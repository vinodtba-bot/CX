#!/usr/bin/env python3
"""Create the Retell LLMs, voice agents and chat agents for member services
and provider services, wired to this middleware.

    # write the JSON configs only (no API calls), e.g. to paste in the dashboard
    python scripts/provision_retell.py --base-url https://<your-tunnel> --dry-run

    # create everything in your Retell workspace
    RETELL_API_KEY=key_... python scripts/provision_retell.py --base-url https://<your-tunnel>

Prints the agent IDs to put in .env. Optionally binds a Retell phone number's
inbound webhook with --member-number / --provider-number.
Request shapes checked against retell-sdk 6.0.1.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "retell" / "prompts"
OUT = ROOT / "retell" / "generated"

PII_CATEGORIES = ["ssn", "credit_card", "bank_account", "password", "pin", "date_of_birth", "driver_license", "passport"]

DEFAULT_DYNAMIC_VARIABLES = {
    "payer_name": "Acme Health Plan",
    "persona": "member",
    "greeting": "Thanks for calling. I'm an AI assistant. How can I help?",
    "business_hours": "Monday to Friday, 8 AM to 8 PM Eastern",
    "transfer_number": "+15555550150",
    "nurse_line_number": "+15555550170",
    "escalation_topics": "appeals, grievances, complaints",
    "plan_year_note": "",
    "caller_verified": "false",
    "ani_match": "false",
    "channel": "phone",
    "first_name": "",
}


def custom_tool(base_url: str, name: str, description: str, properties: dict, required: list[str],
                execution_message: str | None = "One moment while I look that up.") -> dict:
    tool = {
        "type": "custom",
        "name": name,
        "description": description,
        "url": f"{base_url}/api/v1/retell/tools/{name}",
        "method": "POST",
        "parameter_type": "json",
        "parameters": {"type": "object", "properties": properties, "required": required},
        "speak_after_execution": True,
        "speak_during_execution": execution_message is not None,
        "timeout_ms": 8000,
        "max_retry": 0,
    }
    if execution_message:
        tool["execution_message_description"] = execution_message
        tool["execution_message_type"] = "static_text"
    return tool


S = lambda d: {"type": "string", "description": d}  # noqa: E731

PATIENT = {
    "member_id": S("Patient's member ID from their insurance card, e.g. MEM-445566."),
    "date_of_birth": S("Patient's date of birth as YYYY-MM-DD."),
}


def transfer_tool(name: str, description: str) -> dict:
    return {
        "type": "transfer_call",
        "name": name,
        "description": description,
        "transfer_destination": {"type": "predefined", "number": "{{transfer_number}}"},
        "transfer_option": {
            "type": "warm_transfer",
            "show_transferee_as_caller": True,
            "on_hold_music": "relaxing_sound",
            # Whispered to the human representative before the caller joins.
            "private_handoff_option": {
                "type": "prompt",
                "prompt": "In two sentences, tell the representative who is calling (first name and whether they were verified), "
                          "what they asked about, and what you already told them. Never include a full date of birth or SSN.",
            },
        },
    }


def end_tool() -> dict:
    return {"type": "end_call", "name": "end_call", "description": "End the call when the caller says goodbye or has nothing else."}


def member_tools(base_url: str) -> list[dict]:
    return [
        custom_tool(base_url, "verify_member_identity",
                    "Verify the caller's identity. Required before any account information. Pass member_id unless caller ID matched (ani_match is true).",
                    {"member_id": S("Member ID from the insurance card, e.g. MEM-987654."),
                     "date_of_birth": S("Caller's date of birth as YYYY-MM-DD.")},
                    ["date_of_birth"], execution_message=None),
        custom_tool(base_url, "get_coverage_and_accumulators",
                    "Get the verified member's coverage status, plan, primary care physician, and deductible and out-of-pocket totals.",
                    {}, []),
        custom_tool(base_url, "check_claim_status",
                    "Look up a claim by claim number for the verified member. Omit claim_id to list recent claims.",
                    {"claim_id": S("Claim number, e.g. CLM-112233.")}, []),
        custom_tool(base_url, "check_procedure_coverage",
                    "Check if a procedure is covered, the cost share, and whether prior authorization or a referral is needed.",
                    {"cpt_code": S("Five-digit CPT code."),
                     "provider_npi": S("Optional 10-digit NPI of the provider, to apply network status.")},
                    ["cpt_code"]),
        custom_tool(base_url, "get_prior_authorizations",
                    "List the verified member's prior authorizations and their status.", {}, []),
        custom_tool(base_url, "create_service_request",
                    "Create a service request for human follow-up when you cannot complete the caller's request.",
                    {"category": S("Short category, e.g. id_card, address_change, billing_dispute, escalation."),
                     "summary": S("One or two sentence summary of what the caller needs. No SSN or full DOB.")},
                    ["category", "summary"], execution_message="Let me create that request for you."),
        transfer_tool("transfer_to_member_services",
                      "Warm transfer to a licensed member services representative. Use when asked for a person or for escalation topics."),
        end_tool(),
    ]


def provider_tools(base_url: str) -> list[dict]:
    return [
        custom_tool(base_url, "verify_provider_identity",
                    "Verify the provider office by NPI and tax ID. Required before any claim or patient information.",
                    {"npi": S("10-digit billing NPI."), "tax_id": S("9-digit tax ID (TIN/EIN).")},
                    ["npi", "tax_id"], execution_message=None),
        custom_tool(base_url, "check_claim_status",
                    "Look up one of this office's claims by claim number. Omit claim_id to list the office's recent claims.",
                    {"claim_id": S("Claim number, e.g. CLM-334455.")}, []),
        custom_tool(base_url, "check_member_eligibility",
                    "Check a patient's eligibility, plan, PCP and deductible/out-of-pocket status.",
                    PATIENT, ["member_id", "date_of_birth"]),
        custom_tool(base_url, "check_procedure_coverage",
                    "Check coverage, cost share, prior authorization and referral requirements for a CPT code for a patient.",
                    {"cpt_code": S("Five-digit CPT code."), **PATIENT}, ["cpt_code", "member_id", "date_of_birth"]),
        custom_tool(base_url, "get_prior_authorizations",
                    "List a patient's prior authorizations and status.", PATIENT, ["member_id", "date_of_birth"]),
        custom_tool(base_url, "create_service_request",
                    "Open a provider inquiry for human follow-up (reconsideration, demographic update, contract question).",
                    {"category": S("Short category."), "summary": S("One or two sentence summary.")},
                    ["category", "summary"], execution_message="Let me open that inquiry."),
        transfer_tool("transfer_to_provider_services",
                      "Warm transfer to a provider services representative."),
        end_tool(),
    ]


def post_call_analysis() -> list[dict]:
    return [
        {"type": "enum", "name": "primary_intent", "description": "The caller's main reason for contacting us.",
         "choices": ["claim_status", "benefits", "deductible_accumulators", "eligibility", "prior_authorization",
                     "id_card_or_demographics", "billing_dispute", "appeal_or_grievance", "other"]},
        {"type": "boolean", "name": "resolved_without_human", "description": "True if the caller's need was fully handled by the AI without a transfer."},
        {"type": "string", "name": "follow_up_needed", "description": "Any follow-up the plan owes the caller, in one sentence, or 'none'. No SSN or DOB."},
    ]


def build(base_url: str, persona: str) -> dict:
    prompt_file = "member_services.md" if persona == "member" else "provider_services.md"
    llm = {
        "general_prompt": (PROMPTS / prompt_file).read_text(),
        "begin_message": "{{greeting}}",
        "start_speaker": "agent",
        "general_tools": member_tools(base_url) if persona == "member" else provider_tools(base_url),
        "default_dynamic_variables": {**DEFAULT_DYNAMIC_VARIABLES, "persona": persona},
        "model_temperature": 0.2,
    }
    if os.getenv("RETELL_LLM_MODEL"):
        llm["model"] = os.environ["RETELL_LLM_MODEL"]
    title = "Member Services" if persona == "member" else "Provider Services"
    common = {
        "agent_name": f"Payer AI - {title}",
        "webhook_url": f"{base_url}/api/v1/retell/webhook",
        "data_storage_setting": "everything_except_pii",
        "pii_config": {"mode": "post_call", "categories": PII_CATEGORIES},
        "post_call_analysis_data": post_call_analysis(),
    }
    voice_agent = {
        **common,
        "voice_id": os.getenv("RETELL_VOICE_ID", "11labs-Adrian"),
        "webhook_events": ["call_started", "call_ended", "call_analyzed", "transfer_started", "transfer_bridged", "transfer_ended"],
    }
    chat_agent = {**common, "agent_name": f"Payer AI - {title} Chat"}
    return {"llm": llm, "voice_agent": voice_agent, "chat_agent": chat_agent}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True, help="Public HTTPS URL of the middleware (ngrok / cloudflared / ALB)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--member-number", help="Retell phone number (E.164) to bind to the member agent")
    ap.add_argument("--provider-number", help="Retell phone number (E.164) to bind to the provider agent")
    args = ap.parse_args()
    base_url = args.base_url.rstrip("/")

    OUT.mkdir(parents=True, exist_ok=True)
    configs = {p: build(base_url, p) for p in ("member", "provider")}
    for persona, cfg in configs.items():
        (OUT / f"{persona}_config.json").write_text(json.dumps(cfg, indent=2))
    print(f"Wrote {OUT}/member_config.json and provider_config.json")
    if args.dry_run:
        return 0

    key = os.getenv("RETELL_API_KEY")
    if not key:
        print("RETELL_API_KEY is not set", file=sys.stderr)
        return 1
    client = httpx.Client(base_url=os.getenv("RETELL_BASE_URL", "https://api.retellai.com"),
                          headers={"Authorization": f"Bearer {key}"}, timeout=30)

    def call(method: str, path: str, body: dict) -> dict:
        r = client.request(method, path, json=body)
        if r.status_code >= 400:
            print(f"{method} {path} failed: {r.status_code} {r.text}", file=sys.stderr)
            r.raise_for_status()
        return r.json() if r.content else {}

    env_lines = []
    for persona, cfg in configs.items():
        llm = call("POST", "/create-retell-llm", cfg["llm"])
        engine = {"type": "retell-llm", "llm_id": llm["llm_id"]}
        voice = call("POST", "/create-agent", {**cfg["voice_agent"], "response_engine": engine})
        chat = call("POST", "/create-chat-agent", {**cfg["chat_agent"], "response_engine": engine})
        up = persona.upper()
        env_lines += [f"RETELL_{up}_AGENT_ID={voice['agent_id']}", f"RETELL_{up}_CHAT_AGENT_ID={chat['agent_id']}"]
        number = args.member_number if persona == "member" else args.provider_number
        if number:
            call("PATCH", f"/update-phone-number/{number}", {
                "inbound_agents": [{"agent_id": voice["agent_id"], "weight": 1}],
                "inbound_webhook_url": f"{base_url}/api/v1/retell/inbound",
            })
            print(f"Bound {number} to the {persona} agent with inbound webhook")

    print("\nAdd these to .env, then restart the middleware:\n")
    print("\n".join(env_lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
