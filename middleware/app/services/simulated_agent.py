"""Keyword-routed stand-in for the Retell chat agent, used only in demo mode
when no Retell chat agent is configured. It calls the exact same tool layer
the real agent uses, so the FACETS integration, authorization guards and
audit trail can be exercised end to end without a Retell account. It is not
an LLM and is not meant to be.
"""

import re

from .tools import ToolContext, run_tool

TRANSCRIPTS: dict[str, list[tuple[str, str]]] = {}
TOOLS_USED: dict[str, list[str]] = {}

CLAIM_RE = re.compile(r"\bCLM-?\s?\d{4,}\b", re.I)
MEMBER_RE = re.compile(r"\bMEM-?\s?\d{4,}\b", re.I)
DATE_RE = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\b",
    re.I,
)
CPT_RE = re.compile(r"\b\d{5}\b")


def help_text(persona: str) -> str:
    if persona == "member":
        return ("I can check a claim (for example \"status of claim CLM-112233\"), your deductible and out-of-pocket totals, "
                "whether a procedure is covered (\"is CPT 70553 covered?\"), or your prior authorizations. "
                "You can also ask for a representative.")
    return ("I can check claim status (\"claim CLM-334455\"), patient eligibility (\"eligibility for MEM-445566 born 1979-11-02\"), "
            "benefits and prior auth requirements (\"does 70553 need prior auth for MEM-445566 DOB 1979-11-02\"), "
            "or open a service request.")


async def respond(ctx: ToolContext, text: str) -> str:
    chat_id = ctx.session.call_id
    TRANSCRIPTS.setdefault(chat_id, []).append(("User", text))
    reply = await _route(ctx, text)
    TRANSCRIPTS[chat_id].append(("Agent", reply))
    return reply


async def _tool(ctx: ToolContext, name: str, args: dict) -> str:
    TOOLS_USED.setdefault(ctx.session.call_id, []).append(name)
    return (await run_tool(ctx, name, args)).get("summary", "")


def _patient_args(text: str) -> dict:
    m, d = MEMBER_RE.search(text), DATE_RE.search(text)
    return {"member_id": m.group(0) if m else None, "date_of_birth": d.group(0) if d else None}


async def _route(ctx: ToolContext, text: str) -> str:
    t = text.lower()
    persona = ctx.session.persona

    if any(w in t for w in ("representative", "human", "real person", "appeal", "grievance", "complaint")):
        ref = await _tool(ctx, "create_service_request", {"category": "escalation", "summary": text})
        number = ctx.config["member_services_transfer_number" if persona == "member" else "provider_services_transfer_number"]
        return f"{ref} You can also reach a representative at {number}, {ctx.config['business_hours']}."

    if claim := CLAIM_RE.search(text):
        return await _tool(ctx, "check_claim_status", {"claim_id": claim.group(0)})
    if "claim" in t:
        return await _tool(ctx, "check_claim_status", {})

    cpt_match = CPT_RE.search(MEMBER_RE.sub(" ", DATE_RE.sub(" ", text)))
    cpt = cpt_match.group(0) if cpt_match else None
    if cpt and any(w in t for w in ("cpt", "cover", "prior auth", "authorization", "need", "require", "benefit", "cost")):
        args = {"cpt_code": cpt, **(_patient_args(text) if persona == "provider" else {})}
        return await _tool(ctx, "check_procedure_coverage", args)

    if "auth" in t:
        return await _tool(ctx, "get_prior_authorizations", _patient_args(text) if persona == "provider" else {})

    if any(w in t for w in ("deductible", "out of pocket", "out-of-pocket", "oop", "accumulator", "coverage", "eligib", "pcp", "primary care", "plan", "active")):
        if persona == "member":
            return await _tool(ctx, "get_coverage_and_accumulators", {})
        return await _tool(ctx, "check_member_eligibility", _patient_args(text))

    return help_text(persona)
