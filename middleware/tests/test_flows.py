import json

import pytest

from app.security import sign_retell_payload, verify_retell_signature
from app.services.redaction import redact_text
from app.services.tools import normalize_dob, normalize_id



async def retell_post(client, key, path, payload, sign=True):
    raw = json.dumps(payload)
    headers = {"Content-Type": "application/json"}
    if sign:
        headers["X-Retell-Signature"] = sign_retell_payload(raw, key)
    return await client.post(path, content=raw, headers=headers)


def tool_payload(name, call_id, args, agent_id="agent_member", call_type="phone_call"):
    return {"name": name, "call": {"call_id": call_id, "agent_id": agent_id, "call_type": call_type}, "args": args}


# ---------- unit ----------

def test_signature_roundtrip(key):
    body = '{"a": 1}'
    sig = sign_retell_payload(body, key)
    assert verify_retell_signature(body, key, sig)
    assert not verify_retell_signature(body + " ", key, sig)
    assert not verify_retell_signature(body, "other", sig)
    old = sign_retell_payload(body, key, timestamp_ms=1)
    assert not verify_retell_signature(body, key, old)


def test_normalizers():
    assert normalize_dob("March 12th, 1984") == "1984-03-12"
    assert normalize_dob("03/12/1984") == "1984-03-12"
    assert normalize_dob("1984-03-12") == "1984-03-12"
    assert normalize_id("nine8 7654", "MEM") == "MEM-87654"
    assert normalize_id("mem987654", "MEM") == "MEM-987654"


def test_redaction():
    out = redact_text("SSN 123-45-6789, card 4111 1111 1111 1111, born 03/12/1984, mail a@b.com, claim CLM-112233")
    assert "123-45-6789" not in out and "4111" not in out and "03/12/1984" not in out and "a@b.com" not in out
    assert "CLM-112233" in out
    convo = redact_text("Agent: Claim received 2026-09-10 is pending.\nUser: I was born 1984-03-12.")
    assert "2026-09-10" in convo and "1984-03-12" not in convo


# ---------- Retell endpoints ----------

async def test_rejects_unsigned_and_bad_signature(client, key):
    r = await retell_post(client, key, "/api/v1/retell/tools/check_claim_status", tool_payload("x", "c1", {}), sign=False)
    assert r.status_code == 401
    raw = json.dumps(tool_payload("x", "c1", {}))
    r = await client.post("/api/v1/retell/tools/check_claim_status", content=raw,
                          headers={"X-Retell-Signature": sign_retell_payload(raw, "wrong-key")})
    assert r.status_code == 401


async def test_inbound_webhook_ani_match(client, key):
    payload = {"event": "call_inbound", "call_inbound": {
        "call_id": "call_ani", "agent_id": "agent_member", "from_number": "+15555550101", "to_number": "+15555550000"}}
    r = await retell_post(client, key, "/api/v1/retell/inbound", payload)
    assert r.status_code == 200
    dv = r.json()["call_inbound"]["dynamic_variables"]
    assert dv["ani_match"] == "true" and dv["caller_verified"] == "false" and dv["persona"] == "member"
    assert all(isinstance(v, str) for v in dv.values())
    # No PHI in the prompt of an unverified call.
    assert "Sarah" not in json.dumps(dv)

    # ANI + DOB is enough to verify.
    r = await retell_post(client, key, "/api/v1/retell/tools/verify_member_identity",
                          tool_payload("verify_member_identity", "call_ani", {"date_of_birth": "March 12, 1984"}))
    assert r.json()["result"] == "verified"


