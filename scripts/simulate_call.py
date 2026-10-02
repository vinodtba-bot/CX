#!/usr/bin/env python3
"""Replay what Retell sends during a phone call, signed exactly as Retell
signs it, against a running middleware. Lets you exercise the inbound
webhook, tools and post-call webhook (and fill the dashboard) with no Retell
account or phone.

    python scripts/simulate_call.py                     # all scenarios
    python scripts/simulate_call.py --scenario provider
    MIDDLEWARE_URL=http://localhost:8000 RETELL_API_KEY=... python scripts/simulate_call.py

Uses RETELL_API_KEY as the signing key, so it must match the middleware's.
"""

import argparse
import hashlib
import hmac
import json
import os
import random
import sys
import time
import uuid

import httpx

URL = os.getenv("MIDDLEWARE_URL", "http://localhost:8000")
KEY = os.getenv("RETELL_API_KEY", "")
MEMBER_AGENT = os.getenv("RETELL_MEMBER_AGENT_ID", "agent_member_local")
PROVIDER_AGENT = os.getenv("RETELL_PROVIDER_AGENT_ID", "agent_provider_local")


def post(client: httpx.Client, path: str, payload: dict) -> httpx.Response:
    raw = json.dumps(payload)
    headers = {"Content-Type": "application/json"}
    if KEY:
        ts = int(time.time() * 1000)
        digest = hmac.new(KEY.encode(), (raw + str(ts)).encode(), hashlib.sha256).hexdigest()
        headers["X-Retell-Signature"] = f"v={ts},d={digest}"
    r = client.post(path, content=raw, headers=headers)
    r.raise_for_status()
    return r


class Call:
    def __init__(self, client: httpx.Client, agent_id: str, from_number: str):
        self.client, self.agent_id, self.from_number = client, agent_id, from_number
        self.call_id = f"call_sim_{uuid.uuid4().hex[:12]}"
        self.lines: list[str] = []
        self.tools: list[dict] = []
        self.start = int(time.time() * 1000) - random.randint(120, 400) * 1000

    def inbound(self) -> dict:
        r = post(self.client, "/api/v1/retell/inbound", {
            "event": "call_inbound", "event_timestamp": int(time.time() * 1000),
            "call_inbound": {"call_id": self.call_id, "agent_id": self.agent_id,
                             "from_number": self.from_number, "to_number": "+15555550000"}})
        dv = r.json()["call_inbound"]["dynamic_variables"]
        self.say("Agent", dv["greeting"])
        return dv

    def say(self, who: str, text: str) -> None:
        self.lines.append(f"{who}: {text}")
        print(f"  {who:5}: {text}")

    def tool(self, name: str, args: dict) -> dict:
        body = post(self.client, f"/api/v1/retell/tools/{name}", {
            "name": name, "args": args,
            "call": {"call_id": self.call_id, "agent_id": self.agent_id, "call_type": "phone_call"}}).json()
        self.tools.append({"role": "tool_call_invocation", "name": name, "arguments": json.dumps(args), "tool_call_id": uuid.uuid4().hex[:8]})
        print(f"  tool : {name}({args}) -> {body.get('result') or body.get('error') or 'ok'}")
        self.say("Agent", body.get("summary", ""))
        return body

    def end(self, reason: str, summary: str, sentiment: str, successful: bool, intent: str, transferred: bool = False) -> None:
        call = {
            "call_id": self.call_id, "call_type": "phone_call", "agent_id": self.agent_id, "direction": "inbound",
            "from_number": self.from_number, "to_number": "+15555550000", "call_status": "ended",
            "start_timestamp": self.start, "end_timestamp": int(time.time() * 1000),
            "disconnection_reason": "call_transfer" if transferred else reason,
            "transcript": "\n".join(self.lines), "transcript_with_tool_calls": self.tools,
            "metadata": {},
        }
        if transferred:
            post(self.client, "/api/v1/retell/webhook", {"event": "transfer_started", "call": call})
        post(self.client, "/api/v1/retell/webhook", {"event": "call_ended", "call": call})
        post(self.client, "/api/v1/retell/webhook", {"event": "call_analyzed", "call": {**call, "call_analysis": {
            "call_summary": summary, "user_sentiment": sentiment, "call_successful": successful,
            "custom_analysis_data": {"primary_intent": intent, "resolved_without_human": not transferred, "follow_up_needed": "none"}}}})
        print(f"  -> logged {self.call_id}\n")


