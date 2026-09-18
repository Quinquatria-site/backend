from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backoffice.api.router import api_router
from backoffice.config import get_settings
from common.app import create_api_app


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """설정을 기동 시점에 읽어 잘못된 인스턴스가 헬스체크를 통과하지 못하게 한다."""
    get_settings()
    yield


def create_app() -> FastAPI:
    return create_api_app(
        title="Quinquatria Backoffice API", router=api_router, lifespan=lifespan
    )


app = create_app()
