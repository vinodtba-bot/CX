"""Endpoints Retell calls: inbound-call context, mid-call tools, and the
post-call webhook. Every route verifies X-Retell-Signature on the raw body."""

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings, get_settings
from ..db import CallLog, CallSession, session_scope
from ..security import retell_verified_body
from ..services.context import build_dynamic_variables, persona_for_agent
from ..services.facets import FacetsError, get_facets
from ..services.redaction import redact_text
from ..services.store import audit, get_agent_config, get_call_session
from ..services.tools import TOOLS, ToolContext, run_tool

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/retell", tags=["retell"])


@router.post("/inbound")
async def inbound_call(
    raw: bytes = Depends(retell_verified_body),
    db: AsyncSession = Depends(session_scope),
    settings: Settings = Depends(get_settings),
):
    """Retell's inbound call webhook (set as the phone number's
    inbound_webhook_url). Must answer within 10s; Retell retries up to 3
    times, so this is idempotent on call_id."""
    payload = json.loads(raw)
    if payload.get("event") != "call_inbound":
        return {}
    inbound = payload.get("call_inbound", {})
    call_id = inbound.get("call_id")
    agent_id = inbound.get("agent_id")
    persona = persona_for_agent(agent_id, settings)
    config = await get_agent_config(db)

    session = await get_call_session(db, call_id) if call_id else None
    if session is None:
        ani_member_id = None
        if persona == "member" and inbound.get("from_number"):
            # Caller ID is a hint, never authentication: it only lets the agent
            # skip asking for the member ID. DOB is still required.
            try:
                hits = await get_facets().find_members_by_phone(inbound["from_number"])
                if len(hits) == 1:
                    ani_member_id = hits[0]["memberId"]
            except FacetsError:
                log.warning("ANI lookup failed; continuing without it")
        session = CallSession(
            call_id=call_id or f"unknown-{datetime.now(timezone.utc).timestamp()}",
            channel="phone",
            persona=persona,
            agent_id=agent_id,
            from_number=inbound.get("from_number"),
            ani_member_id=ani_member_id,
        )
        db.add(session)
        await audit(db, actor="retell", action="call.inbound", outcome="ok", call_id=session.call_id,
                    detail={"persona": persona, "ani_match": bool(ani_member_id)})

    return {
        "call_inbound": {
            "dynamic_variables": build_dynamic_variables(session, config),
            "metadata": {"payer_organization_id": settings.payer_org_id, "persona": persona},
        }
    }


def _conversation_ids(payload: dict) -> tuple[str | None, str | None, str]:
    """Tool calls carry `call` for voice and `chat` for text agents."""
    if payload.get("call"):
        c = payload["call"]
        channel = "web_call" if c.get("call_type") == "web_call" else "phone"
        return c.get("call_id"), c.get("agent_id"), channel
    if payload.get("chat"):
        c = payload["chat"]
        return c.get("chat_id"), c.get("agent_id"), "chat"
    return None, None, "phone"


@router.post("/tools/{tool_name}")
async def tool_call(
    tool_name: str,
    raw: bytes = Depends(retell_verified_body),
    db: AsyncSession = Depends(session_scope),
    settings: Settings = Depends(get_settings),
):
    """Custom-function endpoint. Retell POSTs {name, call|chat, args}. The
    response body is read by the LLM, so it is always a 200 with a summary,
    even on authorization failures."""
    payload = json.loads(raw)
    args = payload.get("args", {}) or {}
    call_id, agent_id, channel = _conversation_ids(payload)
    if not call_id:
        return {"error": "missing_call", "summary": "Unable to identify this conversation."}

    session = await get_call_session(db, call_id)
    if session is None:
        # Inbound webhook not configured or an outbound/test call: start
        # unverified, the tool guards do the rest.
        session = CallSession(call_id=call_id, channel=channel, persona=persona_for_agent(agent_id, settings), agent_id=agent_id)
        db.add(session)
        await db.flush()
    if session.status != "active":
        return {"error": "conversation_closed", "summary": "This conversation has ended."}

    name = tool_name if tool_name in TOOLS else payload.get("name", tool_name)
    ctx = ToolContext(
        db=db, facets=get_facets(), session=session, config=await get_agent_config(db),
        max_verification_attempts=settings.max_verification_attempts,
    )
    return await run_tool(ctx, name, args)


