from collections.abc import AsyncIterator
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .config import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TenantMixin:
    payer_organization_id: Mapped[str] = mapped_column(
        String(64), index=True, default=lambda: get_settings().payer_org_id
    )


class CallSession(TenantMixin, Base):
    """Transient per-conversation state: who the caller is and whether they
    passed identity verification. Holds identifiers only, never FACETS data."""

    __tablename__ = "call_sessions"

    call_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    channel: Mapped[str] = mapped_column(String(16))  # phone | web_call | chat
    persona: Mapped[str] = mapped_column(String(16))  # member | provider
    agent_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    from_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ani_member_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    member_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_npi: Mapped[str | None] = mapped_column(String(16), nullable=True)
    provider_tax_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    verification_attempts: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CallLog(TenantMixin, Base):
    """Long-term record of a finished call or chat. Transcript is stored
    redacted only."""

    __tablename__ = "call_logs"

    call_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    channel: Mapped[str] = mapped_column(String(16))
    persona: Mapped[str | None] = mapped_column(String(16), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    direction: Mapped[str | None] = mapped_column(String(16), nullable=True)
    call_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disconnection_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    transferred: Mapped[bool] = mapped_column(Boolean, default=False)
    transcript_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(16), nullable=True)
    call_successful: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tools_used: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuditEvent(TenantMixin, Base):
    """Append-only audit trail of data access and configuration changes."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    call_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(32))
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class AgentConfig(TenantMixin, Base):
    """No-code settings payer admins can change from the dashboard."""

    __tablename__ = "agent_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    config: Mapped[dict] = mapped_column(JSON)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


TENANT_TABLES = ["call_sessions", "call_logs", "audit_events", "agent_config"]

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def reset_engine() -> None:
    global _engine, _sessionmaker
    _engine = None
    _sessionmaker = None


async def init_db() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if engine.dialect.name == "postgresql":
            # Row-level security: every query only sees rows for the org id set
            # on the transaction (see session_scope). FORCE applies it to the
            # table owner too, so the app role cannot bypass it.
            for table in TENANT_TABLES:
                await conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
                await conn.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
                await conn.execute(text(f"DROP POLICY IF EXISTS tenant_isolation ON {table}"))
                await conn.execute(
                    text(
                        f"CREATE POLICY tenant_isolation ON {table} "
                        "USING (payer_organization_id = current_setting('app.payer_org_id', true)) "
                        "WITH CHECK (payer_organization_id = current_setting('app.payer_org_id', true))"
                    )
                )


async def session_scope() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one transaction per request, scoped to the tenant."""
    get_engine()
    assert _sessionmaker is not None
    async with _sessionmaker() as session:
        async with session.begin():
            if session.bind.dialect.name == "postgresql":
                await session.execute(
                    text("SELECT set_config('app.payer_org_id', :org, true)"),
                    {"org": get_settings().payer_org_id},
                )
            yield session
