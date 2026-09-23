"""테스트용 라우트로 post-commit 훅을 검증한다. 실제 CRUD 연결 증거는 아니다.

순서 테스트는 실제 SessionDep와 ASGI 응답 전송을 사용한다. PostgreSQL 테스트는
별도 session에서 commit된 행을 읽고, 전송 실패에도 그 행이 남음을 확인한다.
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import APIRouter, BackgroundTasks
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backoffice.auth.dependencies import SessionDep
from backoffice.revalidation.events import (
    mark_changed,
    mark_performances_changed,
    pop_events,
)
from backoffice.revalidation.schemas import (
    ResourceType,
    RevalidationRequest,
    RevalidationTarget,
)
from backoffice.revalidation.sender import RevalidationSender
from common.app import create_api_app
from common.errors import ApiError, ErrorCode
from quinquatria_persistence import (
    Category,
    CategoryCode,
    CategoryTranslation,
    LanguageCode,
)


class RecordingDatabase:
    """commit 경계를 기록하되 실제 get_session 의존성은 바꾸지 않는다."""

    def __init__(self, trace: list[str], *, fail_commit: bool = False) -> None:
        self.trace = trace
        self.fail_commit = fail_commit

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        async with AsyncSession() as session:
            try:
                yield session
                if self.fail_commit:
                    raise RuntimeError("commit failed")
            except Exception:
                self.trace.append("rollback")
                raise
            self.trace.append("committed")


class RecordingSender:
    def __init__(self, trace: list[str]) -> None:
        self.trace = trace
        self.events: list[RevalidationRequest] = []

    async def send_automatic(self, event: RevalidationRequest) -> None:
        self.events.append(event)
        self.trace.append("outbound")


def _application(database, sender=None):
    router = APIRouter()

    @router.post("/changed")
    async def changed(session: SessionDep) -> dict[str, bool]:
        mark_changed(session, ResourceType.PLACE, 11)
        return {"ok": True}

    # 명세상 단건 CRUD와 live/reorder는 요청당 재검증 이벤트를 하나만 등록한다.
    # 이 경로는 실제 API가 아니라 다중 이벤트 실패 격리 계약을 시험하는 합성 경로다.
    @router.post("/two-changes")
    async def two_changes(session: SessionDep) -> dict[str, bool]:
        mark_changed(session, ResourceType.PLACE, 11)
        mark_changed(session, ResourceType.NOTICE, 12)
        return {"ok": True}

    @router.post("/abort")
    async def abort(session: SessionDep) -> None:
        mark_changed(session, ResourceType.PLACE, 11)
        raise ApiError(ErrorCode.VALIDATION_ERROR)

    @router.post("/unmarked")
    async def unmarked(session: SessionDep) -> dict[str, bool]:
        return {"ok": True}

    application = create_api_app(title="ISR Hook Test", router=router)
    application.state.database = database
    if sender is not None:
        application.state.revalidation_sender = sender
    return application


async def _post(application, path: str, trace: list[str]) -> httpx.Response:
    async def recording_app(scope, receive, send):
        async def recording_send(message):
            if message["type"] == "http.response.start":
                trace.append(f"response-{message['status']}")
            elif message["type"] == "http.response.body":
                trace.append("response-body")
            await send(message)

        await application(scope, receive, recording_send)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=recording_app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        return await client.post(f"/api/v1/{path}")


@pytest.mark.parametrize(
    ("resource_type", "target"),
    [
        (ResourceType.CATEGORY, RevalidationTarget.PLACES),
        (ResourceType.PLACE, RevalidationTarget.PLACES),
        (ResourceType.MENU, RevalidationTarget.PLACES),
        (ResourceType.PERFORMANCE, RevalidationTarget.PERFORMANCES),
        (ResourceType.NOTICE, RevalidationTarget.NOTICES),
        (ResourceType.LOST_ITEM, RevalidationTarget.LOST_ITEMS),
    ],
)
def test_resource_and_its_translation_use_parent_resource_id(resource_type, target):
    session = AsyncSession()
    parent_id = 71
    # 번역 DELETE 호출자도 번역 행 ID가 아니라 부모 ID를 전달해야 한다.
    mark_changed(session, resource_type, parent_id)
    mark_changed(session, resource_type, parent_id)

    assert pop_events(session) == (
        RevalidationRequest(target=target, resource_type=resource_type, id=parent_id),
    )
    assert pop_events(session) == ()


def test_dedup_preserves_different_ids_and_types_in_first_seen_order():
    # 실제 API 시나리오를 재현한 입력은 아니다. Place와 Menu를 함께 변경하는
    # batch API는 없으며, 수집기의 규약(동일 이벤트만 중복 제거하고 다른 종류·ID와
    # 최초 등록 순서는 보존)을 검증하기 위해 구성한 입력이다.
    session = AsyncSession()
    mark_changed(session, ResourceType.PLACE, 7)
    mark_changed(session, ResourceType.MENU, 7)
    mark_changed(session, ResourceType.PLACE, 8)
    mark_changed(session, ResourceType.PLACE, 7)

    assert [(event.resource_type, event.id) for event in pop_events(session)] == [
        (ResourceType.PLACE, 7),
        (ResourceType.MENU, 7),
        (ResourceType.PLACE, 8),
    ]


@pytest.mark.parametrize("resource_id", [None, 0, -1, True, "1"])
def test_single_resource_mark_requires_a_strict_positive_id(resource_id):
    session = AsyncSession()

    with pytest.raises(ValueError):
        mark_changed(session, ResourceType.PLACE, resource_id)

    assert pop_events(session) == ()


def test_live_and_reorder_mark_one_event_without_an_individual_id():
    session = AsyncSession()
    mark_performances_changed(session)
    mark_performances_changed(session)

    assert pop_events(session) == (
        RevalidationRequest(
            target=RevalidationTarget.PERFORMANCES,
            resource_type=ResourceType.PERFORMANCE,
        ),
    )


async def test_commit_precedes_response_and_outbound_follows_response():
    trace = []
    sender = RecordingSender(trace)
    app = _application(RecordingDatabase(trace), sender)

    response = await _post(app, "changed", trace)

    assert response.status_code == 200
    assert trace == ["committed", "response-200", "response-body", "outbound"]
    assert sender.events[0].id == 11


@pytest.mark.parametrize(
    ("path", "fail_commit", "status"),
    [("abort", False, 422), ("changed", True, 500)],
)
async def test_rollback_or_failed_commit_never_sends(path, fail_commit, status):
    trace = []
    sender = RecordingSender(trace)
    app = _application(RecordingDatabase(trace, fail_commit=fail_commit), sender)

    response = await _post(app, path, trace)

    assert response.status_code == status
    assert trace == ["rollback", f"response-{status}", "response-body"]
    assert sender.events == []


async def test_unmarked_transaction_does_not_require_a_sender():
    trace = []
    app = _application(RecordingDatabase(trace))

    response = await _post(app, "unmarked", trace)

    assert response.status_code == 200
    assert trace == ["committed", "response-200", "response-body"]


async def test_missing_sender_is_logged_without_changing_committed_response(caplog):
    trace = []
    app = _application(RecordingDatabase(trace))

    response = await _post(app, "changed", trace)

    assert response.status_code == 200
    assert trace[0] == "committed"
    assert "registration failed target=PLACES resource_type=PLACE id=11" in caplog.text


async def test_registration_failure_does_not_skip_the_next_event(monkeypatch, caplog):
    """현재 API에 없는 다중 이벤트의 등록 실패 격리만 검증한다."""
    trace = []
    sender = RecordingSender(trace)
    app = _application(RecordingDatabase(trace), sender)
    original_add_task = BackgroundTasks.add_task

    def add_task(self, func, event):
        if event.id == 11:
            raise RuntimeError("private-registration-detail")
        original_add_task(self, func, event)

    monkeypatch.setattr(BackgroundTasks, "add_task", add_task)

    response = await _post(app, "two-changes", trace)

    assert response.status_code == 200
    assert [event.id for event in sender.events] == [12]
    assert "registration failed" in caplog.text
    assert "private-registration-detail" not in caplog.text


async def test_failed_automatic_http_send_does_not_skip_the_next_event():
    """현재 API에 없는 다중 이벤트의 전송 실패 격리만 검증한다."""
    payloads = []

    def receiver(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        payloads.append(body)
        return httpx.Response(400 if body["id"] == 11 else 200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(receiver)) as client:
        sender = RevalidationSender(client, "https://frontend.invalid/revalidate")
        trace = []
        app = _application(RecordingDatabase(trace), sender)

        response = await _post(app, "two-changes", trace)

    assert response.status_code == 200
    assert [body["id"] for body in payloads] == [11, 12]


async def test_postgresql_write_is_visible_before_send_and_survives_send_failure(
    database,
):
    """실제 PostgreSQL commit과 별도 reader를 사용하는 합성 라우트 검증."""
    visible_codes = []
    payloads = []

    async def receiver(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        async with database.session() as reader:
            visible_codes.extend((await reader.scalars(select(Category.code))).all())
        return httpx.Response(400)

    async with httpx.AsyncClient(transport=httpx.MockTransport(receiver)) as client:
        app = _application(
            database, RevalidationSender(client, "https://frontend.invalid/revalidate")
        )

        @app.post("/api/v1/persist", status_code=201)
        async def persist(session: SessionDep) -> dict[str, int]:
            category = Category(code=CategoryCode.PUB)
            session.add(category)
            await session.flush()
            mark_changed(session, ResourceType.CATEGORY, category.id)
            return {"id": category.id}

        response = await _post(app, "persist", [])

    assert response.status_code == 201
    assert visible_codes == [CategoryCode.PUB]
    assert payloads == [
        {"target": "PLACES", "resource_type": "CATEGORY", "id": response.json()["id"]}
    ]
    async with database.session() as reader:
        assert await reader.scalar(select(func.count()).select_from(Category)) == 1


async def test_postgresql_commit_failure_rolls_back_and_never_sends(database):
    trace = []
    sender = RecordingSender(trace)
    app = _application(database, sender)

    @app.post("/api/v1/invalid-write")
    async def invalid_write(session: SessionDep) -> dict[str, int]:
        category = Category(code=CategoryCode.PUB)
        session.add(category)
        await session.flush()
        mark_changed(session, ResourceType.CATEGORY, category.id)
        # 부모 flush는 성공했고, 필수 name의 NULL은 context 종료 commit에서 실패한다.
        session.add(
            CategoryTranslation(
                category_id=category.id, language_code=LanguageCode.KO, name=None
            )
        )
        return {"id": category.id}

    response = await _post(app, "invalid-write", trace)

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_SERVER_ERROR"
    assert sender.events == []
    async with database.session() as reader:
        assert await reader.scalar(select(func.count()).select_from(Category)) == 0
