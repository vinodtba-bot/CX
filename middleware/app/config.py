from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables (see .env.example)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Tenant. In the single-tenant VPC model each deployment serves one payer,
    # but every row still carries the org id so the schema is ready for RLS.
    payer_org_id: str = "acme-health"
    payer_display_name: str = "Acme Health Plan"

    database_url: str = "postgresql+asyncpg://payer:payer@localhost:5432/payer_ai"

    # Retell. The API key both authenticates our outbound calls and verifies
    # the X-Retell-Signature on everything Retell sends us.
    retell_api_key: str = ""
    retell_base_url: str = "https://api.retellai.com"
    retell_member_agent_id: str = ""
    retell_provider_agent_id: str = ""
    retell_member_chat_agent_id: str = ""
    retell_provider_chat_agent_id: str = ""

    # Local development only: accept unsigned Retell requests when no API key
    # is configured. Must be false anywhere real data flows.
    allow_unsigned_retell: bool = False

    # Payer core (FACETS via the payer's API gateway).
    facets_base_url: str = "http://localhost:8001"
    facets_gateway_key: str = "dev-facets-gateway-key"
    facets_timeout_seconds: float = 3.0
    facets_client_cert: str = ""  # path to mTLS client cert (production)
    facets_client_key: str = ""
    facets_ca_bundle: str = ""

    # Auth for the admin dashboard (replace with Okta/Ping SSO for production).
    admin_api_token: str = "change-me-admin-token"

    # Shared secret the payer portal uses to sign the member/provider identity
    # token it hands the web widget (HS256 JWT).
    portal_jwt_secret: str = "change-me-portal-secret"
    portal_jwt_audience: str = "payer-ai-widget"

    # Enables /api/v1/demo/* (mints portal tokens for the sample personas) and
    # the simulated chat used when no Retell chat agent is configured.
    demo_mode: bool = True

    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    max_verification_attempts: int = 3

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
