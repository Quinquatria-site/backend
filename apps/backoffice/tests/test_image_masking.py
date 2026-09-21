"""presigned URL의 query string은 만료 전까지 업로드 권한 그 자체다.

로그에 남으면 그 key에 누구나 쓸 수 있다. 명세 §4.5가 마스킹을 요구한다.
"""

import logging
from urllib.parse import parse_qs, urlparse

import pytest

from backoffice.images.masking import mask_presigned_url, suppress_sdk_signature_logs
from backoffice.images.s3 import S3ObjectStore

SIGNED = (
    "https://bucket.s3.ap-northeast-2.amazonaws.com/images/place/a.webp"
    "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=AKIA%2F20261006"
    "&X-Amz-Signature=deadbeef&X-Amz-SignedHeaders=content-type%3Bhost"
)


def test_signature_is_removed() -> None:
    assert "deadbeef" not in mask_presigned_url(SIGNED)


def test_credential_is_removed() -> None:
    assert "AKIA" not in mask_presigned_url(SIGNED)


def test_object_key_survives() -> None:
    """어떤 객체에 대한 로그인지는 남아야 조사할 수 있다."""
    assert "images/place/a.webp" in mask_presigned_url(SIGNED)


def test_masked_url_marks_the_redaction() -> None:
    assert mask_presigned_url(SIGNED).endswith("?<redacted>")


def test_url_without_a_query_is_unchanged() -> None:
    plain = "https://bucket.s3.ap-northeast-2.amazonaws.com/images/place/a.webp"

    assert mask_presigned_url(plain) == plain


# 유출은 SDK가 서명을 계산하며 내는 로그에서 생긴다. 가짜 store로는 안 잡힌다.

KEY = "images/place/a.webp"


@pytest.fixture
def signature_logger_level():
    """테스트가 건드린 SDK 로거 레벨을 원래대로 돌려놓는다."""
    logger = logging.getLogger("botocore.auth")
    original = logger.level
    try:
        yield logger
    finally:
        logger.setLevel(original)


@pytest.fixture
def store() -> S3ObjectStore:
    return S3ObjectStore(
        bucket="quinquatria-test",
        region="ap-northeast-2",
        access_key_id="AKIAIOSFODNN7EXAMPLE",
        secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    )


async def _presign_and_capture(store: S3ObjectStore, caplog) -> tuple[str, str]:
    caplog.set_level(logging.DEBUG)
    url = await store.presign_put(KEY, content_type="image/webp", expires_in=300)
    return parse_qs(urlparse(url).query)["X-Amz-Signature"][0], caplog.text


async def test_sdk_debug_leaks_the_signature_when_not_suppressed(
    store: S3ObjectStore, signature_logger_level, caplog
) -> None:
    """억제가 없으면 실제로 샌다는 근거. 이게 깨지면 억제는 필요 없어진 것이다."""
    signature_logger_level.setLevel(logging.NOTSET)

    signature, logged = await _presign_and_capture(store, caplog)

    assert signature in logged


async def test_sdk_debug_does_not_leak_the_signature_once_suppressed(
    store: S3ObjectStore, signature_logger_level, caplog
) -> None:
    """루트를 DEBUG로 올려도 서명은 어느 로거에도 남지 않아야 한다."""
    suppress_sdk_signature_logs()

    signature, logged = await _presign_and_capture(store, caplog)

    assert signature not in logged


async def test_create_app_suppresses_signature_logs(
    store: S3ObjectStore, signature_logger_level, caplog
) -> None:
    """배포 계약은 앱을 띄우기만 하면 지켜져야 한다. 호출을 잊으면 여기서 깨진다."""
    from backoffice.main import create_app

    signature_logger_level.setLevel(logging.NOTSET)
    create_app()

    signature, logged = await _presign_and_capture(store, caplog)

    assert signature not in logged
