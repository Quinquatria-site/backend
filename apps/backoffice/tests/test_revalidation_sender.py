"""재검증 전송의 재시도, 제한 시간, 실패 격리와 로그 위생 계약."""

import asyncio
import json
import logging
from time import monotonic
from unittest.mock import AsyncMock

import httpx
import pytest
from httpcore._trace import Trace
from starlette.background import BackgroundTasks

from backoffice.revalidation import sender as sender_module
from backoffice.revalidation.schemas import RevalidationRequest
from backoffice.revalidation.sender import RevalidationFailed, RevalidationSender

URL = "https://frontend.invalid/revalidation/private-path?private=value"
EVENT = RevalidationRequest(target="NOTICES", resource_type="NOTICE", id=42)


@pytest.fixture(autouse=True)
def immediate_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sender_module, "RETRY_DELAY_SECONDS", 0)


def sender_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record for record in caplog.records if record.name == sender_module.__name__
    ]


@pytest.mark.parametrize("status", [200, 202, 204, 299])
async def test_success_sends_contract_and_records_safe_fields(
    status: int, caplog: pytest.LogCaptureFixture
) -> None:
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, content=b"private-response-body")

    with caplog.at_level(logging.DEBUG):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            await RevalidationSender(client, URL).send(EVENT, source="manual")

    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert json.loads(requests[0].content) == {
        "target": "NOTICES",
        "resource_type": "NOTICE",
        "id": 42,
    }
    assert "authorization" not in requests[0].headers
    assert requests[0].extensions["timeout"] == {
        "connect": 5.0,
        "read": 5.0,
        "write": 5.0,
        "pool": 5.0,
    }
    [record] = sender_records(caplog)
    assert (
        record.target,
        record.resource_type,
        record.id,
        record.source,
        record.attempt,
        record.outcome,
        record.status,
    ) == ("NOTICES", "NOTICE", 42, "manual", 1, "success", status)
    assert record.elapsed >= 0
    formatted = logging.Formatter().format(record)
    assert formatted == record.getMessage()
    for field in (
        "target=NOTICES",
        "resource_type=NOTICE",
        "id=42",
        "source=manual",
        "attempt=1",
        "outcome=success",
        f"status={status}",
        f"elapsed={record.elapsed:.6f}",
    ):
        assert field in formatted
    assert "private-response-body" not in caplog.text
    assert "private-path" not in caplog.text
    assert "private=value" not in caplog.text


async def test_optional_id_is_omitted_from_wire_payload() -> None:
    event = RevalidationRequest(target="PERFORMANCES", resource_type="PERFORMANCE")
    bodies = []

    def handle(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(202)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        await RevalidationSender(client, URL).send(event, source="automatic")

    assert bodies == [{"target": "PERFORMANCES", "resource_type": "PERFORMANCE"}]


@pytest.mark.parametrize("status", [502, 503, 504])
async def test_transient_status_retries_same_body_once(status: int) -> None:
    bodies = []

    def handle(request: httpx.Request) -> httpx.Response:
        bodies.append(request.content)
        return httpx.Response(status if len(bodies) == 1 else 204)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        await RevalidationSender(client, URL).send(EVENT, source="manual")

    assert len(bodies) == 2
    assert bodies[0] == bodies[1]


async def test_retry_waits_half_second(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sender_module, "RETRY_DELAY_SECONDS", 0.5)
    delay = AsyncMock()
    monkeypatch.setattr(sender_module.asyncio, "sleep", delay)
    statuses = iter((503, 200))

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(next(statuses))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        await RevalidationSender(client, URL).send(EVENT, source="manual")

    delay.assert_awaited_once_with(0.5)


@pytest.mark.parametrize(
    "error_type",
    [
        httpx.ConnectError,
        httpx.ReadError,
        httpx.WriteError,
        httpx.CloseError,
        httpx.RemoteProtocolError,
        httpx.ProxyError,
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.PoolTimeout,
    ],
)
async def test_communication_failure_retries_once_with_identical_body(
    error_type: type[Exception],
) -> None:
    bodies = []

    def handle(request: httpx.Request) -> httpx.Response:
        bodies.append(request.content)
        if len(bodies) == 1:
            raise error_type("private-exception-text")
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        await RevalidationSender(client, URL).send(EVENT, source="manual")

    assert len(bodies) == 2
    assert bodies[0] == bodies[1]


@pytest.mark.parametrize("status", [301, 302, 307, 400, 401, 404, 408, 422, 429, 500])
async def test_other_http_status_does_not_retry_or_follow_redirect(status: int) -> None:
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            status, headers={"Location": "https://other.invalid/private-target"}
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), follow_redirects=True
    ) as client:
        with pytest.raises(
            RevalidationFailed, match="^ISR revalidation request failed$"
        ):
            await RevalidationSender(client, URL).send(EVENT, source="manual")

    assert len(requests) == 1