def _ts(ms: int | None) -> datetime | None:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc) if ms else None


def _tools_used(transcript_with_tool_calls: list | None) -> list[str]:
    names = []
    for item in transcript_with_tool_calls or []:
        if item.get("role") == "tool_call_invocation" and item.get("name"):
            names.append(item["name"])
    return names


@router.post("/webhook", status_code=204)
async def webhook(
    raw: bytes = Depends(retell_verified_body),
    db: AsyncSession = Depends(session_scope),
):
    """Post-call webhook (agent webhook_url). Stores a redacted log, usage and
    analysis; closes the transient session. Idempotent per call_id."""
    payload = json.loads(raw)
    event = payload.get("event", "")
    obj = payload.get("call") or payload.get("chat") or {}
    call_id = obj.get("call_id") or obj.get("chat_id")
    if not call_id:
        return Response(status_code=204)

    channel = "chat" if "chat" in payload else ("web_call" if obj.get("call_type") == "web_call" else "phone")
    session = await get_call_session(db, call_id)
    log_row = await db.get(CallLog, call_id)
    if log_row is None:
        log_row = CallLog(call_id=call_id, channel=channel)
        db.add(log_row)

    log_row.agent_id = obj.get("agent_id") or log_row.agent_id
    log_row.direction = obj.get("direction") or log_row.direction
    log_row.call_status = obj.get("call_status") or obj.get("chat_status") or log_row.call_status
    log_row.persona = (session.persona if session else None) or (obj.get("metadata") or {}).get("persona") or log_row.persona
    log_row.verified = bool(session and session.verified) or log_row.verified
    log_row.started_at = _ts(obj.get("start_timestamp")) or log_row.started_at
    log_row.ended_at = _ts(obj.get("end_timestamp")) or log_row.ended_at
    if obj.get("duration_ms") is not None:
        log_row.duration_ms = obj["duration_ms"]
    elif log_row.started_at and log_row.ended_at:
        log_row.duration_ms = int((log_row.ended_at - log_row.started_at).total_seconds() * 1000)

    if event.startswith("transfer_") or obj.get("disconnection_reason") == "call_transfer":
        log_row.transferred = True
    if obj.get("disconnection_reason"):
        log_row.disconnection_reason = obj["disconnection_reason"]
    if obj.get("transcript"):
        log_row.transcript_redacted = redact_text(obj["transcript"])
    elif obj.get("messages"):  # chat transcript
        log_row.transcript_redacted = redact_text(
            "\n".join(f"{'Agent' if m.get('role') == 'agent' else 'User'}: {m.get('content', '')}"
                      for m in obj["messages"] if m.get("role") in ("agent", "user"))
        )
    tools = _tools_used(obj.get("transcript_with_tool_calls") or obj.get("message_with_tool_calls"))
    if tools:
        log_row.tools_used = tools

    analysis = obj.get("call_analysis") or obj.get("chat_analysis")
    if analysis:
        log_row.summary = redact_text(analysis.get("call_summary") or analysis.get("chat_summary"))
        log_row.sentiment = analysis.get("user_sentiment")
        log_row.call_successful = analysis.get("call_successful", analysis.get("chat_successful"))
        custom = analysis.get("custom_analysis_data")
        log_row.analysis = {k: redact_text(v) if isinstance(v, str) else v for k, v in (custom or {}).items()} or None

    if event in ("call_ended", "chat_ended") and session is not None:
        session.status = "closed"
    await audit(db, actor="retell", action=f"webhook.{event}", outcome="ok", call_id=call_id)
    return Response(status_code=204)
