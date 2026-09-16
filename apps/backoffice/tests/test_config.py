"""설정은 환경변수에서만 읽고, 값이 불완전하면 기동을 막아야 한다."""

import pytest
from pydantic import ValidationError

from backoffice.config import MIN_SIGNING_KEY_BYTES, Settings, get_settings

VALID_KEY = "k" * MIN_SIGNING_KEY_BYTES


def _set_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACKOFFICE_ISSUANCE_CODE", "code-from-env")
    monkeypatch.setenv("BACKOFFICE_JWT_SIGNING_KEY", VALID_KEY)


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