def member_ani(client):
    print("Member calling from a number on file (Sarah, deductible + denied claim)")
    c = Call(client, MEMBER_AGENT, "+15555550101")
    c.inbound()
    c.say("User", "Hi, I want to know how much is left on my deductible.")
    c.say("Agent", "I see you're calling from a number on file. To verify, what's your date of birth?")
    c.say("User", "March 12th, 1984.")
    c.tool("verify_member_identity", {"date_of_birth": "1984-03-12"})
    c.tool("get_coverage_and_accumulators", {})
    c.say("User", "Also, why was claim CLM-112233 denied? My SSN is 123-45-6789 if you need it.")
    c.say("Agent", "I don't need your Social Security number. Let me check that claim.")
    c.tool("check_claim_status", {"claim_id": "CLM-112233"})
    c.end("user_hangup", "Member checked deductible and a denied duplicate claim; agent explained the original claim was paid.",
          "Positive", True, "deductible_accumulators")


def member_failed_verification(client):
    print("Unknown caller fails verification and is transferred")
    c = Call(client, MEMBER_AGENT, "+15555559999")
    c.inbound()
    c.say("User", "I need to check my claims.")
    for dob in ("1990-01-01", "1991-01-01", "1992-01-01"):
        c.tool("verify_member_identity", {"member_id": "MEM-987654", "date_of_birth": dob})
    c.tool("get_coverage_and_accumulators", {})
    c.end("call_transfer", "Caller could not be verified after three attempts and was transferred to member services.",
          "Negative", False, "claim_status", transferred=True)


def member_benefits(client):
    print("HMO member asks about an MRI and prior auth")
    c = Call(client, MEMBER_AGENT, "+15555550102")
    c.inbound()
    c.say("User", "My doctor wants me to get a brain MRI. Is it covered?")
    c.tool("verify_member_identity", {"date_of_birth": "1979-11-02"})
    c.tool("check_procedure_coverage", {"cpt_code": "70553"})
    c.tool("get_prior_authorizations", {})
    c.end("user_hangup", "HMO member confirmed MRI coverage with $250 copay; prior auth already approved.",
          "Positive", True, "benefits")


def provider(client):
    print("Imaging center checks a pended claim and patient eligibility")
    c = Call(client, PROVIDER_AGENT, "+15555550191")
    c.inbound()
    c.say("User", "Hi, calling from Lakeshore Imaging about a claim.")
    c.tool("verify_provider_identity", {"npi": "1987654320", "tax_id": "112233445"})
    c.tool("check_claim_status", {"claim_id": "CLM-334455"})
    c.tool("check_member_eligibility", {"member_id": "MEM-445566", "date_of_birth": "1979-11-02"})
    c.tool("check_procedure_coverage", {"cpt_code": "73721", "member_id": "MEM-445566", "date_of_birth": "1979-11-02"})
    c.end("agent_hangup", "Provider checked a pended MRI claim needing records, patient eligibility, and prior auth requirement for knee MRI.",
          "Neutral", True, "claim_status")


SCENARIOS = {"member": member_ani, "failed": member_failed_verification, "benefits": member_benefits, "provider": provider}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", choices=[*SCENARIOS, "all"], default="all")
    args = ap.parse_args()
    if not KEY:
        print("RETELL_API_KEY not set: sending unsigned requests (works only with ALLOW_UNSIGNED_RETELL=true)\n")
    with httpx.Client(base_url=URL, timeout=20) as client:
        for name, fn in SCENARIOS.items():
            if args.scenario in (name, "all"):
                fn(client)
    return 0


if __name__ == "__main__":
    sys.exit(main())
