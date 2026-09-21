"""배포 계약 §8 - 서명을 응답 본문 밖에 남기지 않기 위한 로그 위생."""

import logging

_SIGNATURE_LOGGERS = ("botocore.auth",)
"""DEBUG에서 `X-Amz-Signature` 값을 hex 그대로 남기는 SDK 로거."""


def mask_presigned_url(url: str) -> str:
    """object key까지만 남기고 query string을 지운다."""
    base, separator, _ = url.partition("?")
    return f"{base}?<redacted>" if separator else base


def suppress_sdk_signature_logs() -> None:
    """서명을 남기는 SDK 로거를 DEBUG 아래로 내린다."""
    for name in _SIGNATURE_LOGGERS:
        logging.getLogger(name).setLevel(logging.INFO)
