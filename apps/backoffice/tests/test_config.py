"""설정은 환경변수에서만 읽고, 값이 불완전하면 기동을 막아야 한다."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backoffice.config import (
    MAX_IMAGE_BYTES,
    MIN_ISSUANCE_CODE_LENGTH,
    MIN_SIGNING_KEY_BYTES,
    Settings,
    get_settings,
)
from backoffice.main import create_app

VALID_KEY = "k" * MIN_SIGNING_KEY_BYTES
VALID_CODE = "issuance-code-from-env"

# Pydantic이 오류 문자열의 입력값을 잘라내므로 표시값을 값의 맨 앞에 둔다.
LEAKY_CODE = "leakycode-000001"
LEAKY_KEY_MARK = "leakykey"
LEAKY_KEY = LEAKY_KEY_MARK.ljust(MIN_SIGNING_KEY_BYTES, "0")
SHORT_LEAKY_KEY = LEAKY_KEY_MARK.ljust(MIN_SIGNING_KEY_BYTES - 1, "0")

REQUIRED_SETTINGS = (
    "BACKOFFICE_ISSUANCE_CODE",
    "BACKOFFICE_JWT_SIGNING_KEY",
    # DB는 Customer와 공유하므로 앱 prefix를 붙이지 않는다.
    "DATABASE_URL",
    "BACKOFFICE_S3_BUCKET",
    "BACKOFFICE_S3_REGION",
)

WEAK_SECRETS = (
    ("BACKOFFICE_JWT_SIGNING_KEY", "short"),
    ("BACKOFFICE_ISSUANCE_CODE", "short"),
    ("BACKOFFICE_ISSUANCE_CODE", "code with spaces"),
)


@contextmanager
def _fresh_settings() -> Iterator[None]:
    """`get_settings`는 캐시되므로 앞선 테스트의 성공한 설정이 남지 않게 한다."""
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


DATABASE_URL = "postgresql+psycopg://user:pw@localhost/quinquatria"


def _set_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACKOFFICE_ISSUANCE_CODE", VALID_CODE)
    monkeypatch.setenv("BACKOFFICE_JWT_SIGNING_KEY", VALID_KEY)
    # DB는 Customer와 공유하므로 앱 prefix를 붙이지 않는다.
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
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


@pytest.mark.parametrize("missing", REQUIRED_SETTINGS)
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


@pytest.mark.parametrize(
    ("broken", "secret"),
    [
        ("BACKOFFICE_JWT_SIGNING_KEY", "short"),
        ("BACKOFFICE_ISSUANCE_CODE", "short"),
        ("BACKOFFICE_ISSUANCE_CODE", "code with spaces"),
    ],
)
def test_rejected_secret_does_not_leak_through_the_validation_error(
    monkeypatch: pytest.MonkeyPatch, broken: str, secret: str
) -> None:
    """예외 문자열에 값이 실리면 예외를 기록하는 모든 곳이 유출 경로가 된다."""
    _set_required(monkeypatch)
    monkeypatch.setenv(broken, secret)

    with pytest.raises(ValidationError) as raised:
        Settings()

    rendered = str(raised.value) + repr(raised.value)
    assert "input_value" not in rendered
    assert secret not in rendered


@pytest.mark.parametrize("missing", REQUIRED_SETTINGS)
def test_missing_setting_does_not_leak_the_other_secrets(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    """`missing` 오류의 입력값은 필드 하나가 아니라 설정 전체 dict다."""
    _set_required(monkeypatch)
    monkeypatch.setenv("BACKOFFICE_ISSUANCE_CODE", LEAKY_CODE)
    monkeypatch.setenv("BACKOFFICE_JWT_SIGNING_KEY", LEAKY_KEY)
    monkeypatch.delenv(missing)

    with pytest.raises(ValidationError) as raised:
        Settings()

    rendered = str(raised.value) + repr(raised.value)
    assert "input_value" not in rendered
    assert LEAKY_CODE not in rendered
    assert LEAKY_KEY_MARK not in rendered


def test_settings_failure_during_a_request_does_not_log_the_secret(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """설정은 지연 로드되므로 검증 실패가 요청 처리 중의 예외 로그로 흘러나온다."""
    _set_required(monkeypatch)
    monkeypatch.setenv("BACKOFFICE_ISSUANCE_CODE", LEAKY_CODE)
    monkeypatch.setenv("BACKOFFICE_JWT_SIGNING_KEY", SHORT_LEAKY_KEY)
    get_settings.cache_clear()

    client = TestClient(create_app(), raise_server_exceptions=False)
    try:
        with caplog.at_level(logging.DEBUG):
            response = client.post(
                "/api/v1/auth/token", json={"issuance_code": LEAKY_CODE}
            )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 500
    assert LEAKY_CODE not in caplog.text
    assert LEAKY_KEY_MARK not in caplog.text
    assert LEAKY_CODE not in response.text
    assert LEAKY_KEY_MARK not in response.text


@pytest.mark.parametrize("missing", REQUIRED_SETTINGS)
def test_app_start_fails_when_a_required_setting_is_missing(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    _set_required(monkeypatch)
    monkeypatch.delenv(missing)

    with _fresh_settings(), pytest.raises(ValidationError), TestClient(create_app()):
        pass


@pytest.mark.parametrize(("broken", "value"), WEAK_SECRETS)
def test_app_start_fails_when_a_secret_is_weak(
    monkeypatch: pytest.MonkeyPatch, broken: str, value: str
) -> None:
    _set_required(monkeypatch)
    monkeypatch.setenv(broken, value)

    with _fresh_settings(), pytest.raises(ValidationError), TestClient(create_app()):
        pass


def test_health_check_cannot_pass_on_a_misconfigured_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """설정이 잘못된 인스턴스가 헬스체크를 통과하면 배포가 그대로 올라간다."""
    for name in REQUIRED_SETTINGS:
        monkeypatch.delenv(name, raising=False)

    with _fresh_settings(), pytest.raises(ValidationError):
        with TestClient(create_app()) as client:
            client.get("/api/v1/")


def test_app_starts_and_serves_the_health_check_with_valid_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required(monkeypatch)

    with _fresh_settings(), TestClient(create_app()) as client:
        assert client.get("/api/v1/").status_code == 200


def test_start_failure_does_not_log_the_secret(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _set_required(monkeypatch)
    monkeypatch.setenv("BACKOFFICE_ISSUANCE_CODE", LEAKY_CODE)
    monkeypatch.setenv("BACKOFFICE_JWT_SIGNING_KEY", SHORT_LEAKY_KEY)

    with _fresh_settings(), caplog.at_level(logging.DEBUG):
        with pytest.raises(ValidationError), TestClient(create_app()):
            pass

    assert LEAKY_CODE not in caplog.text
    assert LEAKY_KEY_MARK not in caplog.text


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
