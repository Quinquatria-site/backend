"""명세 §4.2의 JWT 발급과 검증.

`now`를 인자로 받는 순수 함수라 Redis도 DB도 없이 시간 의존 동작을 시험할 수 있다.
"""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt

from common.errors import ApiError, ErrorCode

ISSUER = "quinquatria-backoffice"
AUDIENCE = "quinquatria-backoffice-api"
SUBJECT = "admin"
ALGORITHM = "HS256"

_REQUIRED_CLAIMS = ["iss", "aud", "sub", "iat", "exp", "jti"]
_CHALLENGE = {"WWW-Authenticate": "Bearer"}


def invalid_token_error() -> ApiError:
    """검증 실패를 하나의 응답으로 수렴시킨다.

    만료인지 서명 불일치인지 구분해 알려주면 공격자가 어떤 조작이 통했는지
    알 수 있으므로 사유를 담지 않는다.
    """
    return ApiError(ErrorCode.INVALID_TOKEN, headers=_CHALLENGE)


def issue_token(*, signing_key: str, now: datetime, ttl_seconds: int) -> str:
    """명세 §4.2의 claim을 담은 access token을 발급한다."""
    issued_at = int(now.timestamp())
    expires_at = int((now + timedelta(seconds=ttl_seconds)).timestamp())
    return jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": SUBJECT,
            "iat": issued_at,
            "exp": expires_at,
            "jti": str(uuid4()),
        },
        signing_key,
        algorithm=ALGORITHM,
    )


def verify_token(token: str, *, signing_key: str) -> dict[str, Any]:
    """서명과 필수 claim을 검증하고 claim을 돌려준다.

    `algorithms`를 HS256 하나로 고정해 `alg: none`과 비대칭 키 혼동 공격을 막는다.

    (의도적 예외) 만료·발급 시각 검증은 PyJWT에 맡기므로 이 함수만은 `now`를
    주입받지 않고 실제 시계를 읽는다. 직접 검증하려면 PyJWT의 `verify_exp`를
    끄고 만료 판정을 손으로 다시 구현해야 하는데, 그쪽이 더 위험하다.
    """
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            signing_key,
            algorithms=[ALGORITHM],
            issuer=ISSUER,
            audience=AUDIENCE,
            options={"require": _REQUIRED_CLAIMS},
        )
    except jwt.InvalidTokenError as error:
        raise invalid_token_error() from error

    if claims.get("sub") != SUBJECT:
        raise invalid_token_error()

    try:
        UUID(str(claims["jti"]))
    except ValueError as error:
        raise invalid_token_error() from error

    return claims
