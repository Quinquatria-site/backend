"""라우트가 주입받는 인증 관련 의존성.

rate limiter를 의존성으로 노출해야 계약 테스트가 Redis 없이 돌 수 있다.
"""

from typing import Annotated

from fastapi import Depends, Request

from backoffice.auth.rate_limit import RateLimiter, RedisRateLimiter
from backoffice.auth.tokens import invalid_token_error, verify_token
from backoffice.config import Settings, get_settings

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_rate_limiter(request: Request, settings: SettingsDep) -> RateLimiter:
    """lifespan이 만든 연결 풀 위에 limiter를 얹는다."""
    return RedisRateLimiter(
        request.app.state.redis,
        limit=settings.rate_limit_max,
        window_seconds=settings.rate_limit_window_seconds,
    )


_BEARER_SCHEME = "bearer"


def require_admin(request: Request, settings: SettingsDep) -> None:
    """`Authorization: Bearer <token>`을 검증한다.

    헤더 누락과 토큰 검증 실패를 같은 401로 수렴시킨다.
    """
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != _BEARER_SCHEME or not token.strip():
        raise invalid_token_error()

    verify_token(token.strip(), signing_key=settings.jwt_signing_key.get_secret_value())
