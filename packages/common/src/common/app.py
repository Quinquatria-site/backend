"""두 앱이 공유하는 FastAPI 애플리케이션 팩토리.

명세 §2.1에 따라 모든 API는 `/api/v1` 아래에 등록한다.
"""

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable, Sequence
from http import HTTPStatus

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Lifespan, Receive, Scope, Send

from common.handlers import register_exception_handlers

API_V1_PREFIX = "/api/v1"

HEALTHCHECK_PATH = "/healthcheck"
"""인프라 프로브용 경로. API 버전과 무관하게 고정하려고 `/api/v1` 밖에 둔다."""

HEALTHCHECK_TIMEOUT_SECONDS = 2.0

logger = logging.getLogger(__name__)

CORS_ALLOW_ORIGINS_ENV = "CORS_ALLOW_ORIGINS"
"""두 앱이 공유하는 설정이라 `DATABASE_URL`처럼 앱 prefix를 붙이지 않는다."""

type OriginsProvider = Callable[[], Sequence[str]]
type HealthCheck = Callable[[FastAPI], Awaitable[None]]


def cors_origins_from_env() -> list[str]:
    """쉼표로 구분한 허용 origin 목록을 읽는다. 없으면 CORS를 켜지 않는다."""
    raw = os.environ.get(CORS_ALLOW_ORIGINS_ENV, "")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


class _DeferredCORSMiddleware:
    """허용 origin을 첫 ASGI 호출(서버에서는 기동 시 lifespan) 때 한 번 읽어
    `CORSMiddleware`를 구성한다.

    미들웨어는 기동 전에 등록해야 하지만, 두 앱은 import와 팩토리 호출에서 설정을
    읽지 않는다. 등록과 설정 읽기를 이 래퍼가 분리한다.
    """

    def __init__(self, app: ASGIApp, *, origins: OriginsProvider) -> None:
        self._app = app
        self._origins = origins
        self._resolved: ASGIApp | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._resolved is None:
            origins = list(self._origins())
            self._resolved = (
                CORSMiddleware(
                    self._app,
                    allow_origins=origins,
                    allow_methods=["*"],
                    allow_headers=["*"],
                )
                if origins
                else self._app
            )
        await self._resolved(scope, receive, send)


def create_api_app(
    *,
    title: str,
    router: APIRouter | None = None,
    lifespan: Lifespan[FastAPI] | None = None,
    cors_origins: OriginsProvider | None = None,
    health_check: HealthCheck | None = None,
    health_check_timeout: float = HEALTHCHECK_TIMEOUT_SECONDS,
) -> FastAPI:
    """공통 오류 처리가 등록된 애플리케이션을 만든다.

    `router`를 넘기면 `/api/v1` 아래에 등록한다. `lifespan`은 연결 풀처럼
    기동·종료 시점에 열고 닫아야 하는 자원을 앱이 소유하게 해준다.
    `cors_origins`는 허용 origin을 돌려주는 함수이며 첫 ASGI 호출 때 한 번 불린다.
    인증은 `Authorization` 헤더라 쿠키 전송(credentials)은 켜지 않는다.
    `health_check`는 `GET /healthcheck`가 의존 자원을 확인하는 함수다.
    """
    application = FastAPI(title=title, lifespan=lifespan)
    if cors_origins is not None:
        application.add_middleware(_DeferredCORSMiddleware, origins=cors_origins)
    register_exception_handlers(application)
    if router is not None:
        application.include_router(router, prefix=API_V1_PREFIX)
    _register_healthcheck(application, health_check, health_check_timeout)
    return application


def _register_healthcheck(
    application: FastAPI, check: HealthCheck | None, timeout: float
) -> None:
    @application.get(HEALTHCHECK_PATH, include_in_schema=False)
    async def healthcheck(request: Request) -> JSONResponse:
        if check is not None:
            try:
                await asyncio.wait_for(check(request.app), timeout=timeout)
            except Exception as error:
                # 예외 문자열에 접속 정보가 실릴 수 있어 종류만 남긴다.
                logger.warning("healthcheck failed: %s", type(error).__name__)
                return JSONResponse(
                    {"status": "unavailable"},
                    status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                )
        return JSONResponse({"status": "ok"})
