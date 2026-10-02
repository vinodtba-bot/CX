"""Endpoints the embeddable web widget calls. Every request carries the
payer portal's signed identity token, so web conversations start already
verified and the browser never holds a Retell API key or chooses the
caller's identity."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings, get_settings
from ..db import CallLog, CallSession, session_scope
from ..security import PortalIdentity, require_portal_identity
from ..services import retell_api, simulated_agent
from ..services.context import build_dynamic_variables
from ..services.facets import FacetsError, get_facets
from ..services.redaction import redact_text
from ..services.store import audit, get_agent_config, get_call_session
from ..services.tools import ToolContext

router = APIRouter(prefix="/api/v1/widget", tags=["widget"])


def _new_session(call_id: str, channel: str, ident: PortalIdentity, agent_id: str | None) -> CallSession:
    return CallSession(
        call_id=call_id,
        channel=channel,
        persona=ident.persona,
        agent_id=agent_id,
        member_id=ident.member_id,
        provider_npi=ident.provider_npi,
        provider_tax_id=ident.provider_tax_id,
        verified=True,
        verification_method="portal_sso",
    )


async def _first_name(ident: PortalIdentity) -> str | None:
    if ident.persona != "member":
        return ident.display_name
    try:
        return (await get_facets().get_member(ident.member_id))["firstName"]
    except FacetsError:
        return None


def _owns(session: CallSession, ident: PortalIdentity) -> bool:
    if session.persona != ident.persona:
        return False
    if ident.persona == "member":
        return session.member_id == ident.member_id
    return session.provider_npi == ident.provider_npi


@router.get("/config")
async def widget_config(ident: PortalIdentity = Depends(require_portal_identity),
                        db: AsyncSession = Depends(session_scope),
                        settings: Settings = Depends(get_settings)):
    cfg = await get_agent_config(db)
    voice_agent = settings.retell_member_agent_id if ident.persona == "member" else settings.retell_provider_agent_id
    chat_agent = settings.retell_member_chat_agent_id if ident.persona == "member" else settings.retell_provider_chat_agent_id
    return {
        "payer_name": cfg["payer_name"],
        "persona": ident.persona,
        "voice_enabled": bool(settings.retell_api_key and voice_agent),
        "chat_mode": "retell" if (settings.retell_api_key and chat_agent) else ("simulated" if settings.demo_mode else "disabled"),
    }


# The browser SDK (retell-client-js-sdk 3.x RetellClient) is pointed at this
# prefix with a custom fetch, so its POST /v3/create-web-call lands here. The
# request body from the browser is ignored: agent, identity and context are
# decided server-side from the portal token.
@router.post("/voice/v3/create-web-call", status_code=201)
async def create_web_call(ident: PortalIdentity = Depends(require_portal_identity),
                          db: AsyncSession = Depends(session_scope),
                          settings: Settings = Depends(get_settings)):
    agent_id = settings.retell_member_agent_id if ident.persona == "member" else settings.retell_provider_agent_id
    if not (settings.retell_api_key and agent_id):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Voice agent is not configured")
    cfg = await get_agent_config(db)
    placeholder = _new_session("pending", "web_call", ident, agent_id)
    dv = build_dynamic_variables(placeholder, cfg, {"first_name": await _first_name(ident)})
    try:
        resp = await retell_api.create_web_call(agent_id, dv, {"payer_organization_id": settings.payer_org_id, "persona": ident.persona})
    except retell_api.RetellAPIError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Could not start the voice session") from e
    db.add(_new_session(resp["call_id"], "web_call", ident, agent_id))
    await audit(db, actor=f"portal:{ident.subject}", action="web_call.create", outcome="ok", call_id=resp["call_id"])
    return resp


class ChatMessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


@router.post("/chat/start")
async def start_chat(ident: PortalIdentity = Depends(require_portal_identity),
                     db: AsyncSession = Depends(session_scope),
                     settings: Settings = Depends(get_settings)):
    cfg = await get_agent_config(db)
    agent_id = settings.retell_member_chat_agent_id if ident.persona == "member" else settings.retell_provider_chat_agent_id
    first_name = await _first_name(ident)
    greeting_name = f", {first_name}" if first_name else ""
    if settings.retell_api_key and agent_id:
        placeholder = _new_session("pending", "chat", ident, agent_id)
        dv = build_dynamic_variables(placeholder, cfg, {"first_name": first_name})
        resp = await retell_api.create_chat(agent_id, dv, {"payer_organization_id": settings.payer_org_id, "persona": ident.persona})
        chat_id, mode = resp["chat_id"], "retell"
    elif settings.demo_mode:
        chat_id, mode = f"simchat_{uuid.uuid4().hex[:16]}", "simulated"
    else:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Chat agent is not configured")
    db.add(_new_session(chat_id, "chat", ident, agent_id or None))
    await audit(db, actor=f"portal:{ident.subject}", action="chat.start", outcome="ok", call_id=chat_id, detail={"mode": mode})
    greeting = f"Hi{greeting_name}! I'm the {cfg['payer_name']} virtual assistant. "
    greeting += simulated_agent.help_text(ident.persona) if mode == "simulated" else "How can I help you today?"
    if mode == "simulated":
        simulated_agent.TRANSCRIPTS[chat_id] = [("Agent", greeting)]
    return {"chat_id": chat_id, "mode": mode, "greeting": greeting}


async def _owned_session(chat_id: str, ident: PortalIdentity, db: AsyncSession) -> CallSession:
    session = await get_call_session(db, chat_id)
    if session is None or not _owns(session, ident) or session.channel != "chat":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat not found")
    if session.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "Chat has ended")
    return session


@router.post("/chat/{chat_id}/messages")
async def send_chat_message(chat_id: str, body: ChatMessageIn,
                            ident: PortalIdentity = Depends(require_portal_identity),
                            db: AsyncSession = Depends(session_scope),
                            settings: Settings = Depends(get_settings)):
    session = await _owned_session(chat_id, ident, db)
    if chat_id.startswith("simchat_"):
        ctx = ToolContext(db=db, facets=get_facets(), session=session, config=await get_agent_config(db),
                          max_verification_attempts=settings.max_verification_attempts)
        return {"messages": [{"role": "agent", "content": await simulated_agent.respond(ctx, body.content)}]}
    try:
        resp = await retell_api.create_chat_completion(chat_id, body.content)
    except retell_api.RetellAPIError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Assistant is unavailable") from e
    return {"messages": [{"role": "agent", "content": m["content"]} for m in resp.get("messages", []) if m.get("role") == "agent"]}


@router.post("/chat/{chat_id}/end", status_code=204)
async def end_chat(chat_id: str,
                   ident: PortalIdentity = Depends(require_portal_identity),
                   db: AsyncSession = Depends(session_scope)):
    session = await _owned_session(chat_id, ident, db)
    if chat_id.startswith("simchat_"):
        # No Retell webhook will arrive for a simulated chat, so log it here.
        transcript = simulated_agent.TRANSCRIPTS.pop(chat_id, [])
        tools = simulated_agent.TOOLS_USED.pop(chat_id, [])
        now = datetime.now(timezone.utc)
        started = session.created_at if session.created_at.tzinfo else session.created_at.replace(tzinfo=timezone.utc)
        db.add(CallLog(
            call_id=chat_id, channel="chat", persona=session.persona, direction="inbound", call_status="ended",
            started_at=started, ended_at=now, duration_ms=int((now - started).total_seconds() * 1000),
            disconnection_reason="user_ended", verified=True,
            transferred=False,
            transcript_redacted=redact_text("\n".join(f"{who}: {text}" for who, text in transcript)),
            summary=f"Simulated {session.persona} chat; tools used: {', '.join(tools) or 'none'}.",
            sentiment="Unknown", call_successful=bool(tools), tools_used=tools,
        ))
    else:
        try:
            await retell_api.end_chat(chat_id)
        except retell_api.RetellAPIError:
            pass
    session.status = "closed"
    await audit(db, actor=f"portal:{ident.subject}", action="chat.end", outcome="ok", call_id=chat_id)
