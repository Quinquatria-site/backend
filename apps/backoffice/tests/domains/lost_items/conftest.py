"""분실물 라우트 테스트가 공유하는 픽스처.

라우트를 실제 PostgreSQL 위에서 돌린다. 요청마다 `database.transaction()`을
새로 열어 운영의 "요청 하나 = transaction 하나"를 그대로 재현한다.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backoffice.auth.dependencies import get_object_store, get_session
from backoffice.auth.tokens import issue_token
from backoffice.config import get_settings
from backoffice.main import create_app

from ..._auth import SIGNING_KEY


class CommitGate:
    """무장한 뒤 처음 성공한 요청 하나를 commit 직전에 세운다.

    경합 테스트가 "앞선 요청은 잠금을 쥔 채 아직 commit하지 않았다"는
    상태를 sleep 없이 만들기 위한 훅이다.
    """

    def __init__(self) -> None:
        self._armed = False
        self.reached = asyncio.Event()
        self._released = asyncio.Event()

    async def hold(self, request: object) -> asyncio.Task:
        """`request`를 출발시키고 commit 직전에 멈출 때까지 기다린다."""
        self._armed = True
        self.reached.clear()
        self._released.clear()
        task = asyncio.ensure_future(request)
        await asyncio.wait_for(self.reached.wait(), timeout=5)
        return task

    def release(self) -> None:
        self._released.set()

    async def __call__(self) -> None:
        if not self._armed:
            return
        self._armed = False
        self.reached.set()
        await self._released.wait()


@pytest_asyncio.fixture
async def commit_gate() -> CommitGate:
    return CommitGate()


@pytest_asyncio.fixture
async def api(
    settings, database, object_store, commit_gate
) -> AsyncIterator[AsyncClient]:
    application = create_app()

    async def session() -> AsyncIterator[object]:
        async with database.transaction() as opened:
            yield opened
            # 라우트가 예외 없이 끝난 뒤, commit 전이다.
            await commit_gate()

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
