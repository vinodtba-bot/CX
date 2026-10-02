"""Mid-conversation tools the Retell agent calls.

Each tool receives the conversation's CallSession and enforces two rules
before touching FACETS:
  1. The caller has passed identity verification in this conversation
     (or arrived pre-verified from a logged-in portal session).
  2. The record asked about belongs to the verified caller: a member sees
     only their own data, a provider only their own claims, and a provider
     asking about a patient must supply that patient's member ID and DOB.
The returned dict is what the LLM reads, so every result carries a short
plain-language `summary` and only the fields the agent needs to answer.
"""

import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from ..db import CallSession
from .facets import FacetsClient, FacetsNotFound, FacetsUnavailable
from .store import audit


@dataclass
class ToolContext:
    db: AsyncSession
    facets: FacetsClient
    session: CallSession
    config: dict
    max_verification_attempts: int = 3


class ToolError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message


# ---------- normalization helpers ----------

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}


def normalize_dob(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.strip().lower().replace(",", " ")
    s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", s)
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%m%d%Y"):
        try:
            return datetime.strptime(s.replace(" ", ""), fmt).date().isoformat()
        except ValueError:
            pass
    parts = s.split()
    if len(parts) == 3 and parts[0] in MONTHS:
        try:
            return date(int(parts[2]), MONTHS[parts[0]], int(parts[1])).isoformat()
        except ValueError:
            return None
    return None


def normalize_id(raw: str | None, prefix: str) -> str | None:
    """Callers say "nine eight seven six five four" or type "mem987654"."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    return f"{prefix}-{digits}" if digits else None


def digits_only(raw: str | None) -> str:
    return re.sub(r"\D", "", raw or "")


def money(v: float | None) -> str | None:
    return None if v is None else f"${v:,.2f}"


# ---------- authorization guards ----------

def require_verified(ctx: ToolContext) -> None:
    if not ctx.session.verified:
        raise ToolError(
            "not_verified",
            "The caller has not been verified yet. Verify identity before sharing any account information.",
        )


def require_persona(ctx: ToolContext, persona: str) -> None:
    if ctx.session.persona != persona:
        raise ToolError("wrong_line", f"This tool is only available on the {persona} services line.")


async def provider_patient_check(ctx: ToolContext, member_id_raw: str | None, dob_raw: str | None) -> dict:
    """A verified provider must name the patient by member ID + DOB."""
    member_id = normalize_id(member_id_raw, "MEM")
    dob = normalize_dob(dob_raw)
    if not member_id or not dob:
        raise ToolError("missing_patient", "Ask the provider for the patient's member ID and date of birth.")
    try:
        member = await ctx.facets.get_member(member_id)
    except FacetsNotFound:
        raise ToolError("patient_not_found", "No member matches that member ID and date of birth.")
    if member["dateOfBirth"] != dob:
        raise ToolError("patient_not_found", "No member matches that member ID and date of birth.")
    return member


# ---------- tools ----------

async def verify_member_identity(ctx: ToolContext, args: dict) -> dict:
    require_persona(ctx, "member")
    s = ctx.session
    if s.verified:
        return {"result": "already_verified", "summary": "The caller is already verified."}
    if s.verification_attempts >= ctx.max_verification_attempts:
        raise ToolError("locked", "Too many failed verification attempts. Offer to transfer to a representative.")
    s.verification_attempts += 1

    member_id = normalize_id(args.get("member_id"), "MEM") or s.ani_member_id
    dob = normalize_dob(args.get("date_of_birth"))
    if not member_id:
        return {"result": "need_member_id", "summary": "Ask the caller for the member ID on their insurance card."}
    if not dob:
        return {"result": "need_dob", "summary": "Ask the caller for their date of birth, including the year."}
    try:
        member = await ctx.facets.get_member(member_id)
        ok = member["dateOfBirth"] == dob
    except FacetsNotFound:
        member, ok = None, False
    if not ok:
        remaining = ctx.max_verification_attempts - s.verification_attempts
        return {
            "result": "failed",
            "attempts_remaining": remaining,
            "summary": "That information did not match our records. Do not say which part was wrong."
            + (" Ask them to try again." if remaining > 0 else " Offer to transfer to a representative."),
        }
    s.verified = True
    s.member_id = member["memberId"]
    s.verification_method = "ani_plus_dob" if not args.get("member_id") else "member_id_plus_dob"
    return {
        "result": "verified",
        "first_name": member["firstName"],
        "plan_name": member["planDescription"],
        "summary": f"Verified. You are speaking with {member['firstName']}. Address them by first name only.",
    }


async def verify_provider_identity(ctx: ToolContext, args: dict) -> dict:
    require_persona(ctx, "provider")
    s = ctx.session
    if s.verified:
        return {"result": "already_verified", "summary": "The provider office is already verified."}
    if s.verification_attempts >= ctx.max_verification_attempts:
        raise ToolError("locked", "Too many failed verification attempts. Offer to transfer to a representative.")
    s.verification_attempts += 1
    npi, tax_id = digits_only(args.get("npi")), digits_only(args.get("tax_id"))
    if len(npi) != 10 or len(tax_id) != 9:
        return {"result": "need_info", "summary": "Ask for the 10-digit NPI and the 9-digit tax ID."}
    try:
        provider = await ctx.facets.get_provider(npi)
        ok = provider["taxId"] == tax_id
    except FacetsNotFound:
        provider, ok = None, False
    if not ok:
        return {
            "result": "failed",
            "attempts_remaining": ctx.max_verification_attempts - s.verification_attempts,
            "summary": "The NPI and tax ID did not match our records. Ask them to confirm and try again.",
        }
    s.verified = True
    s.provider_npi, s.provider_tax_id = npi, tax_id
    s.verification_method = "npi_plus_tin"
    return {
        "result": "verified",
        "provider_name": provider["name"],
        "network_status": provider["networkStatus"],
        "contract_tier": provider["contractTier"],
        "credentialing_status": provider["credentialingStatus"],
        "summary": f"Verified {provider['name']}, {provider['networkStatus']}, credentialing status {provider['credentialingStatus']}.",
    }


def _accumulator_view(acc: dict) -> dict:
    ded_rem = max(acc["deductibleIndividualTotal"] - acc["deductibleIndividualMet"], 0)
    oop_rem = max(acc["outOfPocketIndividualTotal"] - acc["outOfPocketIndividualMet"], 0)
    return {
        "plan_year": acc["planYear"],
        "deductible_individual": {"total": money(acc["deductibleIndividualTotal"]), "met": money(acc["deductibleIndividualMet"]), "remaining": money(ded_rem)},
        "deductible_family": {"total": money(acc["deductibleFamilyTotal"]), "met": money(acc["deductibleFamilyMet"]),
                              "remaining": money(max(acc["deductibleFamilyTotal"] - acc["deductibleFamilyMet"], 0))},
        "out_of_pocket_individual": {"total": money(acc["outOfPocketIndividualTotal"]), "met": money(acc["outOfPocketIndividualMet"]), "remaining": money(oop_rem)},
        "out_of_pocket_family": {"total": money(acc["outOfPocketFamilyTotal"]), "met": money(acc["outOfPocketFamilyMet"]),
                                 "remaining": money(max(acc["outOfPocketFamilyTotal"] - acc["outOfPocketFamilyMet"], 0))},
        "_ded_rem": ded_rem,
        "_oop_rem": oop_rem,
    }


async def _coverage_payload(ctx: ToolContext, member_id: str) -> dict:
    elig = await ctx.facets.get_eligibility(member_id)
    acc = _accumulator_view(await ctx.facets.get_accumulators(member_id))
    ded_rem, oop_rem = acc.pop("_ded_rem"), acc.pop("_oop_rem")
    pcp = elig.get("pcp")
    if not elig["eligible"]:
        summary = f"Coverage is not active. The {elig['planDescription']} plan ended on {elig['coverageTermDate']}."
    else:
        summary = (
            f"Coverage is active on {elig['planDescription']}. "
            f"Individual deductible: {money(ded_rem)} remaining of {acc['deductible_individual']['total']}. "
            f"Out-of-pocket maximum: {money(oop_rem)} remaining of {acc['out_of_pocket_individual']['total']}."
        )
        if pcp:
            summary += f" Primary care physician on file is {pcp['name']} at {pcp['practice']}."
    if not ctx.config.get("disclose_dollar_amounts", True):
        acc = {"plan_year": acc["plan_year"]}
        summary = summary.split(" Individual deductible")[0] + " Dollar amounts are available in the member portal."
    return {
        "eligible": elig["eligible"],
        "status": elig["status"],
        "plan_name": elig["planDescription"],
        "product_type": elig["productType"],
        "group_name": elig["groupName"],
        "coverage_effective_date": elig["coverageEffectiveDate"],
        "coverage_term_date": elig["coverageTermDate"],
        "primary_care_physician": {"name": pcp["name"], "practice": pcp["practice"], "phone": pcp["phone"]} if pcp else None,
        "accumulators": acc,
        "summary": summary,
    }


async def get_coverage_and_accumulators(ctx: ToolContext, args: dict) -> dict:
    require_persona(ctx, "member")
    require_verified(ctx)
    return await _coverage_payload(ctx, ctx.session.member_id)


async def check_member_eligibility(ctx: ToolContext, args: dict) -> dict:
    require_persona(ctx, "provider")
    require_verified(ctx)
    member = await provider_patient_check(ctx, args.get("member_id"), args.get("date_of_birth"))
    payload = await _coverage_payload(ctx, member["memberId"])
    payload["patient_first_name"] = member["firstName"]
    return payload


def _claim_view(claim: dict) -> dict:
    status = claim["adjudicationStatus"]
    view = {
        "claim_id": claim["claimId"],
        "status": status,
        "date_of_service": claim["dateOfService"],
        "received_date": claim["receivedDate"],
        "billed_amount": money(claim["totalBilledAmount"]),
        "allowed_amount": money(claim["allowedAmount"]),
        "paid_amount": money(claim["paidAmount"]),
        "member_responsibility": money(claim["memberResponsibility"]),
        "adjudicated_date": claim["adjudicatedDate"],
        "payment_reference": claim["checkNumber"],
        "explanation_code": claim["explanationCode"],
        "explanation": claim.get("explanationDescription"),
    }
    if status == "PAID":
        view["summary"] = (
            f"Claim {claim['claimId']} for the {claim['dateOfService']} visit was paid on {claim['adjudicatedDate']}. "
            f"Plan paid {money(claim['paidAmount'])}; member responsibility is {money(claim['memberResponsibility'])}. "
            f"Payment reference {claim['checkNumber']}."
        )
    elif status == "DENIED":
        view["summary"] = (
            f"Claim {claim['claimId']} for the {claim['dateOfService']} visit was denied on {claim['adjudicatedDate']}. "
            f"Reason ({claim['explanationCode']}): {claim.get('explanationDescription')}"
        )
        if claim.get("originalClaimId"):
            view["summary"] += f" The original claim is {claim['originalClaimId']}."
    elif status == "PENDED":
        view["summary"] = (
            f"Claim {claim['claimId']} received {claim['receivedDate']} is pending. "
            f"{claim.get('explanationDescription') or ''}"
        ).strip()
    else:
        view["summary"] = f"Claim {claim['claimId']} status is {status}."
    return view


async def check_claim_status(ctx: ToolContext, args: dict) -> dict:
    require_verified(ctx)
    if not ctx.config.get("allow_claim_status", True):
        raise ToolError("disabled", "Claim status by phone is turned off. Offer a transfer.")
    s = ctx.session
    claim_id = normalize_id(args.get("claim_id"), "CLM")

    if not claim_id:
        # No claim number: list the caller's most recent claims.
        if s.persona == "member":
            claims = await ctx.facets.list_member_claims(s.member_id)
        else:
            claims = await ctx.facets.list_provider_claims(s.provider_npi)
        recent = [_claim_view({**c, "explanationDescription": None}) for c in claims[:3]]
        return {
            "claims": [{k: c[k] for k in ("claim_id", "status", "date_of_service", "billed_amount")} for c in recent],
            "summary": "Most recent claims: " + "; ".join(
                f"{c['claim_id']} on {c['date_of_service']}, {c['status'].lower()}" for c in recent
            ) if recent else "No claims found.",
        }

    try:
        claim = await ctx.facets.get_claim_status(claim_id)
    except FacetsNotFound:
        return {"result": "not_found", "summary": f"No claim found with number {claim_id}. Ask the caller to confirm the number."}
    owned = (
        claim["patientMemberId"] == s.member_id if s.persona == "member"
        else claim["providerTaxId"] == s.provider_tax_id
    )
    if not owned:
        # Same answer as not-found so the agent can't be used to probe for claims.
        return {"result": "not_found", "summary": f"No claim found with number {claim_id}. Ask the caller to confirm the number."}
    return {"result": "found", **_claim_view(claim)}


async def check_procedure_coverage(ctx: ToolContext, args: dict) -> dict:
    require_verified(ctx)
    if not ctx.config.get("allow_benefit_checks", True):
        raise ToolError("disabled", "Benefit checks are turned off. Offer a transfer.")
    s = ctx.session
    cpt = digits_only(args.get("cpt_code"))[:5]
    if len(cpt) != 5:
        return {"result": "need_code", "summary": "Ask for the five-digit CPT procedure code."}
    if s.persona == "member":
        member_id = s.member_id
        provider_npi = digits_only(args.get("provider_npi")) or None
    else:
        member_id = (await provider_patient_check(ctx, args.get("member_id"), args.get("date_of_birth")))["memberId"]
        provider_npi = s.provider_npi
    try:
        b = await ctx.facets.get_procedure_benefit(member_id, cpt, provider_npi)
    except FacetsNotFound:
        return {"result": "no_rule", "summary": f"No benefit configuration found for code {cpt}. Offer a transfer for a manual review."}

    net = b.get(b["networkApplied"], {})
    if net.get("covered") is False:
        cost = "not covered out of network"
    elif "copay" in net:
        cost = f"{money(net['copay'])} copay"
    elif "coinsurancePct" in net:
        cost = f"{net['coinsurancePct']}% coinsurance" + (" after deductible" if net.get("subjectToDeductible") else "")
    else:
        cost = "covered"
    network_label = "in network" if b["networkApplied"] == "inNetwork" else "out of network"
    parts = [f"{b['procedureDescription']} (CPT {cpt}) is {'covered' if b['covered'] else 'not covered'}: {cost} {network_label}."]
    parts.append("Prior authorization IS required." if b.get("priorAuthRequired") else "No prior authorization is required.")
    if b.get("referralRequired"):
        parts.append("A referral from the primary care physician is required.")
    if b.get("visitLimit"):
        parts.append(f"Visit limit {b['visitLimit']} per year, {b.get('visitsUsed', 0)} used.")
    return {
        "procedure_code": cpt,
        "procedure_description": b["procedureDescription"],
        "covered": b["covered"],
        "network_applied": network_label,
        "cost_share": cost,
        "prior_auth_required": b.get("priorAuthRequired", False),
        "referral_required": b.get("referralRequired", False),
        "visit_limit": b.get("visitLimit"),
        "visits_used": b.get("visitsUsed"),
        "summary": " ".join(parts) + " This is a benefit estimate, not a guarantee of payment.",
    }


async def get_prior_authorizations(ctx: ToolContext, args: dict) -> dict:
    require_verified(ctx)
    if not ctx.config.get("allow_prior_auth_lookup", True):
        raise ToolError("disabled", "Prior authorization lookup is turned off. Offer a transfer.")
    s = ctx.session
    if s.persona == "member":
        member_id = s.member_id
    else:
        member_id = (await provider_patient_check(ctx, args.get("member_id"), args.get("date_of_birth")))["memberId"]
    auths = await ctx.facets.list_prior_auths(member_id)
    items = [
        {
            "auth_id": a["authId"],
            "procedure": a["procedureDescription"],
            "procedure_code": a["procedureCode"],
            "status": a["status"],
            "requested_date": a["requestedDate"],
            "valid_through": a["validThrough"],
        }
        for a in auths
    ]
    summary = "; ".join(
        f"{i['procedure']} ({i['auth_id']}) is {i['status'].replace('_', ' ').lower()}"
        + (f", valid through {i['valid_through']}" if i["valid_through"] else "")
        for i in items
    )
    return {"authorizations": items, "summary": summary or "No prior authorizations on file."}


async def create_service_request(ctx: ToolContext, args: dict) -> dict:
    require_verified(ctx)
    s = ctx.session
    category = (args.get("category") or "general").strip()[:64]
    summary = (args.get("summary") or "").strip()[:1000]
    if not summary:
        return {"result": "need_summary", "summary": "Summarize what the caller needs before creating the request."}
    record = await ctx.facets.create_inquiry({
        "memberId": s.member_id,
        "providerNpi": s.provider_npi,
        "category": category,
        "summary": summary,
        "source": "AI_AGENT",
        "externalCallId": s.call_id,
    })
    return {
        "reference_number": record["inquiryId"],
        "summary": f"Service request {record['inquiryId']} was created. A representative will follow up within two business days.",
    }


Tool = Callable[[ToolContext, dict], Awaitable[dict]]

TOOLS: dict[str, Tool] = {
    "verify_member_identity": verify_member_identity,
    "verify_provider_identity": verify_provider_identity,
    "get_coverage_and_accumulators": get_coverage_and_accumulators,
    "check_member_eligibility": check_member_eligibility,
    "check_claim_status": check_claim_status,
    "check_procedure_coverage": check_procedure_coverage,
    "get_prior_authorizations": get_prior_authorizations,
    "create_service_request": create_service_request,
}


async def run_tool(ctx: ToolContext, name: str, args: dict) -> dict:
    """Execute a tool with uniform error handling and an audit record."""
    fn = TOOLS.get(name)
    started = time.monotonic()
    if fn is None:
        result, outcome = {"error": "unknown_tool", "summary": f"Unknown tool {name}."}, "unknown_tool"
    else:
        try:
            result = await fn(ctx, args or {})
            outcome = result.get("result", "ok")
        except ToolError as e:
            result, outcome = {"error": e.code, "summary": e.message}, e.code
        except FacetsUnavailable:
            result = {
                "error": "core_unavailable",
                "summary": "The claims system is not responding right now. Apologize, do not guess at figures, and offer to transfer or create a service request.",
            }
            outcome = "core_unavailable"
    await audit(
        ctx.db,
        actor=f"agent:{ctx.session.persona}",
        action=f"tool.{name}",
        outcome=outcome,
        call_id=ctx.session.call_id,
        latency_ms=int((time.monotonic() - started) * 1000),
        detail={k: v for k, v in (args or {}).items()},
    )
    return result
