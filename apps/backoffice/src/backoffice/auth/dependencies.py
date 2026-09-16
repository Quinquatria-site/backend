"""라우트가 주입받는 인증 관련 의존성."""

from typing import Annotated

from fastapi import Depends, Request

from backoffice.auth.tokens import invalid_token_error, verify_token
from backoffice.config import Settings, get_settings

SettingsDep = Annotated[Settings, Depends(get_settings)]

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
