"""공지 라우트 테스트가 공유하는 실제 DB 기반 HTTP 클라이언트."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backoffice.auth.dependencies import get_session
from backoffice.auth.tokens import issue_token
from backoffice.config import Settings, get_settings
from backoffice.main import create_app
from quinquatria_persistence import Database

from ..._auth import SIGNING_KEY


@pytest_asyncio.fixture
async def api(settings: Settings, database: Database) -> AsyncIterator[AsyncClient]:
    """요청마다 `database.transaction()` 하나를 여는 인증된 클라이언트.

    앱 예외를 다시 던지지 않아 500 응답과 rollback 결과를 함께 검증할 수 있다.
    """

    async def session() -> AsyncIterator:
        async with database.transaction() as opened:
            yield opened

    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_session] = session
    token = issue_token(signing_key=SIGNING_KEY, now=datetime.now(UTC), ttl_seconds=600)
    async with AsyncClient(
        transport=ASGITransport(app=application, raise_app_exceptions=False),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client
