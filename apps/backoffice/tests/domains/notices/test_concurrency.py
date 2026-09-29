"""같은 공지를 동시에 PATCH하면 `FOR UPDATE`가 두 요청을 차례로 처리한다.

첫 요청을 commit 직전에 붙잡아 둔 채 두 번째 요청을 보내, 두 번째가 실제로
행 잠금을 기다리는지 `pg_stat_activity`로 확인한 뒤 첫 요청을 놓아준다.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text

from backoffice.auth.dependencies import get_session
from backoffice.auth.tokens import issue_token
from backoffice.config import get_settings
from backoffice.main import create_app
from quinquatria_persistence import NoticeTranslation

from ..._auth import SIGNING_KEY
from .test_create import EN, KO
from .test_read import _create

WAIT_LIMIT = 5.0
"""두 번째 요청이 잠금 대기에 들어가기를 기다리는 한도."""


async def _row_lock_waiters(database) -> int:
    """unique 인덱스 대기와 구분하려고 `FOR UPDATE` 조회의 대기만 센다."""
    async with database.session() as session:
        return await session.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity"
                " WHERE datname = current_database() AND wait_event_type = 'Lock'"
                " AND query ILIKE '%FOR UPDATE%'"
            )
        )


async def test_concurrent_patches_adding_one_language_are_serialized(
    settings, database
) -> None:
    holding = asyncio.Event()
    release = asyncio.Event()
    opened = 0

    async def plain() -> AsyncIterator:
        async with database.transaction() as transaction:
            yield transaction

    async def session() -> AsyncIterator:
        """첫 요청만 라우트가 끝난 뒤 commit 전에 멈춘다."""
        nonlocal opened
        opened += 1
        first = opened == 1
        async with database.transaction() as transaction:
            yield transaction
            if first:
                holding.set()
                await release.wait()

    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_session] = plain
    token = issue_token(signing_key=SIGNING_KEY, now=datetime.now(UTC), ttl_seconds=600)
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as api:
        created = await _create(api, "GENERAL", KO)
        application.dependency_overrides[get_session] = session
        url = f"/api/v1/notices/{created['id']}"

        first = asyncio.create_task(api.patch(url, json={"translations": [EN]}))
        await asyncio.wait_for(holding.wait(), timeout=WAIT_LIMIT)
        second = asyncio.create_task(
            api.patch(url, json={"translations": [{**EN, "title": "Later"}]})
        )
        try:
            async with asyncio.timeout(WAIT_LIMIT):
                while await _row_lock_waiters(database) == 0:
                    await asyncio.sleep(0.05)
            assert not second.done()
        finally:
            release.set()
        responses = await asyncio.gather(first, second)

    assert [response.status_code for response in responses] == [200, 200]
    async with database.session() as session_:
        count = await session_.scalar(
            select(func.count())
            .select_from(NoticeTranslation)
            .where(NoticeTranslation.language_code == "EN")
        )
    assert count == 1
    final = responses[1].json()["translations"]
    assert [(t["language_code"], t["title"]) for t in final] == [
        ("EN", "Later"),
        ("KO", KO["title"]),
    ]
