"""커밋된 변경의 ISR 태그를 프론트 수신기에 한 번 전송한다."""

import asyncio
import logging
from contextvars import ContextVar
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from backoffice.revalidation.events import RevalidationTag

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 10.0

_sending_revalidation: ContextVar[bool] = ContextVar(
    "sending_revalidation", default=False
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


class _SuppressWebhookHTTPLogs(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _sending_revalidation.get()


_http_log_filter = _SuppressWebhookHTTPLogs()


def _install_http_log_filter() -> None:
    # httpx는 성공한 요청도 URL과 함께 INFO로 기록하고 httpcore는 DEBUG에서
    # 통신 예외를 기록한다. 웹훅 전송 중의 기록만 막고 다른 요청의 로그는 유지한다.
    for name in _HTTP_LOGGERS:
        logging.getLogger(name).addFilter(_http_log_filter)


def _endpoint(base_url: str) -> str:
    """사이트 origin에 고정된 수신 경로만 허용한다."""
    raw = base_url.strip()
    if any(character.isspace() or ord(character) < 32 for character in raw):
        raise ValueError("invalid site URL")
    try:
        parts = urlsplit(raw)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.path not in {"", "/"}
            or "?" in raw
            or "#" in raw
        ):
            raise ValueError("invalid site URL")
        # port 속성 접근 시 숫자가 아닌 포트를 거부한다.
        _ = parts.port
        url = httpx.URL(raw)
        if not url.host or url.userinfo:
            raise ValueError("invalid site URL")
    except (httpx.InvalidURL, ValueError) as error:
        raise ValueError("invalid site URL") from error
    return f"{str(url).rstrip('/')}/api/revalidate"


class RevalidationSender:
    """요청마다 한 번만 보내며 실패가 CRUD 응답에 영향을 주지 않게 한다."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        user_site_url: str | None,
        secret: SecretStr | None,
    ) -> None:
        self._client = client
        self._user_site_url = user_site_url
        self._secret = secret
        _install_http_log_filter()

    @property
    def enabled(self) -> bool:
        """예제의 빈 설정은 정상적인 비활성 상태다."""
        return bool(
            self._user_site_url
            and self._user_site_url.strip()
            and self._secret
            and self._secret.get_secret_value().strip()
        )

    async def send_automatic(self, tag: RevalidationTag) -> None:
        if not self.enabled:
            return

        try:
            url = _endpoint(self._user_site_url or "")
        except ValueError:
            self._log_failure(tag, "invalid_url")
            return

        secret = self._secret.get_secret_value() if self._secret else ""
        token = _sending_revalidation.set(True)
        try:
            try:
                # httpx의 timeout은 단계별이다. 전체 한도를 별도로 감싼다.
                async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
                    async with self._client.stream(
                        "POST",
                        url,
                        headers={"Authorization": f"Bearer {secret}"},
                        json={"tag": tag.value},
                        timeout=REQUEST_TIMEOUT_SECONDS,
                        follow_redirects=False,
                    ) as response:
                        status = response.status_code
            except TimeoutError, httpx.TimeoutException:
                kind = "timeout"
                status = None
            except httpx.RequestError:
                kind = "request_error"
                status = None
            except Exception:
                kind = "unexpected_error"
                status = None
        finally:
            _sending_revalidation.reset(token)

        if status == 200:
            return
        self._log_failure(tag, kind if status is None else "http_status", status)

    @staticmethod
    def _log_failure(
        tag: RevalidationTag, kind: str, status: int | None = None
    ) -> None:
        # 원본 예외·URL·헤더·응답 본문은 로깅하지 않는다.
        logger.warning(
            "ISR revalidation failed tag=%s kind=%s status=%s",
            tag.value,
            kind,
            status,
        )
