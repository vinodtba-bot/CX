"""Builds the dynamic variables injected into the Retell prompt at the start
of a conversation. Values must be strings (Retell requirement).

What goes in here is deliberately minimal: identity hints and plan basics.
Detailed figures (accumulators, claims) are fetched by tools only after
verification, so nothing sensitive sits in the prompt of an unverified call.
"""

from ..config import Settings
from ..db import CallSession


def persona_for_agent(agent_id: str | None, settings: Settings) -> str:
    if agent_id and agent_id in {settings.retell_provider_agent_id, settings.retell_provider_chat_agent_id}:
        return "provider"
    return "member"


def build_dynamic_variables(session: CallSession, config: dict, extra: dict | None = None) -> dict[str, str]:
    payer = config["payer_name"]
    persona = session.persona
    greeting_key = "member_greeting" if persona == "member" else "provider_greeting"
    transfer = config["member_services_transfer_number" if persona == "member" else "provider_services_transfer_number"]
    dv = {
        "payer_name": payer,
        "persona": persona,
        "greeting": config[greeting_key].format(payer_name=payer),
        "business_hours": config["business_hours"],
        "transfer_number": transfer,
        "nurse_line_number": config["nurse_line_number"],
        "escalation_topics": ", ".join(config["escalation_topics"]),
        "plan_year_note": config["plan_year_note"],
        "caller_verified": "true" if session.verified else "false",
        "ani_match": "true" if session.ani_member_id else "false",
        "channel": session.channel,
    }
    if extra:
        dv.update({k: str(v) for k, v in extra.items() if v is not None})
    return dv
