"""인증 테스트가 공유하는 값과 대역(test double).

실제 Redis 없이도 라우트 계약을 검증할 수 있도록 `RateLimiter` 프로토콜을
만족하는 최소 구현을 둔다.
"""

from backoffice.auth.rate_limit import Decision

ISSUANCE_CODE = "test-issuance-code"
SIGNING_KEY = "k" * 32
OTHER_SIGNING_KEY = "z" * 32


class AllowAll:
    """한도에 걸리지 않는 경로를 시험할 때 쓴다."""

    async def hit(self, key: str) -> Decision:
        return Decision(allowed=True, retry_after=0)


class DenyAll:
    """한도 초과 응답을 시험할 때 쓴다."""

    def __init__(self, retry_after: int = 42) -> None:
        self._retry_after = retry_after

    async def hit(self, key: str) -> Decision:
        return Decision(allowed=False, retry_after=self._retry_after)
