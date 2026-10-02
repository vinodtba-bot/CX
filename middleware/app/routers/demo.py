"""Demo-only helpers. In production the payer's portal signs the identity
token itself; this router stands in for that portal and is disabled unless
DEMO_MODE=true."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..config import Settings, get_settings
from ..security import PortalIdentity, mint_portal_token

router = APIRouter(prefix="/api/v1/demo", tags=["demo"])

# Synthetic personas matching mock-facets sample data.
PERSONAS = {
    "member-sarah": PortalIdentity(persona="member", subject="portal-user-1001", member_id="MEM-987654", display_name="Sarah Jenkins"),
    "member-miguel": PortalIdentity(persona="member", subject="portal-user-1002", member_id="MEM-445566", display_name="Miguel Alvarez"),
    "provider-riverside": PortalIdentity(persona="provider", subject="prov-portal-2001", provider_npi="1234567893",
                                         provider_tax_id="998877665", display_name="Riverside Family Medicine"),
    "provider-lakeshore": PortalIdentity(persona="provider", subject="prov-portal-2002", provider_npi="1987654320",
                                         provider_tax_id="112233445", display_name="Lakeshore Imaging Center"),
}


def require_demo(settings: Settings = Depends(get_settings)) -> Settings:
    if not settings.demo_mode:
        raise HTTPException(404)
    return settings


@router.get("/personas")
async def personas(_: Settings = Depends(require_demo)):
    return {"results": [{"key": k, "persona": p.persona, "name": p.display_name} for k, p in PERSONAS.items()]}


class TokenIn(BaseModel):
    persona_key: str


@router.post("/portal-token")
async def portal_token(body: TokenIn, settings: Settings = Depends(require_demo)):
    ident = PERSONAS.get(body.persona_key)
    if ident is None:
        raise HTTPException(404, "Unknown persona")
    return {"token": mint_portal_token(ident, settings), "persona": ident.persona, "name": ident.display_name}
