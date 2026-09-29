"""프론트 ISR 웹훅의 본문, 인증, 한도, 실패 격리와 로그 위생."""

import asyncio
import json
import logging
from time import monotonic

import httpx
import pytest
from pydantic import SecretStr

from backoffice.revalidation import sender as sender_module
from backoffice.revalidation.events import RevalidationTag
from backoffice.revalidation.sender import RevalidationSender

SITE_URL = "https://frontend.invalid"
SECRET = "dummy-revalidation-secret"


@pytest.mark.parametrize("tag", list(RevalidationTag))
async def test_exact_request_contract_and_no_success_logs(tag, caplog) -> None:
    requests = []

    def receive(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        # HTTPX/httpcore가 기록한 요청 URL이나 통신 내용도 남지 않아야 한다.
        logging.getLogger("httpcore.connection").debug("private transport detail")
        return httpx.Response(200, json={"revalidated": tag.value})

    async with httpx.AsyncClient(transport=httpx.MockTransport(receive)) as client:
        sender = RevalidationSender(client, SITE_URL + "/", SecretStr(SECRET))
        with caplog.at_level(logging.DEBUG):
            await sender.send_automatic(tag)

    [request] = requests
    assert request.method == "POST"
    assert str(request.url) == f"{SITE_URL}/api/revalidate"
    assert request.headers["Authorization"] == f"Bearer {SECRET}"
    assert request.headers["Content-Type"] == "application/json"
    assert json.loads(request.content) == {"tag": tag.value}
    assert list(json.loads(request.content)) == ["tag"]
    assert SITE_URL not in caplog.text
    assert SECRET not in caplog.text
    assert "private transport detail" not in caplog.text
    assert not [
        record for record in caplog.records if record.name == sender_module.__name__
    ]


@pytest.mark.parametrize(
    ("url", "secret"),
    [
        (None, SecretStr(SECRET)),
        ("", SecretStr(SECRET)),
        ("   ", SecretStr(SECRET)),
        (SITE_URL, None),
        (SITE_URL, SecretStr("")),
        (SITE_URL, SecretStr("   ")),
    ],
)
async def test_missing_or_blank_configuration_skips_without_network_or_logs(
    url, secret, caplog
) -> None:
    requests = []

    def receive(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(receive)) as client:
        sender = RevalidationSender(client, url, secret)
        assert not sender.enabled
        with caplog.at_level(logging.DEBUG):
            await sender.send_automatic(RevalidationTag.CATEGORIES)

    assert requests == []
    assert caplog.text == ""


@pytest.mark.parametrize(
    "url",
    [
        "/relative",
        "ftp://frontend.invalid",
        "https://[",
        "https://user@frontend.invalid",
        "https://frontend.invalid/path",
        "https://frontend.invalid?x=1",
        "https://frontend.invalid?",
        "https://frontend.invalid#fragment",
        "https://frontend.invalid#",
        "https://frontend.invalid:bad",
        "https://frontend.invalid/ path",
    ],
)
async def test_malformed_url_is_safe_logged_failure_without_network(
    url, caplog
) -> None:
    requests = []

    def receive(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(receive)) as client:
        sender = RevalidationSender(client, url, SecretStr(SECRET))
        assert sender.enabled
        with caplog.at_level(logging.DEBUG):
            await sender.send_automatic(RevalidationTag.CATEGORIES)

    assert requests == []
    assert "tag=categories kind=invalid_url status=None" in caplog.text
    assert url not in caplog.text
    assert SECRET not in caplog.text


@pytest.mark.parametrize("status", [301, 302, 307, 400, 401, 404, 503])
async def test_non_200_response_logs_one_failure_and_never_redirects(
    status, caplog
) -> None:
    requests = []

    def receive(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            status,
            headers={"Location": "https://elsewhere.invalid/private"},
            content=b"private-response-body",
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(receive), follow_redirects=True
    ) as client:
        sender = RevalidationSender(client, SITE_URL, SecretStr(SECRET))
        with caplog.at_level(logging.DEBUG):
            await sender.send_automatic(RevalidationTag.NOTICES)

    assert len(requests) == 1
    assert f"tag=notices kind=http_status status={status}" in caplog.text
    assert SITE_URL not in caplog.text
    assert "elsewhere.invalid" not in caplog.text
    assert "private-response-body" not in caplog.text
    assert SECRET not in caplog.text
    assert (
        len(
            [
                record
                for record in caplog.records
                if record.name == sender_module.__name__
            ]
        )
        == 1
    )


async def test_transport_error_is_safe_logged_once(caplog) -> None:
    calls = 0

    def receive(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("private-exception-text")

    async with httpx.AsyncClient(transport=httpx.MockTransport(receive)) as client:
        sender = RevalidationSender(client, SITE_URL, SecretStr(SECRET))
        with caplog.at_level(logging.DEBUG):
            await sender.send_automatic(RevalidationTag.PLACES)

    assert calls == 1
    assert "tag=places kind=request_error status=None" in caplog.text
    assert "private-exception-text" not in caplog.text
    assert SITE_URL not in caplog.text
    assert SECRET not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


async def test_entire_request_is_bounded_to_ten_seconds(monkeypatch, caplog) -> None:
    monkeypatch.setattr(sender_module, "REQUEST_TIMEOUT_SECONDS", 0.02)
    calls = 0
    cancelled = 0

    async def receive(request: httpx.Request) -> httpx.Response:
        nonlocal calls, cancelled
        calls += 1
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            cancelled += 1
            raise
        return httpx.Response(200)

    started = monotonic()
    async with httpx.AsyncClient(transport=httpx.MockTransport(receive)) as client:
        sender = RevalidationSender(client, SITE_URL, SecretStr(SECRET))
        with caplog.at_level(logging.DEBUG):
            await sender.send_automatic(RevalidationTag.LOST_ITEMS)

    assert calls == cancelled == 1
    assert monotonic() - started < 1
    assert "tag=lost-items kind=timeout status=None" in caplog.text
