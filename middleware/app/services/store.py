"""Small data-access helpers shared by the routers."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import AgentConfig, AuditEvent, CallSession
from .redaction import redact_args

DEFAULT_AGENT_CONFIG: dict = {
    "payer_name": "Acme Health Plan",
    "member_greeting": "Thanks for calling {payer_name} Member Services. I'm an AI assistant and I can help with claims, benefits, deductibles and prior authorizations.",
    "provider_greeting": "Thanks for calling {payer_name} Provider Services. I'm an AI assistant and I can help with claim status, eligibility, benefits and prior authorization requirements.",
    "business_hours": "Monday to Friday, 8 AM to 8 PM Eastern",
    "member_services_transfer_number": "+15555550150",
    "provider_services_transfer_number": "+15555550160",
    "nurse_line_number": "+15555550170",
    "escalation_topics": ["appeals", "grievances", "complaints", "medical necessity disputes", "behavioral health crisis"],
    "allow_claim_status": True,
    "allow_benefit_checks": True,
    "allow_prior_auth_lookup": True,
    "disclose_dollar_amounts": True,
    "plan_year_note": "Plan year runs January 1 to December 31.",
}


async def get_agent_config(db: AsyncSession) -> dict:
    row = (await db.execute(select(AgentConfig).order_by(AgentConfig.id.desc()).limit(1))).scalar_one_or_none()
    merged = dict(DEFAULT_AGENT_CONFIG)
    if row:
        merged.update(row.config)
    return merged


async def save_agent_config(db: AsyncSession, config: dict, actor: str) -> dict:
    db.add(AgentConfig(config=config, updated_by=actor))
    await audit(db, actor=actor, action="agent_config.update", outcome="ok", detail={"keys": sorted(config)})
    return await get_agent_config(db)


async def audit(
    db: AsyncSession,
    *,
    actor: str,
    action: str,
    outcome: str,
    call_id: str | None = None,
    latency_ms: int | None = None,
    detail: dict | None = None,
) -> None:
    db.add(
        AuditEvent(
            call_id=call_id,
            actor=actor,
            action=action,
            outcome=outcome,
            latency_ms=latency_ms,
            detail=redact_args(detail) if detail else None,
        )
    )


async def get_call_session(db: AsyncSession, call_id: str) -> CallSession | None:
    return await db.get(CallSession, call_id)
