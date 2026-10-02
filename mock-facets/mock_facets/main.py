"""Mock TriZetto FACETS gateway.

Stands in for the payer's enterprise API gateway (Apigee / MuleSoft) in front of
FACETS Open Access. Paths and field names are modeled loosely on what a payer
gateway typically exposes; a real engagement maps the payer's actual contract
in middleware/app/services/facets.py, not here.
"""

import asyncio
import os
import random
import uuid
from datetime import date, datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel

from . import data

GATEWAY_KEY = os.getenv("FACETS_GATEWAY_KEY", "dev-facets-gateway-key")
LATENCY_MS = int(os.getenv("FACETS_SIMULATED_LATENCY_MS", "120"))
FAILURE_RATE = float(os.getenv("FACETS_SIMULATED_FAILURE_RATE", "0"))

app = FastAPI(title="Mock TriZetto FACETS Gateway", version="0.1.0")

INQUIRIES: list[dict] = []


async def gateway_auth(x_gateway_key: str = Header(default="")) -> None:
    if x_gateway_key != GATEWAY_KEY:
        raise HTTPException(status_code=401, detail="Invalid gateway key")
    if LATENCY_MS:
        await asyncio.sleep(LATENCY_MS / 1000 * random.uniform(0.5, 1.5))
    if FAILURE_RATE and random.random() < FAILURE_RATE:
        raise HTTPException(status_code=503, detail="FACETS core temporarily unavailable")


def _member(member_id: str) -> dict:
    member = data.MEMBERS.get(member_id.upper())
    if not member:
        raise HTTPException(status_code=404, detail="Member ID not found in FACETS registry")
    return member


def _public_member(m: dict) -> dict:
    return {k: v for k, v in m.items() if k != "accumulators"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/v1/members/search", dependencies=[Depends(gateway_auth)])
async def search_members(phone: str = Query(...)):
    hits = [_public_member(m) for m in data.MEMBERS.values() if m["phone"] == phone]
    return {"results": hits}


@app.get("/v1/members/{member_id}", dependencies=[Depends(gateway_auth)])
async def get_member(member_id: str):
    return _public_member(_member(member_id))


@app.get("/v1/members/{member_id}/eligibility", dependencies=[Depends(gateway_auth)])
async def get_eligibility(member_id: str, asOf: date | None = None):
    m = _member(member_id)
    as_of = asOf or date.today()
    eff = date.fromisoformat(m["coverageEffectiveDate"])
    term = date.fromisoformat(m["coverageTermDate"]) if m["coverageTermDate"] else None
    active = eff <= as_of and (term is None or as_of <= term)
    return {
        "memberId": m["memberId"],
        "asOfDate": as_of.isoformat(),
        "eligible": active,
        "status": m["status"],
        "planId": m["planId"],
        "planDescription": m["planDescription"],
        "productType": m["productType"],
        "groupName": m["groupName"],
        "coverageEffectiveDate": m["coverageEffectiveDate"],
        "coverageTermDate": m["coverageTermDate"],
        "pcp": m["pcp"],
    }


@app.get("/v1/members/{member_id}/accumulators", dependencies=[Depends(gateway_auth)])
async def get_accumulators(member_id: str):
    m = _member(member_id)
    return {
        "memberId": m["memberId"],
        "firstName": m["firstName"],
        "planDescription": m["planDescription"],
        "planYear": data.PLAN_YEAR,
        **m["accumulators"],
    }


@app.get("/v1/members/{member_id}/claims", dependencies=[Depends(gateway_auth)])
async def list_member_claims(member_id: str):
    _member(member_id)
    claims = [c for c in data.CLAIMS.values() if c["patientMemberId"] == member_id.upper()]
    return {"results": sorted(claims, key=lambda c: c["dateOfService"], reverse=True)}


@app.get("/v1/members/{member_id}/prior-authorizations", dependencies=[Depends(gateway_auth)])
async def list_prior_auths(member_id: str):
    _member(member_id)
    return {"results": [a for a in data.PRIOR_AUTHS.values() if a["memberId"] == member_id.upper()]}


@app.get("/v1/claims/{claim_id}/status", dependencies=[Depends(gateway_auth)])
async def get_claim_status(claim_id: str):
    claim = data.CLAIMS.get(claim_id.upper())
    if not claim:
        raise HTTPException(status_code=404, detail="Claim ID not found")
    code = claim["explanationCode"]
    return {**claim, "explanationDescription": data.EXPLANATION_CODES.get(code)}


@app.get("/v1/providers/{npi}", dependencies=[Depends(gateway_auth)])
async def get_provider(npi: str):
    p = data.PROVIDERS.get(npi)
    if not p:
        raise HTTPException(status_code=404, detail="Provider NPI not found")
    return p


@app.get("/v1/providers/{npi}/claims", dependencies=[Depends(gateway_auth)])
async def list_provider_claims(npi: str):
    if npi not in data.PROVIDERS:
        raise HTTPException(status_code=404, detail="Provider NPI not found")
    claims = [c for c in data.CLAIMS.values() if c["providerNpi"] == npi]
    return {"results": sorted(claims, key=lambda c: c["dateOfService"], reverse=True)}


@app.get("/v1/benefits/{member_id}/procedures/{cpt_code}", dependencies=[Depends(gateway_auth)])
async def get_procedure_benefit(member_id: str, cpt_code: str, providerNpi: str | None = None):
    m = _member(member_id)
    rule = data.BENEFIT_RULES.get(m["planId"], {}).get(cpt_code)
    if rule is None:
        raise HTTPException(status_code=404, detail="No benefit configuration for this procedure code")
    network = "inNetwork"
    if providerNpi:
        prov = data.PROVIDERS.get(providerNpi)
        if prov and prov["networkStatus"] != "In-Network":
            network = "outOfNetwork"
    return {
        "memberId": m["memberId"],
        "planId": m["planId"],
        "procedureCode": cpt_code,
        "procedureDescription": data.PROCEDURES.get(cpt_code),
        "networkApplied": network,
        **{k: v for k, v in rule.items()},
    }


class InquiryIn(BaseModel):
    memberId: str | None = None
    providerNpi: str | None = None
    category: str
    summary: str
    source: str = "AI_AGENT"
    externalCallId: str | None = None


@app.post("/v1/inquiries", dependencies=[Depends(gateway_auth)], status_code=201)
async def create_inquiry(body: InquiryIn):
    record = {
        "inquiryId": f"INQ-{uuid.uuid4().hex[:8].upper()}",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "status": "OPEN",
        **body.model_dump(),
    }
    INQUIRIES.append(record)
    return record


@app.get("/v1/inquiries", dependencies=[Depends(gateway_auth)])
async def list_inquiries():
    return {"results": INQUIRIES}
