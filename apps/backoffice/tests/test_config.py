"""설정은 환경변수에서만 읽고, 값이 불완전하면 기동을 막아야 한다."""

import pytest
from pydantic import ValidationError

from backoffice.config import (
    MAX_IMAGE_BYTES,
    MIN_ISSUANCE_CODE_LENGTH,
    MIN_SIGNING_KEY_BYTES,
    Settings,
    get_settings,
)

VALID_KEY = "k" * MIN_SIGNING_KEY_BYTES
VALID_CODE = "issuance-code-from-env"


def _set_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACKOFFICE_ISSUANCE_CODE", VALID_CODE)
    monkeypatch.setenv("BACKOFFICE_JWT_SIGNING_KEY", VALID_KEY)
    monkeypatch.setenv(
        "BACKOFFICE_DATABASE_URL", "postgresql+psycopg://user:pw@localhost/quinquatria"
    )
    monkeypatch.setenv("BACKOFFICE_S3_BUCKET", "quinquatria-assets")
    monkeypatch.setenv("BACKOFFICE_S3_REGION", "ap-northeast-2")


def test_reads_secrets_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)

    settings = Settings()

    assert settings.issuance_code.get_secret_value() == VALID_CODE
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
        "BACKOFFICE_DATABASE_URL",
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


@pytest.mark.parametrize(
    "weak_code",
    [
        "",
        "   ",
        "\t",
        "\n",
        "short",
        "k" * (MIN_ISSUANCE_CODE_LENGTH - 1),
    ],
)
def test_weak_issuance_code_fails_fast(
    monkeypatch: pytest.MonkeyPatch, weak_code: str
) -> None:
    """빈 코드는 compare_digest를 무조건 통과시키고, 짧은 코드는 추측된다."""
    _set_required(monkeypatch)
    monkeypatch.setenv("BACKOFFICE_ISSUANCE_CODE", weak_code)

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    "spaced_code",
    [
        "code with spaces!",
        " leading-whitespace-code",
        "trailing-whitespace-code\n",
    ],
)
def test_issuance_code_with_whitespace_fails_fast(
    monkeypatch: pytest.MonkeyPatch, spaced_code: str
) -> None:
    """주입 과정에서 섞인 공백은 진단할 수 없는 영구 401이 되므로 기동을 막는다."""
    _set_required(monkeypatch)
    monkeypatch.setenv("BACKOFFICE_ISSUANCE_CODE", spaced_code)

    with pytest.raises(ValidationError):
        Settings()


def test_issuance_code_at_the_minimum_length_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required(monkeypatch)
    code = "c" * MIN_ISSUANCE_CODE_LENGTH
    monkeypatch.setenv("BACKOFFICE_ISSUANCE_CODE", code)

    assert Settings().issuance_code.get_secret_value() == code


def test_issuance_code_is_not_silently_trimmed(monkeypatch: pytest.MonkeyPatch) -> None:
    """서버가 비밀값을 변형하면 설정한 값과 실제 값이 달라진다."""
    _set_required(monkeypatch)

    assert Settings().issuance_code.get_secret_value() == VALID_CODE


def test_minimum_issuance_code_length_follows_the_spec() -> None:
    assert MIN_ISSUANCE_CODE_LENGTH == 16


def test_blank_issuance_code_cannot_start_the_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """설정은 지연 로드되므로 토큰 발급 경로에서 기동 실패가 드러나야 한다."""
    _set_required(monkeypatch)
    monkeypatch.setenv("BACKOFFICE_ISSUANCE_CODE", "")
    get_settings.cache_clear()

    with pytest.raises(ValidationError):
        get_settings()

    get_settings.cache_clear()


def test_secrets_do_not_leak_through_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)

    rendered = repr(Settings())

    assert VALID_CODE not in rendered
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


def test_static_aws_credentials_are_not_configurable() -> None:
    """workload IAM role만 쓰므로 정적 키를 받는 입구를 두지 않는다."""
    fields = set(Settings.model_fields)

    assert not {name for name in fields if "access_key" in name or "secret" in name}
