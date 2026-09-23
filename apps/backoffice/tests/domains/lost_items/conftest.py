"""분실물 라우트 테스트가 공유하는 픽스처.

라우트를 실제 PostgreSQL 위에서 돌린다. 요청마다 `database.transaction()`을
새로 열어 운영의 "요청 하나 = transaction 하나"를 그대로 재현한다.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backoffice.auth.dependencies import get_object_store, get_session
from backoffice.auth.tokens import issue_token
from backoffice.config import get_settings
from backoffice.main import create_app

from ..._auth import SIGNING_KEY


@pytest_asyncio.fixture
async def api(settings, database, object_store) -> AsyncIterator[AsyncClient]:
    application = create_app()

    async def session() -> AsyncIterator[object]:
        async with database.transaction() as opened:
            yield opened

    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_object_store] = lambda: object_store
    application.dependency_overrides[get_session] = session

    token = issue_token(signing_key=SIGNING_KEY, now=datetime.now(UTC), ttl_seconds=600)
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client
