"""Backoffice 애플리케이션 설정.

비밀값은 배포 환경이 주입한 환경변수에서만 읽는다. 필수 설정이 없으면 기본값으로
넘어가지 않고 기동에 실패시킨다. 인증이 꺼진 채 뜨는 것이 뜨지 않는 것보다 나쁘다.
"""

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_SIGNING_KEY_BYTES = 32
"""명세 §4.2가 요구하는 256-bit 이상의 서명 키 길이."""


class Settings(BaseSettings):
    """환경변수 `BACKOFFICE_*`에서 읽는 실행 설정."""

    model_config = SettingsConfigDict(env_prefix="BACKOFFICE_")

    issuance_code: SecretStr
    jwt_signing_key: SecretStr

    token_ttl_seconds: int = Field(18000, ge=1)

    @field_validator("jwt_signing_key")
    @classmethod
    def _signing_key_is_long_enough(cls, value: SecretStr) -> SecretStr:
        """짧은 키는 brute force로 서명을 위조할 수 있으므로 기동을 막는다."""
        if len(value.get_secret_value().encode()) < MIN_SIGNING_KEY_BYTES:
            raise ValueError(
                f"JWT 서명 키는 {MIN_SIGNING_KEY_BYTES} byte 이상이어야 합니다"
            )
        return value


@lru_cache
def get_settings() -> Settings:
    """FastAPI 의존성으로 주입할 설정 싱글턴.

    테스트는 `dependency_overrides`로 교체하거나 `cache_clear()`를 호출한다.
    """
    return Settings()
