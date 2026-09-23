"""ISR 수신 요청을 제한된 시간 안에 전송하고 안전한 결과만 기록한다."""

import asyncio
import logging
from contextvars import ContextVar
from time import monotonic
from typing import Literal
from urllib.parse import urlsplit

import httpx

from backoffice.revalidation.schemas import RevalidationRequest

logger = logging.getLogger(__name__)

ATTEMPT_TIMEOUT_SECONDS = 5.0
RETRY_DELAY_SECONDS = 0.5
TOTAL_TIMEOUT_SECONDS = 10.5
MAX_ATTEMPTS = 2

_RETRYABLE_STATUSES = frozenset((502, 503, 504))
_COMMUNICATION_ERRORS = (
    httpx.NetworkError,
    httpx.RemoteProtocolError,
    httpx.ProxyError,
)
_HTTP_LOGGERS = (
    "httpx",
    "httpcore",
    "httpcore.connection",
    "httpcore.http11",
    "httpcore.http2",
    "httpcore.proxy",
    "httpcore.socks",
)
_sending_revalidation: ContextVar[bool] = ContextVar(
    "sending_revalidation", default=False
)


class _SuppressRevalidationHTTPLogs(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _sending_revalidation.get()


_http_log_filter = _SuppressRevalidationHTTPLogs()


class RevalidationFailed(Exception):
    """URL, 응답 본문이나 원본 통신 예외를 포함하지 않는 전송 실패."""


def _record(
    event: RevalidationRequest,
    *,
    source: Literal["automatic", "manual"],
    attempt: int,
    outcome: str,
    status: int | None,
    started: float,
) -> None:
    fields = {
        "target": event.target.value,
        "resource_type": event.resource_type.value,
        "id": event.id,
        "source": source,
        "attempt": attempt,
        "outcome": outcome,
        "status": status,
        "elapsed": round(monotonic() - started, 6),
    }
    logger.log(
        logging.INFO if outcome == "success" else logging.WARNING,
        "ISR revalidation result target=%(target)s resource_type=%(resource_type)s "
        "id=%(id)s source=%(source)s attempt=%(attempt)d outcome=%(outcome)s "
        "status=%(status)s elapsed=%(elapsed).6f",
        fields,
        extra=fields,
    )


class RevalidationSender:
    def __init__(self, client: httpx.AsyncClient, url: str | None) -> None:
        self._client = client
        self._url = url
        # httpx는 INFO에서 URL을, httpcore는 DEBUG에서 통신 예외를 기록한다.
        # logger의 전역 레벨 대신 현재 요청 context만 필터링하여 다른 동시
        # HTTP 요청의 진단 로그는 유지한다. trace callback만으로는 억제되지 않는다.
        for name in _HTTP_LOGGERS:
            logging.getLogger(name).addFilter(_http_log_filter)

    async def send(
        self,
        event: RevalidationRequest,
        *,
        source: Literal["automatic", "manual"],
    ) -> None:
        started = monotonic()
        try:
            # HTTPX가 host로 허용하는 잘못된 IPv6 괄호도 설정 오류로 처리한다.
            urlsplit(self._url or "")
            url = httpx.URL(self._url or "")
            if url.scheme not in ("http", "https") or not url.host or url.userinfo:
                raise ValueError
        except httpx.InvalidURL, ValueError:
            _record(
                event,
                source=source,
                attempt=0,
                outcome="invalid_configuration",
                status=None,
                started=started,
            )
            raise RevalidationFailed("ISR revalidation request failed") from None

        payload = event.model_dump(mode="json", exclude_none=True)
        token = _sending_revalidation.set(True)
        attempt = 0
        try:
            async with asyncio.timeout(TOTAL_TIMEOUT_SECONDS):
                for attempt in range(1, MAX_ATTEMPTS + 1):
                    status = None
                    retryable = False
                    try:
                        async with asyncio.timeout(ATTEMPT_TIMEOUT_SECONDS):
                            # 수신 응답의 상태만 필요하다. 본문은 읽거나 기록하지
                            # 않고 닫으며 redirect는 다른 URL로 따라가지 않는다.
                            async with self._client.stream(
                                "POST",
                                url,
                                json=payload,
                                timeout=ATTEMPT_TIMEOUT_SECONDS,
                                follow_redirects=False,
                            ) as response:
                                status = response.status_code
                        outcome = "success" if 200 <= status < 300 else "http_status"
                        retryable = status in _RETRYABLE_STATUSES
                    except TimeoutError, httpx.TimeoutException:
                        outcome = "timeout"
                        retryable = True
                    except _COMMUNICATION_ERRORS:
                        outcome = "communication_error"
                        retryable = True
                    except Exception:
                        # 원본 예외의 문자열·traceback에는 URL 등이 포함될 수 있다.
                        outcome = "request_error"

                    retry = retryable and attempt < MAX_ATTEMPTS
                    _record(
                        event,
                        source=source,
                        attempt=attempt,
                        outcome=f"retry_{outcome}" if retry else outcome,
                        status=status,
                        started=started,
                    )
                    if outcome == "success":
                        return
                    if not retry:
                        raise RevalidationFailed("ISR revalidation request failed")
                    await asyncio.sleep(RETRY_DELAY_SECONDS)
        except TimeoutError:
            _record(
                event,
                source=source,
                attempt=attempt,
                outcome="total_timeout",
                status=None,
                started=started,
            )
            raise RevalidationFailed("ISR revalidation request failed") from None
        finally:
            _sending_revalidation.reset(token)

    async def send_automatic(self, event: RevalidationRequest) -> None:
        started = monotonic()
        try:
            await self.send(event, source="automatic")
        except RevalidationFailed:
            # 개별 시도는 send에서 이미 기록했다. 다음 background 작업은 계속한다.
            pass
        except Exception:
            _record(
                event,
                source="automatic",
                attempt=0,
                outcome="unexpected_error",
                status=None,
                started=started,
            )
