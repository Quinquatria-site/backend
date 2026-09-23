from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backoffice.api.router import api_router
from backoffice.config import get_settings
from backoffice.images.masking import suppress_sdk_signature_logs
from common.app import cors_origins_from_env, create_api_app
from quinquatria_persistence import Database


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """DB 엔진을 앱이 소유한다.

    설정은 여기서 처음 읽는다. import 시점에 읽으면 환경변수 없이는 테스트조차
    수집할 수 없다. 기동 시점에는 읽으므로 잘못된 인스턴스는 헬스체크를 통과하지
    못한다.
    """
    application.state.database = Database(get_settings().database_url)
    try:
        yield
    finally:
        await application.state.database.dispose()


def create_app() -> FastAPI:
    # 설정을 읽기 전에 건다. 기동 중 실패해도 서명이 남을 창이 없어야 한다.
    suppress_sdk_signature_logs()
    return create_api_app(
        title="Quinquatria Backoffice API",
        router=api_router,
        lifespan=lifespan,
        cors_origins=cors_origins_from_env,
    )


app = create_app()
