"""카탈로그 계약 테스트가 공유하는 픽스처.

동기 `TestClient`는 자기 이벤트 루프에서 앱을 돌려 async DB 엔진과 루프가
갈라진다. 테스트 루프 위에서 도는 `httpx.AsyncClient`로 실제 Postgres를 쓴다.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest_asyncio

from backoffice.auth.dependencies import get_object_store, get_session
from backoffice.auth.tokens import issue_token
from backoffice.config import get_settings
from backoffice.main import create_app

from ..._auth import SIGNING_KEY


@pytest_asyncio.fixture
async def api(settings, database, object_store) -> AsyncIterator[httpx.AsyncClient]:
    """유효한 Bearer 토큰을 단 클라이언트. 요청마다 transaction 하나를 연다."""
    application = create_app()

    async def session() -> AsyncIterator[object]:
        async with database.transaction() as opened:
            yield opened

    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_object_store] = lambda: object_store
    application.dependency_overrides[get_session] = session

    token = issue_token(
        signing_key=SIGNING_KEY, now=datetime.now(UTC), ttl_seconds=18000
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client
