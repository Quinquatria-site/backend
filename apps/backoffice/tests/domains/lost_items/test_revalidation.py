"""분실물 쓰기가 커밋 뒤 `lost-items` ISR 태그를 한 번 보낸다."""

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
from ._support import URL, body, ko

_TRANSLATIONS = [ko(), {"language_code": "EN", "title": "Wallet"}]


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
    """분실물 `api` fixture와 달리 실제 get_session을 사용한다."""
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


async def _create(client: httpx.AsyncClient) -> dict:
    response = await client.post(URL, json=body(translations=_TRANSLATIONS))
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize("mutation", ["create", "patch", "delete", "translation"])
async def test_each_lost_item_write_emits_one_lost_items_tag(
    webhook_api, mutation
) -> None:
    client, sender = webhook_api
    created = await _create(client) if mutation != "create" else None
    sender.tags.clear()

    if mutation == "create":
        response = await client.post(URL, json=body())
        expected_status = 201
    elif mutation == "patch":
        # 반환 처리도 사용자 화면에 보이므로 재검증 대상이다 (명세 §7.1).
        response = await client.patch(
            f"{URL}/{created['id']}", json={"is_returned": True}
        )
        expected_status = 200
    elif mutation == "delete":
        response = await client.delete(f"{URL}/{created['id']}")
        expected_status = 204
    else:
        response = await client.delete(f"{URL}/{created['id']}/translations/EN")
        expected_status = 204

    assert response.status_code == expected_status, response.text
    assert sender.tags == [RevalidationTag.LOST_ITEMS]


async def test_reads_and_rejected_lost_item_writes_do_not_revalidate(
    webhook_api,
) -> None:
    client, sender = webhook_api
    created = await _create(client)
    sender.tags.clear()

    read = await client.get(f"{URL}/{created['id']}")
    listed = await client.get(URL)
    missing = await client.patch(f"{URL}/999", json={"is_returned": True})
    rejected = await client.delete(f"{URL}/{created['id']}/translations/KO")

    assert (
        read.status_code,
        listed.status_code,
        missing.status_code,
        rejected.status_code,
    ) == (200, 200, 404, 409)
    assert sender.tags == []
