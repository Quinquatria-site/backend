"""공연 관리 라우트. `api/router.py`가 보호 라우터에 등록한다.

`PUT /performances/reorder`는 정적 경로이므로 `{performance_id}` 경로보다
먼저 등록한다 (명세 §5.1).
"""

from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Query, Response

from backoffice.auth.dependencies import ObjectStoreDep, SessionDep, SettingsDep
from backoffice.domains.performances import service
from backoffice.domains.performances.schemas import (
    LiveUpdate,
    PerformanceCreate,
    PerformanceListQuery,
    PerformanceOut,
    PerformancePatch,
    ReorderRequest,
)
from common.pagination import Page
from common.query import NoQuery
from common.types import ResourceId
from quinquatria_persistence.enums import LanguageCode

router = APIRouter(tags=["performances"])


@router.get("/performances")
async def list_performances(
    query: Annotated[PerformanceListQuery, Query()], session: SessionDep
) -> Page[PerformanceOut]:
    return await service.list_performances(session, query)


@router.put(
    "/performances/reorder",
    status_code=HTTPStatus.NO_CONTENT,
    response_class=Response,
)
async def reorder_performances(
    payload: ReorderRequest, session: SessionDep
) -> Response:
    await service.reorder(session, payload.date, payload.order)
    return Response(status_code=HTTPStatus.NO_CONTENT)


@router.post("/performances", status_code=HTTPStatus.CREATED)
async def create_performance(
    payload: PerformanceCreate,
    session: SessionDep,
    store: ObjectStoreDep,
    settings: SettingsDep,
) -> PerformanceOut:
    performance = await service.create_performance(
        session, store, payload, max_image_bytes=settings.max_image_bytes
    )
    return await service.serialize_one(session, performance)


@router.get("/performances/{performance_id}")
async def get_performance(
    performance_id: ResourceId,
    query: Annotated[NoQuery, Query()],
    session: SessionDep,
) -> PerformanceOut:
    performance = await service.get_performance(session, performance_id)
    return await service.serialize_one(session, performance)


@router.patch("/performances/{performance_id}")
async def update_performance(
    performance_id: ResourceId,
    payload: PerformancePatch,
    session: SessionDep,
    store: ObjectStoreDep,
    settings: SettingsDep,
) -> PerformanceOut:
    performance = await service.update_performance(
        session,
        store,
        performance_id,
        payload,
        max_image_bytes=settings.max_image_bytes,
    )
    return await service.serialize_one(session, performance)


@router.put("/performances/{performance_id}/live")
async def set_performance_live(
    performance_id: ResourceId, payload: LiveUpdate, session: SessionDep
) -> PerformanceOut:
    performance = await service.set_live(session, performance_id, payload.is_live)
    return await service.serialize_one(session, performance)


@router.delete(
    "/performances/{performance_id}",
    status_code=HTTPStatus.NO_CONTENT,
    response_class=Response,
)
async def delete_performance(
    performance_id: ResourceId,
    session: SessionDep,
    store: ObjectStoreDep,
    settings: SettingsDep,
) -> Response:
    await service.delete_performance(
        session, store, performance_id, max_image_bytes=settings.max_image_bytes
    )
    return Response(status_code=HTTPStatus.NO_CONTENT)


@router.delete(
    "/performances/{performance_id}/translations/{language_code}",
    status_code=HTTPStatus.NO_CONTENT,
    response_class=Response,
)
async def delete_performance_translation(
    performance_id: ResourceId, language_code: LanguageCode, session: SessionDep
) -> Response:
    await service.delete_translation(session, performance_id, language_code)
    return Response(status_code=HTTPStatus.NO_CONTENT)
