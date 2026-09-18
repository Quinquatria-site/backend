"""설정은 환경변수에서만 읽고, 값이 불완전하면 기동을 막아야 한다."""

import pytest
from pydantic import ValidationError

from backoffice.config import (
    MAX_IMAGE_BYTES,
    MIN_SIGNING_KEY_BYTES,
    Settings,
    get_settings,
)

VALID_KEY = "k" * MIN_SIGNING_KEY_BYTES


DATABASE_URL = "postgresql+psycopg://user:pw@localhost/quinquatria"


def _set_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACKOFFICE_ISSUANCE_CODE", "code-from-env")
    monkeypatch.setenv("BACKOFFICE_JWT_SIGNING_KEY", VALID_KEY)
    # DB는 Customer와 공유하므로 앱 prefix를 붙이지 않는다.
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("BACKOFFICE_S3_BUCKET", "quinquatria-assets")
    monkeypatch.setenv("BACKOFFICE_S3_REGION", "ap-northeast-2")


def test_reads_secrets_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)

    settings = Settings()

    assert settings.issuance_code.get_secret_value() == "code-from-env"
    assert settings.jwt_signing_key.get_secret_value() == VALID_KEY


def test_defaults_follow_the_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)

    settings = Settings()

    assert settings.token_ttl_seconds == 18000


@pytest.mark.parametrize(
    "missing",
    [
        "BACKOFFICE_ISSUANCE_CODE",
        "BACKOFFICE_JWT_SIGNING_KEY",
        "DATABASE_URL",
        "BACKOFFICE_S3_BUCKET",
        "BACKOFFICE_S3_REGION",
    ],
)
def test_missing_required_setting_fails_fast(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    _set_required(monkeypatch)
    monkeypatch.delenv(missing)

    with pytest.raises(ValidationError):
        Settings()


def test_short_signing_key_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)
    monkeypatch.setenv("BACKOFFICE_JWT_SIGNING_KEY", "k" * (MIN_SIGNING_KEY_BYTES - 1))

    with pytest.raises(ValidationError):
        Settings()


def test_secrets_do_not_leak_through_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)

    rendered = repr(Settings())

    assert "code-from-env" not in rendered
    assert VALID_KEY not in rendered


def test_get_settings_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)
    get_settings.cache_clear()

    assert get_settings() is get_settings()

    get_settings.cache_clear()


def test_s3_defaults_follow_the_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)

    settings = Settings()

    assert settings.s3_bucket == "quinquatria-assets"
    assert settings.s3_region == "ap-northeast-2"
    assert settings.s3_endpoint_url is None
    assert settings.presigned_url_ttl_seconds == 300
    assert settings.max_image_bytes == MAX_IMAGE_BYTES
    assert settings.cleanup_grace_seconds == 86400
    assert settings.cleanup_batch_size == 500


def test_max_image_bytes_is_ten_mebibytes() -> None:
    assert MAX_IMAGE_BYTES == 10 * 1024 * 1024


def test_database_url_is_read_without_the_app_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DB는 Customer와 공유하므로 앱마다 다른 이름을 갖지 않는다.

    `migrations/env.py`도 같은 `DATABASE_URL`을 읽는다. 이름이 갈리면 앱과
    마이그레이션이 서로 다른 DB를 가리켜도 아무도 알아채지 못한다.
    """
    _set_required(monkeypatch)

    assert Settings().database_url == DATABASE_URL


def test_prefixed_database_url_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """`BACKOFFICE_DATABASE_URL`은 더 이상 설정 입구가 아니다."""
    _set_required(monkeypatch)
    monkeypatch.delenv("DATABASE_URL")
    monkeypatch.setenv("BACKOFFICE_DATABASE_URL", DATABASE_URL)

    with pytest.raises(ValidationError):
        Settings()


def test_static_aws_credentials_are_not_configurable() -> None:
    """workload IAM role만 쓰므로 정적 키를 받는 입구를 두지 않는다."""
    # 인스턴스의 `model_fields` 접근은 Pydantic V3에서 제거되므로 클래스에서 읽는다.
    fields = set(Settings.model_fields)

    assert not {name for name in fields if "access_key" in name or "secret" in name}
