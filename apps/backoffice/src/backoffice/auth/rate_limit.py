"""명세 §4.1의 토큰 발급 rate limit.

고정 윈도우(INCR + EXPIRE)는 경계에서 한도의 두 배까지 새므로 sliding window
log를 쓴다. 시각은 앱이 아니라 Redis의 TIME에서 읽어 인스턴스 간 시계 드리프트를
없앤다. 읽기·정리·기록을 Lua 한 번에 묶어 동시 요청이 한도를 넘지 못하게 한다.
"""

from typing import NamedTuple, Protocol
from uuid import uuid4

from redis.asyncio import Redis
from redis.exceptions import RedisError

from common.errors import ApiError, ErrorCode

KEY_PREFIX = "ratelimit:auth-token"

_SCRIPT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local member = ARGV[3]

local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000

redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local used = redis.call('ZCARD', key)

if used >= limit then
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local retry_after = math.ceil(tonumber(oldest[2]) + window - now)
    if retry_after < 1 then
        retry_after = 1
    end
    return {0, retry_after}
end

redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, window)
return {1, 0}
"""


class Decision(NamedTuple):
    """한 번의 요청에 대한 판정. `retry_after`는 거부일 때만 의미가 있다."""

    allowed: bool
    retry_after: int


class RateLimiter(Protocol):
    async def hit(self, key: str) -> Decision: ...


class RedisRateLimiter:
    """Redis sorted set에 발급 시각을 쌓는 sliding window log."""

    def __init__(self, redis: Redis, *, limit: int, window_seconds: int) -> None:
        self._script = redis.register_script(_SCRIPT)
        self._limit = limit
        self._window_seconds = window_seconds

    async def hit(self, key: str) -> Decision:
        try:
            allowed, retry_after = await self._script(
                keys=[key],
                args=[self._limit, self._window_seconds, str(uuid4())],
            )
        except (RedisError, OSError) as error:
            # 한도를 확인할 수 없으면 통과시키지 않는다. 발급 코드가 무제한
            # 대입에 노출되는 것보다 발급이 멈추는 편이 낫다.
            raise ApiError(ErrorCode.INTERNAL_SERVER_ERROR) from error

        return Decision(allowed=bool(allowed), retry_after=int(retry_after))
