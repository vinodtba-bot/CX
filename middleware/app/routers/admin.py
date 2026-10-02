from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import AuditEvent, CallLog, session_scope
from ..security import require_admin
from ..services.store import DEFAULT_AGENT_CONFIG, audit, get_agent_config, save_agent_config

router = APIRouter(prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _call_row(c: CallLog, full: bool = False) -> dict:
    row = {
        "call_id": c.call_id,
        "channel": c.channel,
        "persona": c.persona,
        "direction": c.direction,
        "status": c.call_status,
        "started_at": c.started_at.isoformat() if c.started_at else None,
        "ended_at": c.ended_at.isoformat() if c.ended_at else None,
        "duration_ms": c.duration_ms,
        "disconnection_reason": c.disconnection_reason,
        "verified": c.verified,
        "transferred": c.transferred,
        "sentiment": c.sentiment,
        "call_successful": c.call_successful,
        "summary": c.summary,
        "tools_used": c.tools_used or [],
    }
    if full:
        row["transcript_redacted"] = c.transcript_redacted
        row["analysis"] = c.analysis
    return row


@router.get("/stats")
async def stats(days: int = Query(30, ge=1, le=365), db: AsyncSession = Depends(session_scope)):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (await db.execute(select(CallLog).where(CallLog.created_at >= since))).scalars().all()
    total = len(rows)
    transferred = sum(1 for r in rows if r.transferred)
    durations = [r.duration_ms for r in rows if r.duration_ms]
    by_day: dict[str, int] = {}
    for r in rows:
        day = (r.started_at or r.created_at).date().isoformat()
        by_day[day] = by_day.get(day, 0) + 1
    tool_counts: dict[str, int] = {}
    for r in rows:
        for t in r.tools_used or []:
            tool_counts[t] = tool_counts.get(t, 0) + 1
    sentiment: dict[str, int] = {}
    for r in rows:
        sentiment[r.sentiment or "Unknown"] = sentiment.get(r.sentiment or "Unknown", 0) + 1
    tool_errors = (await db.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.ts >= since, AuditEvent.action.like("tool.%"), AuditEvent.outcome == "core_unavailable")
    )).scalar_one()
    return {
        "window_days": days,
        "total_conversations": total,
        "by_channel": {ch: sum(1 for r in rows if r.channel == ch) for ch in ("phone", "web_call", "chat")},
        "by_persona": {p: sum(1 for r in rows if r.persona == p) for p in ("member", "provider")},
        "containment_rate": round((total - transferred) / total, 3) if total else None,
        "transfer_count": transferred,
        "verified_rate": round(sum(1 for r in rows if r.verified) / total, 3) if total else None,
        "avg_handle_time_seconds": round(sum(durations) / len(durations) / 1000, 1) if durations else None,
        "total_minutes": round(sum(durations) / 60000, 1),
        "conversations_by_day": dict(sorted(by_day.items())),
        "tool_usage": dict(sorted(tool_counts.items(), key=lambda kv: -kv[1])),
        "sentiment": sentiment,
        "core_system_errors": tool_errors,
    }


@router.get("/calls")
async def list_calls(
    persona: str | None = None,
    channel: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(session_scope),
):
    q = select(CallLog).order_by(CallLog.created_at.desc()).limit(limit)
    if persona:
        q = q.where(CallLog.persona == persona)
    if channel:
        q = q.where(CallLog.channel == channel)
    return {"results": [_call_row(c) for c in (await db.execute(q)).scalars().all()]}


@router.get("/calls/{call_id}")
async def get_call(call_id: str, db: AsyncSession = Depends(session_scope), actor: str = Depends(require_admin)):
    c = await db.get(CallLog, call_id)
    if c is None:
        raise HTTPException(404, "Call not found")
    events = (await db.execute(
        select(AuditEvent).where(AuditEvent.call_id == call_id).order_by(AuditEvent.ts)
    )).scalars().all()
    # Reading a transcript is itself a PHI access event.
    await audit(db, actor=actor, action="call_log.view", outcome="ok", call_id=call_id)
    return {
        **_call_row(c, full=True),
        "events": [
            {"ts": e.ts.isoformat(), "actor": e.actor, "action": e.action, "outcome": e.outcome,
             "latency_ms": e.latency_ms, "detail": e.detail}
            for e in events
        ],
    }


@router.get("/audit")
async def list_audit(limit: int = Query(100, ge=1, le=1000), db: AsyncSession = Depends(session_scope)):
    rows = (await db.execute(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit))).scalars().all()
    return {"results": [
        {"id": e.id, "ts": e.ts.isoformat(), "call_id": e.call_id, "actor": e.actor, "action": e.action,
         "outcome": e.outcome, "latency_ms": e.latency_ms, "detail": e.detail}
        for e in rows
    ]}


class AgentConfigIn(BaseModel):
    payer_name: str = Field(min_length=1, max_length=120)
    member_greeting: str = Field(max_length=600)
    provider_greeting: str = Field(max_length=600)
    business_hours: str = Field(max_length=200)
    member_services_transfer_number: str = Field(pattern=r"^\+[1-9]\d{6,14}$")
    provider_services_transfer_number: str = Field(pattern=r"^\+[1-9]\d{6,14}$")
    nurse_line_number: str = Field(pattern=r"^\+[1-9]\d{6,14}$")
    escalation_topics: list[str] = Field(max_length=30)
    allow_claim_status: bool
    allow_benefit_checks: bool
    allow_prior_auth_lookup: bool
    disclose_dollar_amounts: bool
    plan_year_note: str = Field(max_length=300)


@router.get("/agent-config")
async def read_agent_config(db: AsyncSession = Depends(session_scope)):
    return {"config": await get_agent_config(db), "defaults": DEFAULT_AGENT_CONFIG}


@router.put("/agent-config")
async def update_agent_config(body: AgentConfigIn, db: AsyncSession = Depends(session_scope),
                              actor: str = Depends(require_admin)):
    return {"config": await save_agent_config(db, body.model_dump(), actor)}
