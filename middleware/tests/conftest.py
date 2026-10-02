import os
import sys
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "middleware"))
sys.path.insert(0, str(ROOT / "mock-facets"))

TEST_KEY = "key_test_0123456789abcdef"
os.environ.update({
    "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
    "RETELL_API_KEY": TEST_KEY,
    "RETELL_MEMBER_AGENT_ID": "agent_member",
    "RETELL_PROVIDER_AGENT_ID": "agent_provider",
    "RETELL_MEMBER_CHAT_AGENT_ID": "",
    "RETELL_PROVIDER_CHAT_AGENT_ID": "",
    "ADMIN_API_TOKEN": "admin-test",
    "PORTAL_JWT_SECRET": "portal-test-secret-0123456789abcdef0123",
    "FACETS_GATEWAY_KEY": "dev-facets-gateway-key",
    "FACETS_SIMULATED_LATENCY_MS": "0",
    "DEMO_MODE": "true",
    "ALLOW_UNSIGNED_RETELL": "false",
})

from app import db as dbmod  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402
from app.services import facets as facets_mod  # noqa: E402
from mock_facets.main import app as facets_app  # noqa: E402


@pytest_asyncio.fixture
async def client():
    get_settings.cache_clear()
    dbmod.reset_engine()
    facets_mod.set_facets(
        facets_mod.FacetsClient(get_settings(), transport=httpx.ASGITransport(app=facets_app))
    )
    await dbmod.init_db()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await dbmod.get_engine().dispose()
    dbmod.reset_engine()


@pytest.fixture
def key():
    return TEST_KEY
