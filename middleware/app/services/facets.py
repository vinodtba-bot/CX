"""Client for the payer's FACETS gateway.

This is the only module that knows FACETS paths and field names. Swapping in
HealthEdge HRWS, a FHIR Patient Access API or an X12 270/276 clearinghouse
means adding a sibling adapter with the same methods.
"""

from typing import Any

import httpx

from ..config import Settings, get_settings


class FacetsError(Exception):
    pass


class FacetsNotFound(FacetsError):
    pass


class FacetsUnavailable(FacetsError):
    pass


class FacetsClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        kwargs: dict[str, Any] = {
            "base_url": settings.facets_base_url,
            "timeout": settings.facets_timeout_seconds,
            "headers": {"X-Gateway-Key": settings.facets_gateway_key},
        }
        if settings.facets_client_cert and settings.facets_client_key:
            # mTLS to the payer's API gateway over the private link.
            kwargs["cert"] = (settings.facets_client_cert, settings.facets_client_key)
        if settings.facets_ca_bundle:
            kwargs["verify"] = settings.facets_ca_bundle
        if transport is not None:
            kwargs["transport"] = transport
        self._client = httpx.AsyncClient(**kwargs)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict | None = None) -> dict:
        try:
            resp = await self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise FacetsUnavailable(str(exc)) from exc
        if resp.status_code == 404:
            raise FacetsNotFound(path)
        if resp.status_code >= 400:
            raise FacetsUnavailable(f"{resp.status_code} from FACETS gateway")
        return resp.json()

    async def _post(self, path: str, body: dict) -> dict:
        try:
            resp = await self._client.post(path, json=body)
        except httpx.HTTPError as exc:
            raise FacetsUnavailable(str(exc)) from exc
        if resp.status_code >= 400:
            raise FacetsUnavailable(f"{resp.status_code} from FACETS gateway")
        return resp.json()

    async def find_members_by_phone(self, phone: str) -> list[dict]:
        return (await self._get("/v1/members/search", {"phone": phone}))["results"]

    async def get_member(self, member_id: str) -> dict:
        return await self._get(f"/v1/members/{member_id}")

    async def get_eligibility(self, member_id: str) -> dict:
        return await self._get(f"/v1/members/{member_id}/eligibility")

    async def get_accumulators(self, member_id: str) -> dict:
        return await self._get(f"/v1/members/{member_id}/accumulators")

    async def list_member_claims(self, member_id: str) -> list[dict]:
        return (await self._get(f"/v1/members/{member_id}/claims"))["results"]

    async def list_prior_auths(self, member_id: str) -> list[dict]:
        return (await self._get(f"/v1/members/{member_id}/prior-authorizations"))["results"]

    async def get_claim_status(self, claim_id: str) -> dict:
        return await self._get(f"/v1/claims/{claim_id}/status")

    async def get_provider(self, npi: str) -> dict:
        return await self._get(f"/v1/providers/{npi}")

    async def list_provider_claims(self, npi: str) -> list[dict]:
        return (await self._get(f"/v1/providers/{npi}/claims"))["results"]

    async def get_procedure_benefit(self, member_id: str, cpt_code: str, provider_npi: str | None = None) -> dict:
        params = {"providerNpi": provider_npi} if provider_npi else None
        return await self._get(f"/v1/benefits/{member_id}/procedures/{cpt_code}", params)

    async def create_inquiry(self, body: dict) -> dict:
        return await self._post("/v1/inquiries", body)


_client: FacetsClient | None = None


def get_facets() -> FacetsClient:
    global _client
    if _client is None:
        _client = FacetsClient(get_settings())
    return _client


def set_facets(client: FacetsClient | None) -> None:
    global _client
    _client = client