async def test_member_flow_requires_verification_and_ownership(client, key):
    cid = "call_member_1"
    r = await retell_post(client, key, "/api/v1/retell/tools/get_coverage_and_accumulators",
                          tool_payload("get_coverage_and_accumulators", cid, {}))
    assert r.json()["error"] == "not_verified"

    r = await retell_post(client, key, "/api/v1/retell/tools/verify_member_identity",
                          tool_payload("verify_member_identity", cid, {"member_id": "MEM-987654", "date_of_birth": "1984-03-13"}))
    assert r.json()["result"] == "failed"
    r = await retell_post(client, key, "/api/v1/retell/tools/verify_member_identity",
                          tool_payload("verify_member_identity", cid, {"member_id": "987654", "date_of_birth": "03/12/1984"}))
    assert r.json()["result"] == "verified"

    r = await retell_post(client, key, "/api/v1/retell/tools/get_coverage_and_accumulators",
                          tool_payload("get_coverage_and_accumulators", cid, {}))
    body = r.json()
    assert body["accumulators"]["deductible_individual"]["remaining"] == "$350.00"
    assert "$350.00 remaining" in body["summary"]

    r = await retell_post(client, key, "/api/v1/retell/tools/check_claim_status",
                          tool_payload("check_claim_status", cid, {"claim_id": "CLM-112233"}))
    assert r.json()["status"] == "DENIED" and "Duplicate" in r.json()["summary"]

    # Claim for a different member looks exactly like not-found.
    r = await retell_post(client, key, "/api/v1/retell/tools/check_claim_status",
                          tool_payload("check_claim_status", cid, {"claim_id": "CLM-334455"}))
    assert r.json()["result"] == "not_found"

    r = await retell_post(client, key, "/api/v1/retell/tools/check_procedure_coverage",
                          tool_payload("check_procedure_coverage", cid, {"cpt_code": "70553"}))
    assert r.json()["prior_auth_required"] is True


async def test_verification_lockout(client, key):
    cid = "call_lock"
    for _ in range(3):
        await retell_post(client, key, "/api/v1/retell/tools/verify_member_identity",
                          tool_payload("verify_member_identity", cid, {"member_id": "MEM-987654", "date_of_birth": "2000-01-01"}))
    r = await retell_post(client, key, "/api/v1/retell/tools/verify_member_identity",
                          tool_payload("verify_member_identity", cid, {"member_id": "MEM-987654", "date_of_birth": "1984-03-12"}))
    assert r.json()["error"] == "locked"


async def test_provider_flow(client, key):
    cid = "call_prov_1"
    p = lambda name, args: tool_payload(name, cid, args, agent_id="agent_provider")  # noqa: E731
    r = await retell_post(client, key, "/api/v1/retell/tools/verify_provider_identity",
                          p("verify_provider_identity", {"npi": "1987654320", "tax_id": "11-2233445"}))
    assert r.json()["result"] == "verified"

    r = await retell_post(client, key, "/api/v1/retell/tools/check_claim_status", p("check_claim_status", {"claim_id": "clm 334455"}))
    assert r.json()["status"] == "PENDED"
    # Another provider's claim is hidden.
    r = await retell_post(client, key, "/api/v1/retell/tools/check_claim_status", p("check_claim_status", {"claim_id": "CLM-667788"}))
    assert r.json()["result"] == "not_found"

    r = await retell_post(client, key, "/api/v1/retell/tools/check_member_eligibility",
                          p("check_member_eligibility", {"member_id": "MEM-445566", "date_of_birth": "1979-11-03"}))
    assert r.json()["error"] == "patient_not_found"
    r = await retell_post(client, key, "/api/v1/retell/tools/check_member_eligibility",
                          p("check_member_eligibility", {"member_id": "MEM-445566", "date_of_birth": "1979-11-02"}))
    assert r.json()["eligible"] is True and r.json()["primary_care_physician"]["name"] == "Dr. Alana Brooks"

    # Member-only tool on the provider line is refused.
    r = await retell_post(client, key, "/api/v1/retell/tools/get_coverage_and_accumulators", p("get_coverage_and_accumulators", {}))
    assert r.json()["error"] == "wrong_line"


