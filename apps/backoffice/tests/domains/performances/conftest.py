"""공연 라우트를 실제 PostgreSQL 위에서 호출하는 픽스처."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backoffice.auth.dependencies import get_object_store, get_session
from backoffice.auth.tokens import issue_token
from backoffice.config import Settings, get_settings
from backoffice.main import create_app
from quinquatria_persistence import Database

from ..._auth import SIGNING_KEY
from ..._images import FakeObjectStore


@pytest_asyncio.fixture
async def api(
    settings: Settings, database: Database, object_store: FakeObjectStore
) -> AsyncIterator[AsyncClient]:
    """요청마다 `database.transaction()` 하나를 여는 인증된 클라이언트."""

    async def session() -> AsyncIterator[AsyncSession]:
        async with database.transaction() as instance:
            yield instance

    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_object_store] = lambda: object_store
    application.dependency_overrides[get_session] = session
    token = issue_token(
        signing_key=SIGNING_KEY, now=datetime.now(UTC), ttl_seconds=18000
    )
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client
