"""Backoffice 테스트가 공유하는 픽스처.

Redis는 일회용 컨테이너로만 띄운다. Docker가 없으면 통합 테스트는 건너뛰지 않고
실패해야 한다 — 조용히 통과하면 rate limit이 깨진 채 배포된다.
"""

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from pydantic import SecretStr
from redis.asyncio import Redis
from testcontainers.community.redis import RedisContainer

from backoffice.auth.dependencies import get_rate_limiter
from backoffice.config import Settings, get_settings
from backoffice.main import create_app

from ._auth import ISSUANCE_CODE, SIGNING_KEY, AllowAll

REDIS_PORT = 6379


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    with RedisContainer("redis:7-alpine") as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(REDIS_PORT)
        yield f"redis://{host}:{port}/0"


@pytest_asyncio.fixture
async def redis_client(redis_url: str) -> AsyncIterator[Redis]:
    client = Redis.from_url(redis_url)
    try:
        await client.flushall()
        yield client
    finally:
        await client.aclose()


@pytest.fixture
def settings() -> Settings:
    """환경변수를 읽지 않고 명시값으로 만든 설정."""
    return Settings(
        issuance_code=SecretStr(ISSUANCE_CODE),
        jwt_signing_key=SecretStr(SIGNING_KEY),
        redis_url="redis://unused-in-contract-tests:6379/0",
    )


@pytest.fixture
def make_client(settings: Settings):
    """rate limiter를 갈아끼울 수 있는 TestClient 팩토리.

    context manager로 열지 않으므로 lifespan이 돌지 않고 Redis도 필요 없다.
    """

    def build(limiter: object | None = None) -> TestClient:
        application = create_app()
        application.dependency_overrides[get_settings] = lambda: settings
        application.dependency_overrides[get_rate_limiter] = lambda: (
            limiter if limiter is not None else AllowAll()
        )
        return TestClient(application)

    return build


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()
