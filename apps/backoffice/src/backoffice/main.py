from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backoffice.api.router import api_router
from backoffice.config import get_settings
from common.app import create_api_app
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
    return create_api_app(
        title="Quinquatria Backoffice API", router=api_router, lifespan=lifespan
    )


app = create_app()
