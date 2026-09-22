"""Backoffice 애플리케이션 설정.

비밀값은 배포 환경이 주입한 환경변수에서만 읽는다. 필수 설정이 없으면 기본값으로
넘어가지 않고 기동에 실패시킨다. 인증이 꺼진 채 뜨는 것이 뜨지 않는 것보다 나쁘다.
"""

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_SIGNING_KEY_BYTES = 32
"""명세 §4.2가 요구하는 256-bit 이상의 서명 키 길이."""

MIN_ISSUANCE_CODE_LENGTH = 16
"""명세 §4.2가 요구하는 발급 코드 최소 길이."""

MAX_IMAGE_BYTES = 10 * 1024 * 1024
"""명세 §4.5가 허용하는 최대 이미지 크기 (10 MiB)."""


class Settings(BaseSettings):
    """환경변수 `BACKOFFICE_*`에서 읽는 실행 설정.

    예외는 `database_url` 하나다. 아래 필드 주석을 참고한다.
    """

    # 정적 AWS access key를 받지 않는다. 서명은 workload IAM role의 임시
    # credential로 하며, 키를 설정에 두면 유출 시 만료가 없다.
    #
    # `populate_by_name`을 켜지 않는다. 켜면 alias를 쓰는 필드가 prefix 붙은
    # 이름으로도 들어와, 없애려던 `BACKOFFICE_DATABASE_URL`이 조용한 fallback으로
    # 되살아난다.
    #
    # 검증 오류는 `SecretStr`로 감싸기 전의 원본 입력을 싣고, `missing` 오류는
    # 설정 전체 dict를 싣는다. 설정은 지연 로드되므로 예외 로그로 흘러나간다.
    model_config = SettingsConfigDict(
        env_prefix="BACKOFFICE_", hide_input_in_errors=True
    )

    issuance_code: SecretStr
    jwt_signing_key: SecretStr
    database_url: str = Field(validation_alias="DATABASE_URL")
    """Customer와 공유하는 DB. 앱 prefix를 붙이지 않는 유일한 설정이다.

    두 앱이 같은 DB를 쓰므로 앱마다 다른 이름을 두면 같은 값을 두 번 주입해야
    하고, 한쪽만 바꿨을 때 앱과 마이그레이션이 서로 다른 DB를 가리키게 된다.
    `migrations/env.py`도 같은 `DATABASE_URL`을 읽는다.
    """

    s3_bucket: str
    s3_region: str

    s3_endpoint_url: str | None = None
    token_ttl_seconds: int = Field(18000, ge=1)
    presigned_url_ttl_seconds: int = Field(300, ge=1)
    max_image_bytes: int = Field(MAX_IMAGE_BYTES, ge=1, le=MAX_IMAGE_BYTES)
    """낮추는 것만 허용한다. 원장 CHECK가 10 MiB로 고정돼 있다."""
    cleanup_grace_seconds: int = Field(86400, ge=0)
    cleanup_batch_size: int = Field(500, ge=1)

    revalidation_url: str | None = Field(default=None, repr=False)
    """프론트 수신 URL. 미설정 상태에서도 시작하며 전송 시 실패로 처리한다."""

    @field_validator("issuance_code")
    @classmethod
    def _issuance_code_is_strong_enough(cls, value: SecretStr) -> SecretStr:
        """토큰 발급은 인증 없이 호출되고 요청 수 제한은 앱 밖(명세 §4.1의 reverse
        proxy)에 있다. 코드의 추측 난이도가 유일한 방어선이므로 약한 코드로는 뜨지
        않는다. 값은 다듬지 않는다. 비밀값을 서버가 변형하면 설정한 값과 실제 값이
        달라진다.
        """
        code = value.get_secret_value()
        if any(character.isspace() for character in code):
            # 비교는 byte 단위라 주입 과정에서 섞인 공백 하나가 진단할 수 없는
            # 영구 401이 된다. 명세 §4.1상 응답은 불일치 이유를 알려주지 않는다.
            raise ValueError("발급 코드에는 공백 문자를 포함할 수 없습니다")
        if len(code) < MIN_ISSUANCE_CODE_LENGTH:
            # 빈 코드는 compare_digest를 무조건 통과시킨다. 길이 하한이 그 경우와
            # 추측 가능한 짧은 코드를 함께 막는다.
            raise ValueError(
                f"발급 코드는 {MIN_ISSUANCE_CODE_LENGTH}자 이상이어야 합니다"
            )
        return value

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
