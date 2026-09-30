"""공지 쓰기가 커밋 뒤 `notices` ISR 태그를 한 번 보낸다."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest
import pytest_asyncio

from backoffice.auth.tokens import issue_token
from backoffice.config import get_settings
from backoffice.main import create_app
from backoffice.revalidation.events import RevalidationTag

from ..._auth import SIGNING_KEY

_TRANSLATIONS = [
    {"language_code": "KO", "title": "안전 수칙", "content": "안내"},
    {"language_code": "EN", "title": "Safety", "content": "Notice"},
]


class RecordingSender:
    enabled = True

    def __init__(self) -> None:
        self.tags: list[RevalidationTag] = []

    async def send_automatic(self, tag: RevalidationTag) -> None:
        self.tags.append(tag)


@pytest_asyncio.fixture
async def webhook_api(
    settings, database
) -> AsyncIterator[tuple[httpx.AsyncClient, RecordingSender]]:
    """공지 `api` fixture와 달리 실제 get_session을 사용한다."""
    sender = RecordingSender()
    app = create_app()
    app.state.database = database
    app.state.revalidation_sender = sender
    app.dependency_overrides[get_settings] = lambda: settings
    token = issue_token(signing_key=SIGNING_KEY, now=datetime.now(UTC), ttl_seconds=600)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client, sender


async def _create(client: httpx.AsyncClient) -> dict:
    response = await client.post(
        "/api/v1/notices", json={"type": "GENERAL", "translations": _TRANSLATIONS}
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize("mutation", ["create", "patch", "delete", "translation"])
async def test_each_notice_write_emits_one_notices_tag(webhook_api, mutation) -> None:
    client, sender = webhook_api
    created = await _create(client) if mutation != "create" else None
    sender.tags.clear()

    if mutation == "create":
        response = await client.post(
            "/api/v1/notices", json={"type": "PERMANENT", "translations": _TRANSLATIONS}
        )
        expected_status = 201
    elif mutation == "patch":
        response = await client.patch(
            f"/api/v1/notices/{created['id']}", json={"type": "PERMANENT"}
        )
        expected_status = 200
    elif mutation == "delete":
        response = await client.delete(f"/api/v1/notices/{created['id']}")
        expected_status = 204
    else:
        response = await client.delete(
            f"/api/v1/notices/{created['id']}/translations/EN"
        )
        expected_status = 204

    assert response.status_code == expected_status, response.text
    assert sender.tags == [RevalidationTag.NOTICES]


async def test_reads_and_rejected_notice_writes_do_not_revalidate(
    webhook_api,
) -> None:
    client, sender = webhook_api
    created = await _create(client)
    sender.tags.clear()

    read = await client.get(f"/api/v1/notices/{created['id']}")
    listed = await client.get("/api/v1/notices")
    missing = await client.patch("/api/v1/notices/999", json={"type": "PERMANENT"})
    rejected = await client.delete(f"/api/v1/notices/{created['id']}/translations/KO")

    assert (
        read.status_code,
        listed.status_code,
        missing.status_code,
        rejected.status_code,
    ) == (200, 200, 404, 409)
    assert sender.tags == []
