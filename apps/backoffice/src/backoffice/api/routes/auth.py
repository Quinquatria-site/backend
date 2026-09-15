"""명세 §4.1의 토큰 발급 엔드포인트.

Bearer 인증 없이 호출하는 유일한 Backoffice API다.
"""

from datetime import UTC, datetime
from hmac import compare_digest
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, SecretStr

from backoffice.auth.client_ip import client_ip
from backoffice.auth.dependencies import SettingsDep, get_rate_limiter
from backoffice.auth.rate_limit import KEY_PREFIX, RateLimiter
from backoffice.auth.tokens import issue_token
from common.errors import ApiError, ErrorCode
from common.query import NoQuery

router = APIRouter()

TOKEN_TYPE = "Bearer"
_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


class TokenRequest(BaseModel):
    """`SecretStr`이라 검증 오류 메시지에 값이 실리지 않는다."""

    issuance_code: SecretStr


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int


async def enforce_rate_limit(
    request: Request,
    settings: SettingsDep,
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> None:
    """명세 §4.1대로 성공과 실패를 모두 집계한다.

    route dependency는 본문 검증보다 먼저 풀리므로 본문이 잘못된 요청도 센다.
    """
    address = client_ip(request, trusted_proxy_hops=settings.trusted_proxy_hops)
    decision = await limiter.hit(f"{KEY_PREFIX}:{address}")
    if not decision.allowed:
        raise ApiError(
            ErrorCode.RATE_LIMIT_EXCEEDED,
            headers={"Retry-After": str(decision.retry_after)},
        )


@router.post("/auth/token", dependencies=[Depends(enforce_rate_limit)])
async def issue_access_token(
    body: TokenRequest,
    settings: SettingsDep,
    response: Response,
    query: Annotated[NoQuery, Query()],
) -> TokenResponse:
    supplied = body.issuance_code.get_secret_value().encode()
    expected = settings.issuance_code.get_secret_value().encode()
    # 상수 시간 비교로 일치하는 접두사 길이가 응답 시간에 드러나지 않게 한다.
    if not compare_digest(supplied, expected):
        raise ApiError(ErrorCode.INVALID_CREDENTIALS)

    token = issue_token(
        signing_key=settings.jwt_signing_key.get_secret_value(),
        now=datetime.now(UTC),
        ttl_seconds=settings.token_ttl_seconds,
    )
    response.headers.update(_NO_STORE)
    return TokenResponse(
        access_token=token,
        token_type=TOKEN_TYPE,
        expires_in=settings.token_ttl_seconds,
    )
