"""현재 구현된 12개 카탈로그 쓰기가 커밋 뒤 정확한 ISR 태그를 보낸다."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx
import pytest
import pytest_asyncio
from fastapi import BackgroundTasks
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from backoffice.auth.dependencies import get_object_store
from backoffice.auth.tokens import issue_token
from backoffice.config import get_settings
from backoffice.main import create_app
from backoffice.revalidation.events import RevalidationTag
from backoffice.revalidation.sender import RevalidationSender
from quinquatria_persistence.models import Category

from ..._auth import SIGNING_KEY
from ._helpers import (
    category_body,
    create_category,
    create_menu,
    create_place,
    menu_body,
    place_body,
)


class RecordingSender:
    enabled = True

    def __init__(self) -> None:
        self.tags: list[RevalidationTag] = []

    async def send_automatic(self, tag: RevalidationTag) -> None:
        self.tags.append(tag)


def _application(settings, database, object_store, sender):
    app = create_app()
    app.state.database = database
    app.state.revalidation_sender = sender
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_object_store] = lambda: object_store
    return app


def _auth_headers() -> dict[str, str]:
    token = issue_token(
        signing_key=SIGNING_KEY, now=datetime.now(UTC), ttl_seconds=18000
    )
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def webhook_api(
    settings, database, object_store
) -> AsyncIterator[tuple[httpx.AsyncClient, RecordingSender]]:
    """기존 catalog fixture와 달리 실제 get_session을 사용한다."""
    sender = RecordingSender()
    app = _application(settings, database, object_store, sender)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers=_auth_headers(),
    ) as client:
        yield client, sender


_CATEGORY_TRANSLATIONS = [
    {"language_code": "KO", "name": "주점"},
    {"language_code": "EN", "name": "Pub"},
]
_PLACE_TRANSLATIONS = [
    {"language_code": "KO", "name": "주점", "host_college": "통번역대학"},
    {"language_code": "EN", "name": "Pub", "host_college": "College"},
]
_MENU_TRANSLATIONS = [
    {"language_code": "KO", "name": "떡볶이"},
    {"language_code": "EN", "name": "Tteokbokki"},
]


@pytest.mark.parametrize("resource", ["categories", "places", "menus"])
@pytest.mark.parametrize("mutation", ["create", "patch", "delete", "translation"])
async def test_each_real_catalog_write_emits_one_correct_tag(
    webhook_api, resource, mutation
) -> None:
    client, sender = webhook_api

    if resource == "categories":
        created = (
            await create_category(client, translations=_CATEGORY_TRANSLATIONS)
            if mutation != "create"
            else None
        )
        body = category_body(translations=_CATEGORY_TRANSLATIONS)
        patch = {"code": "BOOTH"}
        tag = RevalidationTag.CATEGORIES
    elif resource == "places":
        category = await create_category(client)
        created = (
            await create_place(client, category["id"], translations=_PLACE_TRANSLATIONS)
            if mutation != "create"
            else None
        )
        body = place_body(category["id"], translations=_PLACE_TRANSLATIONS)
        patch = {"x": 128.0}
        tag = RevalidationTag.PLACES
    else:
        category = await create_category(client)
        place = await create_place(client, category["id"])
        created = (
            await create_menu(client, place["id"], translations=_MENU_TRANSLATIONS)
            if mutation != "create"
            else None
        )
        body = menu_body(place["id"], translations=_MENU_TRANSLATIONS)
        patch = {"price": 6000}
        tag = RevalidationTag.PLACES

    sender.tags.clear()
    path = f"/api/v1/{resource}"
    if mutation == "create":
        response = await client.post(path, json=body)
        expected_status = 201
    elif mutation == "patch":
        response = await client.patch(f"{path}/{created['id']}", json=patch)
        expected_status = 200
    elif mutation == "delete":
        response = await client.delete(f"{path}/{created['id']}")
        expected_status = 204
    else:
        response = await client.delete(f"{path}/{created['id']}/translations/EN")
        expected_status = 204

    assert response.status_code == expected_status, response.text
    assert sender.tags == [tag]


async def test_reads_and_rejected_writes_do_not_revalidate(webhook_api) -> None:
    client, sender = webhook_api
    category = await create_category(client)
    sender.tags.clear()

    read = await client.get(f"/api/v1/categories/{category['id']}")
    missing = await client.patch("/api/v1/categories/999", json={"code": "BOOTH"})
    rejected = await client.delete(
        f"/api/v1/categories/{category['id']}/translations/KO"
    )

    assert (read.status_code, missing.status_code, rejected.status_code) == (
        200,
        404,
        409,
    )
    assert sender.tags == []


async def test_commit_precedes_response_and_outbound_waits_until_after_body(
    settings, database, object_store
) -> None:
    trace = []
    outbound_started = asyncio.Event()
    release_outbound = asyncio.Event()
    visible_rows = []

    class TracedDatabase:
        @asynccontextmanager
        async def transaction(self):
            async with database.transaction() as session:
                yield session
            trace.append("committed")

    class GatedSender:
        enabled = True

        async def send_automatic(self, tag):
            async with database.session() as reader:
                visible_rows.append(
                    await reader.scalar(select(func.count()).select_from(Category))
                )
            trace.append("outbound_started")
            outbound_started.set()
            await release_outbound.wait()
            trace.append("outbound_done")

    app = _application(settings, TracedDatabase(), object_store, GatedSender())

    async def traced_app(scope, receive, send):
        async def traced_send(message):
            if message["type"] == "http.response.start":
                trace.append(f"response_start_{message['status']}")
            elif message["type"] == "http.response.body" and not message.get(
                "more_body", False
            ):
                trace.append("response_body")
            await send(message)

        await app(scope, receive, traced_send)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=traced_app),
        base_url="http://test",
        headers=_auth_headers(),
    ) as client:
        pending = asyncio.create_task(
            client.post("/api/v1/categories", json=category_body())
        )
        try:
            await asyncio.wait_for(outbound_started.wait(), timeout=5)
            assert trace == [
                "committed",
                "response_start_201",
                "response_body",
                "outbound_started",
            ]
            assert visible_rows == [1]
            assert not pending.done()
        finally:
            release_outbound.set()
        response = await pending

    assert response.status_code == 201
    assert trace[-1] == "outbound_done"


async def test_handler_rollback_never_sends(settings, database, object_store) -> None:
    class FailingDatabase:
        @asynccontextmanager
        async def transaction(self):
            async with database.transaction() as session:
                yield session
                raise RuntimeError("commit failed")

    sender = RecordingSender()
    app = _application(settings, FailingDatabase(), object_store, sender)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
        headers=_auth_headers(),
    ) as client:
        response = await client.post("/api/v1/categories", json=category_body())

    assert response.status_code == 500
    assert sender.tags == []
    async with database.session() as reader:
        assert await reader.scalar(select(func.count()).select_from(Category)) == 0


async def test_deferred_constraint_commit_failure_rolls_back_and_never_sends(
    settings, database, object_store
) -> None:
    commit_errors = []

    class DeferredFailureDatabase:
        @asynccontextmanager
        async def transaction(self):
            try:
                async with database.transaction() as session:
                    yield session
                    # 실제 PostgreSQL의 DEFERRABLE FK를 commit 직전에 위반한다.
                    # 임시 테이블 DDL과 Category 쓰기는 같은 transaction에 있다.
                    await session.execute(
                        text(
                            "CREATE TEMP TABLE isr_commit_parent "
                            "(id INTEGER PRIMARY KEY) ON COMMIT DROP"
                        )
                    )
                    await session.execute(
                        text(
                            "CREATE TEMP TABLE isr_commit_child "
                            "(parent_id INTEGER REFERENCES isr_commit_parent(id) "
                            "DEFERRABLE INITIALLY DEFERRED) ON COMMIT DROP"
                        )
                    )
                    await session.execute(
                        text("INSERT INTO isr_commit_child(parent_id) VALUES (1)")
                    )
            except IntegrityError as error:
                commit_errors.append(error)
                raise

    sender = RecordingSender()
    app = _application(settings, DeferredFailureDatabase(), object_store, sender)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
        headers=_auth_headers(),
    ) as client:
        response = await client.post("/api/v1/categories", json=category_body())

    assert response.status_code == 500
    assert len(commit_errors) == 1
    assert getattr(commit_errors[0].orig, "sqlstate", None) == "23503"
    assert sender.tags == []
    async with database.session() as reader:
        assert await reader.scalar(select(func.count()).select_from(Category)) == 0


async def test_background_registration_failure_preserves_committed_write(
    webhook_api, database, monkeypatch, caplog
) -> None:
    client, sender = webhook_api

    def reject_registration(self, func, tag):
        raise RuntimeError("private-registration-detail")

    monkeypatch.setattr(BackgroundTasks, "add_task", reject_registration)
    response = await client.post("/api/v1/categories", json=category_body())

    assert response.status_code == 201
    assert sender.tags == []
    assert "tag=categories kind=registration_error" in caplog.text
    assert "private-registration-detail" not in caplog.text
    async with database.session() as reader:
        assert await reader.scalar(select(func.count()).select_from(Category)) == 1


@pytest.mark.parametrize(
    ("url", "secret", "status", "expected_log"),
    [
        (None, None, 200, None),
        ("https://user@frontend.invalid", "dummy-secret", 200, "invalid_url"),
        ("https://frontend.invalid", "dummy-secret", 401, "http_status"),
    ],
)
async def test_webhook_configuration_or_receiver_failure_preserves_crud_success(
    settings, database, object_store, url, secret, status, expected_log, caplog
) -> None:
    requests = []

    def receive(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, content=b"private-response-body")

    async with httpx.AsyncClient(transport=httpx.MockTransport(receive)) as outbound:
        sender = RevalidationSender(
            outbound, url, SecretStr(secret) if secret else None
        )
        app = _application(settings, database, object_store, sender)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            response = await client.post("/api/v1/categories", json=category_body())

    assert response.status_code == 201
    if expected_log == "http_status":
        assert len(requests) == 1
    else:
        assert requests == []
    if expected_log:
        assert expected_log in caplog.text
    else:
        assert caplog.text == ""
    assert "dummy-secret" not in caplog.text
    assert "private-response-body" not in caplog.text
    async with database.session() as reader:
        assert await reader.scalar(select(func.count()).select_from(Category)) == 1