@pytest.mark.parametrize(
    "error_type",
    [
        httpx.InvalidURL,
        httpx.UnsupportedProtocol,
        httpx.LocalProtocolError,
        RuntimeError,
    ],
)
async def test_request_errors_do_not_retry_and_are_sanitized(
    error_type: type[Exception], caplog: pytest.LogCaptureFixture
) -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise error_type("private-exception-text")

    with caplog.at_level(logging.DEBUG):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            with pytest.raises(RevalidationFailed) as caught:
                await RevalidationSender(client, URL).send(EVENT, source="manual")

    assert calls == 1
    assert "private-exception-text" not in str(caught.value)
    assert "private-exception-text" not in caplog.text
    assert "private-path" not in caplog.text
    assert all(record.exc_info is None for record in sender_records(caplog))


@pytest.mark.parametrize(
    "url",
    [None, "", "/relative", "ftp://frontend.invalid", "https://[", "https://user@host"],
)
async def test_missing_or_invalid_url_fails_without_network(url: str | None) -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        sender = RevalidationSender(client, url)
        with pytest.raises(RevalidationFailed):
            await sender.send(EVENT, source="manual")

    assert calls == 0


async def test_second_transient_failure_stops_and_logs_both_attempts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(RevalidationFailed):
            await RevalidationSender(client, URL).send(EVENT, source="manual")

    assert calls == 2
    assert [(r.attempt, r.outcome, r.status) for r in sender_records(caplog)] == [
        (1, "retry_http_status", 503),
        (2, "http_status", 503),
    ]


async def test_attempt_deadline_cancels_even_transport_that_ignores_httpx_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sender_module, "ATTEMPT_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(sender_module, "TOTAL_TIMEOUT_SECONDS", 0.2)
    calls = 0
    cancelled = 0

    async def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls, cancelled
        calls += 1
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            cancelled += 1
            raise
        return httpx.Response(200)

    started = monotonic()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(RevalidationFailed):
            await RevalidationSender(client, URL).send(EVENT, source="manual")

    assert calls == cancelled == 2
    assert monotonic() - started < 1


async def test_total_deadline_also_bounds_retry_delay(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(sender_module, "TOTAL_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(sender_module, "RETRY_DELAY_SECONDS", 5)
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("private-exception-text")

    started = monotonic()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(RevalidationFailed):
            await RevalidationSender(client, URL).send(EVENT, source="manual")

    assert calls == 1
    assert monotonic() - started < 1
    assert sender_records(caplog)[-1].outcome == "total_timeout"


async def test_real_httpcore_trace_exception_is_not_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        async with Trace("connect_tcp", logging.getLogger("httpcore.connection")):
            raise httpx.ConnectError("private-httpcore-exception")

    with caplog.at_level(logging.DEBUG):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            with pytest.raises(RevalidationFailed):
                await RevalidationSender(client, URL).send(EVENT, source="manual")

    assert "private-httpcore-exception" not in caplog.text
    assert "private-path" not in caplog.text
    assert len(sender_records(caplog)) == 2


async def test_suppression_does_not_hide_other_concurrent_http_requests(
    caplog: pytest.LogCaptureFixture,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            entered.set()
            await release.wait()
        return httpx.Response(200)

    with caplog.at_level(logging.DEBUG):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            task = asyncio.create_task(
                RevalidationSender(client, URL).send(EVENT, source="manual")
            )
            await entered.wait()
            try:
                await client.get("https://unrelated.invalid/visible")
            finally:
                release.set()
                await task
            await client.get("https://unrelated.invalid/after-send")

    assert "unrelated.invalid/visible" in caplog.text
    assert "unrelated.invalid/after-send" in caplog.text
    assert "private-path" not in caplog.text


async def test_automatic_failure_does_not_stop_next_background_task() -> None:
    """현재 API에 없는 복수 자동 전송의 순차 실행 계약만 검증한다."""
    ids = []

    def handle(request: httpx.Request) -> httpx.Response:
        event_id = json.loads(request.content)["id"]
        ids.append(event_id)
        return httpx.Response(400 if event_id == 42 else 200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        sender = RevalidationSender(client, URL)
        tasks = BackgroundTasks()
        tasks.add_task(sender.send_automatic, EVENT)
        tasks.add_task(sender.send_automatic, EVENT.model_copy(update={"id": 43}))
        await tasks()

    assert ids == [42, 43]


async def test_automatic_unexpected_exception_is_swallowed_without_details(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async with httpx.AsyncClient() as client:
        sender = RevalidationSender(client, URL)
        monkeypatch.setattr(
            sender,
            "send",
            AsyncMock(side_effect=RuntimeError("private-exception-text")),
        )
        await sender.send_automatic(EVENT)

    assert "private-exception-text" not in caplog.text
    [record] = sender_records(caplog)
    assert record.source == "automatic"
    assert record.outcome == "unexpected_error"
    assert record.exc_info is None


async def test_automatic_cancellation_propagates_and_resets_log_context(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError

    with caplog.at_level(logging.DEBUG):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            with pytest.raises(asyncio.CancelledError):
                await RevalidationSender(client, URL).send_automatic(EVENT)
        logging.getLogger("httpx").info("after-cancellation-visible")

    assert "after-cancellation-visible" in caplog.text
    assert not sender_records(caplog)
