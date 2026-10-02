import hashlib
import hmac
import re
import secrets
import time
from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException, Request, status

from .config import Settings, get_settings

SIGNATURE_RE = re.compile(r"v=(\d+),d=([0-9a-f]{64})")
SIGNATURE_TOLERANCE_MS = 5 * 60 * 1000


def sign_retell_payload(raw_body: str, api_key: str, timestamp_ms: int | None = None) -> str:
    """Produce an X-Retell-Signature value. Used by tests and the local call
    simulator; Retell does the same on its side."""
    ts = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)
    digest = hmac.new(api_key.encode(), (raw_body + str(ts)).encode(), hashlib.sha256).hexdigest()
    return f"v={ts},d={digest}"


def verify_retell_signature(raw_body: str, api_key: str, signature: str, now_ms: int | None = None) -> bool:
    """Mirror of retell-sdk's verify(): header is `v=<ms timestamp>,d=<hex>`
    where d = HMAC-SHA256(api_key, raw_body + timestamp), with a 5 minute
    replay window."""
    match = SIGNATURE_RE.fullmatch(signature or "")
    if not match:
        return False
    ts, digest = int(match.group(1)), match.group(2)
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    if abs(now - ts) > SIGNATURE_TOLERANCE_MS:
        return False
    expected = hmac.new(api_key.encode(), (raw_body + str(ts)).encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, digest)


async def retell_verified_body(request: Request, settings: Settings = Depends(get_settings)) -> bytes:
    """Dependency for every endpoint Retell calls. Verifies against the raw
    bytes, never re-serialized JSON."""
    raw = await request.body()
    if not settings.retell_api_key:
        if settings.allow_unsigned_retell:
            return raw
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Retell API key not configured")
    signature = request.headers.get("x-retell-signature", "")
    if not verify_retell_signature(raw.decode("utf-8"), settings.retell_api_key, signature):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid Retell signature")
    return raw


async def require_admin(
    authorization: str = Header(default=""), settings: Settings = Depends(get_settings)
) -> str:
    """Bearer-token admin auth for the prototype. Production swaps this for
    OIDC (Okta / Ping / Entra ID) with role claims."""
    token = authorization.removeprefix("Bearer ").strip()
    if not token or not secrets.compare_digest(token, settings.admin_api_token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Admin authentication required")
    return "admin"


@dataclass
class PortalIdentity:
    persona: str  # member | provider
    subject: str
    member_id: str | None = None
    provider_npi: str | None = None
    provider_tax_id: str | None = None
    display_name: str | None = None


def mint_portal_token(identity: PortalIdentity, settings: Settings, ttl_seconds: int = 900) -> str:
    now = int(time.time())
    claims = {
        "sub": identity.subject,
        "aud": settings.portal_jwt_audience,
        "iat": now,
        "exp": now + ttl_seconds,
        "persona": identity.persona,
        "member_id": identity.member_id,
        "provider_npi": identity.provider_npi,
        "provider_tax_id": identity.provider_tax_id,
        "name": identity.display_name,
    }
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, settings.portal_jwt_secret, algorithm="HS256")


async def require_portal_identity(
    authorization: str = Header(default=""), settings: Settings = Depends(get_settings)
) -> PortalIdentity:
    """The payer's portal signs a short-lived JWT for its logged-in user and
    the widget sends it here. This is what lets the agent know who it is
    speaking to before the conversation starts."""
    token = authorization.removeprefix("Bearer ").strip()
    try:
        claims = jwt.decode(
            token, settings.portal_jwt_secret, algorithms=["HS256"], audience=settings.portal_jwt_audience
        )
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid portal session token")
    persona = claims.get("persona")
    if persona == "member" and claims.get("member_id"):
        pass
    elif persona == "provider" and claims.get("provider_npi") and claims.get("provider_tax_id"):
        pass
    else:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Portal token missing identity claims")
    return PortalIdentity(
        persona=persona,
        subject=claims["sub"],
        member_id=claims.get("member_id"),
        provider_npi=claims.get("provider_npi"),
        provider_tax_id=claims.get("provider_tax_id"),
        display_name=claims.get("name"),
    )