async def test_webhook_stores_redacted_log_and_admin_reads_it(client, key):
    cid = "call_wh_1"
    await retell_post(client, key, "/api/v1/retell/tools/verify_member_identity",
                      tool_payload("verify_member_identity", cid, {"member_id": "MEM-987654", "date_of_birth": "1984-03-12"}))
    call = {
        "call_id": cid, "agent_id": "agent_member", "call_type": "phone_call", "direction": "inbound",
        "call_status": "ended", "start_timestamp": 1790000000000, "end_timestamp": 1790000185000,
        "disconnection_reason": "user_hangup",
        "transcript": "Agent: How can I help?\nUser: My SSN is 123-45-6789 and I was born March 12, 1984.",
        "transcript_with_tool_calls": [{"role": "tool_call_invocation", "name": "verify_member_identity", "arguments": "{}", "tool_call_id": "t1"}],
    }
    r = await retell_post(client, key, "/api/v1/retell/webhook", {"event": "call_ended", "call": call})
    assert r.status_code == 204
    analysis = {"call_summary": "Member asked about deductible.", "user_sentiment": "Positive", "call_successful": True,
                "custom_analysis_data": {"intent": "deductible"}}
    r = await retell_post(client, key, "/api/v1/retell/webhook", {"event": "call_analyzed", "call": {**call, "call_analysis": analysis}})
    assert r.status_code == 204

    h = {"Authorization": "Bearer admin-test"}
    assert (await client.get("/api/v1/admin/calls")).status_code == 401
    detail = (await client.get(f"/api/v1/admin/calls/{cid}", headers=h)).json()
    assert "123-45-6789" not in detail["transcript_redacted"] and "[REDACTED_SSN]" in detail["transcript_redacted"]
    assert detail["duration_ms"] == 185000 and detail["verified"] is True and detail["sentiment"] == "Positive"
    assert detail["tools_used"] == ["verify_member_identity"]
    # DOB passed to the tool is masked in the audit trail.
    tool_events = [e for e in detail["events"] if e["action"] == "tool.verify_member_identity"]
    assert tool_events[0]["detail"]["date_of_birth"] == "[REDACTED]"

    stats = (await client.get("/api/v1/admin/stats", headers=h)).json()
    assert stats["total_conversations"] == 1 and stats["containment_rate"] == 1.0

    # Tools refuse after the call has ended.
    r = await retell_post(client, key, "/api/v1/retell/tools/get_coverage_and_accumulators",
                          tool_payload("get_coverage_and_accumulators", cid, {}))
    assert r.json()["error"] == "conversation_closed"


async def test_agent_config_update(client):
    h = {"Authorization": "Bearer admin-test"}
    cfg = (await client.get("/api/v1/admin/agent-config", headers=h)).json()["config"]
    cfg["disclose_dollar_amounts"] = False
    cfg["business_hours"] = "24/7"
    r = await client.put("/api/v1/admin/agent-config", headers=h, json=cfg)
    assert r.status_code == 200 and r.json()["config"]["business_hours"] == "24/7"
    cfg["member_services_transfer_number"] = "not-a-number"
    assert (await client.put("/api/v1/admin/agent-config", headers=h, json=cfg)).status_code == 422


async def test_widget_simulated_chat(client):
    tok = (await client.post("/api/v1/demo/portal-token", json={"persona_key": "member-sarah"})).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    cfg = (await client.get("/api/v1/widget/config", headers=h)).json()
    assert cfg["chat_mode"] == "simulated" and cfg["voice_enabled"] is True

    start = (await client.post("/api/v1/widget/chat/start", headers=h)).json()
    assert "Sarah" in start["greeting"]
    chat_id = start["chat_id"]
    msg = (await client.post(f"/api/v1/widget/chat/{chat_id}/messages", headers=h, json={"content": "How much of my deductible is left?"})).json()
    assert "$350.00" in msg["messages"][0]["content"]
    msg = (await client.post(f"/api/v1/widget/chat/{chat_id}/messages", headers=h, json={"content": "status of claim CLM-112233"})).json()
    assert "denied" in msg["messages"][0]["content"]

    # Another portal user cannot use this chat.
    other = (await client.post("/api/v1/demo/portal-token", json={"persona_key": "member-miguel"})).json()["token"]
    r = await client.post(f"/api/v1/widget/chat/{chat_id}/messages", headers={"Authorization": f"Bearer {other}"}, json={"content": "hi"})
    assert r.status_code == 404

    assert (await client.post(f"/api/v1/widget/chat/{chat_id}/end", headers=h)).status_code == 204
    calls = (await client.get("/api/v1/admin/calls", headers={"Authorization": "Bearer admin-test"})).json()["results"]
    assert calls[0]["call_id"] == chat_id and calls[0]["tools_used"] == ["get_coverage_and_accumulators", "check_claim_status"]


async def test_widget_rejects_bad_token(client):
    r = await client.post("/api/v1/widget/chat/start", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401
