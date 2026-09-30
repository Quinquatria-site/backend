"""공연 쓰기가 커밋 뒤 `performances` ISR 태그를 한 번 보낸다."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest
import pytest_asyncio

from backoffice.auth.dependencies import get_object_store
from backoffice.auth.tokens import issue_token
from backoffice.config import get_settings
from backoffice.main import create_app
from backoffice.revalidation.events import RevalidationTag

from ..._auth import SIGNING_KEY
from ._support import DAY_ONE, body, create

_TRANSLATIONS = [
    {"language_code": "KO", "title": "메인 공연"},
    {"language_code": "EN", "title": "Main Stage"},
]


class RecordingSender:
    enabled = True

    def __init__(self) -> None:
        self.tags: list[RevalidationTag] = []

    async def send_automatic(self, tag: RevalidationTag) -> None:
        self.tags.append(tag)


@pytest_asyncio.fixture
async def webhook_api(
    settings, database, object_store
) -> AsyncIterator[tuple[httpx.AsyncClient, RecordingSender]]:
    """공연 `api` fixture와 달리 실제 get_session을 사용한다."""
    sender = RecordingSender()
    app = create_app()
    app.state.database = database
    app.state.revalidation_sender = sender
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_object_store] = lambda: object_store
    token = issue_token(
        signing_key=SIGNING_KEY, now=datetime.now(UTC), ttl_seconds=18000
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client, sender


@pytest.mark.parametrize(
    "mutation", ["create", "patch", "live", "reorder", "delete", "translation"]
)
async def test_each_performance_write_emits_one_performances_tag(
    webhook_api, mutation
) -> None:
    client, sender = webhook_api
    created = (
        await create(client, translations=_TRANSLATIONS)
        if mutation != "create"
        else None
    )
    sender.tags.clear()

    path = "/api/v1/performances"
    if mutation == "create":
        response = await client.post(path, json=body())
        expected_status = 201
    elif mutation == "patch":
        response = await client.patch(
            f"{path}/{created['id']}", json={"type": "STUDENT"}
        )
        expected_status = 200
    elif mutation == "live":
        response = await client.put(
            f"{path}/{created['id']}/live", json={"is_live": True}
        )
        expected_status = 200
    elif mutation == "reorder":
        response = await client.put(
            f"{path}/reorder", json={"date": DAY_ONE, "order": [created["id"]]}
        )
        expected_status = 204
    elif mutation == "delete":
        response = await client.delete(f"{path}/{created['id']}")
        expected_status = 204
    else:
        response = await client.delete(f"{path}/{created['id']}/translations/EN")
        expected_status = 204

    assert response.status_code == expected_status, response.text
    assert sender.tags == [RevalidationTag.PERFORMANCES]


async def test_reads_and_rejected_performance_writes_do_not_revalidate(
    webhook_api,
) -> None:
    client, sender = webhook_api
    created = await create(client)
    sender.tags.clear()

    path = "/api/v1/performances"
    read = await client.get(f"{path}/{created['id']}")
    listed = await client.get(path)
    missing = await client.patch(f"{path}/999", json={"type": "STUDENT"})
    rejected_order = await client.put(
        f"{path}/reorder", json={"date": DAY_ONE, "order": [created["id"], 999]}
    )
    rejected_translation = await client.delete(
        f"{path}/{created['id']}/translations/KO"
    )

    assert (
        read.status_code,
        listed.status_code,
        missing.status_code,
        rejected_order.status_code,
        rejected_translation.status_code,
    ) == (200, 200, 404, 422, 409)
    assert sender.tags == []
