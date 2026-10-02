"""Thin client for the Retell REST endpoints the middleware calls.
Shapes checked against retell-sdk 6.0.1 (Oct 2026)."""

import httpx

from ..config import get_settings


class RetellNotConfigured(Exception):
    pass


class RetellAPIError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"Retell API {status}: {body[:300]}")
        self.status = status


async def _request(method: str, path: str, json: dict | None = None) -> dict | None:
    s = get_settings()
    if not s.retell_api_key:
        raise RetellNotConfigured()
    async with httpx.AsyncClient(base_url=s.retell_base_url, timeout=15) as client:
        resp = await client.request(method, path, json=json, headers={"Authorization": f"Bearer {s.retell_api_key}"})
    if resp.status_code >= 400:
        raise RetellAPIError(resp.status_code, resp.text)
    return resp.json() if resp.content else None


async def create_web_call(agent_id: str, dynamic_variables: dict[str, str], metadata: dict) -> dict:
    return await _request("POST", "/v3/create-web-call", {
        "agent_id": agent_id,
        "retell_llm_dynamic_variables": dynamic_variables,
        "metadata": metadata,
    })


async def create_chat(agent_id: str, dynamic_variables: dict[str, str], metadata: dict) -> dict:
    return await _request("POST", "/create-chat", {
        "agent_id": agent_id,
        "retell_llm_dynamic_variables": dynamic_variables,
        "metadata": metadata,
    })


async def create_chat_completion(chat_id: str, content: str) -> dict:
    return await _request("POST", "/create-chat-completion", {"chat_id": chat_id, "content": content})


async def end_chat(chat_id: str) -> None:
    await _request("PATCH", f"/end-chat/{chat_id}")
