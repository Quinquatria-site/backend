from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from backoffice.api.router import api_router
from backoffice.config import get_settings
from common.app import create_api_app


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Redis 연결 풀을 앱이 소유한다.

    설정은 여기서 처음 읽는다. import 시점에 읽으면 환경변수 없이는 테스트조차
    수집할 수 없다.
    """
    application.state.redis = Redis.from_url(get_settings().redis_url)
    try:
        yield
    finally:
        await application.state.redis.aclose()


def create_app() -> FastAPI:
    return create_api_app(
        title="Quinquatria Backoffice API", router=api_router, lifespan=lifespan
    )


app = create_app()
