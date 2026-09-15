"""명세 §4.1의 rolling window rate limit을 실제 Redis로 검증한다."""

import asyncio

import pytest
from redis.asyncio import Redis

from backoffice.auth.rate_limit import KEY_PREFIX, RedisRateLimiter
from common.errors import ApiError, ErrorCode

KEY = f"{KEY_PREFIX}:203.0.113.7"
OTHER_KEY = f"{KEY_PREFIX}:198.51.100.4"


async def test_requests_up_to_the_limit_are_allowed(redis_client: Redis) -> None:
    limiter = RedisRateLimiter(redis_client, limit=5, window_seconds=60)

    decisions = [await limiter.hit(KEY) for _ in range(5)]

    assert all(decision.allowed for decision in decisions)


async def test_the_request_past_the_limit_is_denied(redis_client: Redis) -> None:
    limiter = RedisRateLimiter(redis_client, limit=5, window_seconds=60)
    for _ in range(5):
        await limiter.hit(KEY)

    decision = await limiter.hit(KEY)

    assert not decision.allowed
    assert 1 <= decision.retry_after <= 60


async def test_denied_requests_are_not_recorded(redis_client: Redis) -> None:
    """거부까지 기록하면 공격이 계속되는 동안 창이 밀려 운영자도 복구되지 않는다."""
    limiter = RedisRateLimiter(redis_client, limit=2, window_seconds=60)
    for _ in range(2):
        await limiter.hit(KEY)

    for _ in range(3):
        await limiter.hit(KEY)

    assert await redis_client.zcard(KEY) == 2


async def test_the_window_rolls_forward(redis_client: Redis) -> None:
    limiter = RedisRateLimiter(redis_client, limit=1, window_seconds=1)
    assert (await limiter.hit(KEY)).allowed
    assert not (await limiter.hit(KEY)).allowed

    await asyncio.sleep(1.2)

    assert (await limiter.hit(KEY)).allowed


async def test_keys_are_counted_independently(redis_client: Redis) -> None:
    limiter = RedisRateLimiter(redis_client, limit=1, window_seconds=60)
    await limiter.hit(KEY)

    assert (await limiter.hit(OTHER_KEY)).allowed


async def test_the_key_expires_after_the_window(redis_client: Redis) -> None:
    limiter = RedisRateLimiter(redis_client, limit=5, window_seconds=60)

    await limiter.hit(KEY)

    assert 0 < await redis_client.ttl(KEY) <= 60


async def test_unreachable_redis_fails_closed() -> None:
    """한도를 확인할 수 없으면 발급을 막는다. 통과시키면 무제한 대입에 노출된다."""
    unreachable = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=1)
    limiter = RedisRateLimiter(unreachable, limit=5, window_seconds=60)

    try:
        with pytest.raises(ApiError) as caught:
            await limiter.hit(KEY)
    finally:
        await unreachable.aclose()

    assert caught.value.code == ErrorCode.INTERNAL_SERVER_ERROR
    assert caught.value.status_code == 500
