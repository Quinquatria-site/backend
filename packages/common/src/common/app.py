"""두 앱이 공유하는 FastAPI 애플리케이션 팩토리.

명세 §2.1에 따라 모든 API는 `/api/v1` 아래에 등록한다.
"""

from fastapi import APIRouter, FastAPI

from common.handlers import register_exception_handlers

API_V1_PREFIX = "/api/v1"


def create_api_app(*, title: str, router: APIRouter | None = None) -> FastAPI:
    """공통 오류 처리가 등록된 애플리케이션을 만든다.

    `router`를 넘기면 `/api/v1` 아래에 등록한다.
    """
    application = FastAPI(title=title)
    register_exception_handlers(application)
    if router is not None:
        application.include_router(router, prefix=API_V1_PREFIX)
    return application
