"""요청 언어로 평탄화한 공연 목록과 상세 조회."""

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import Boolean, Date, Integer, Select, Text, and_, column, select, table

from common.errors import ApiError, ErrorCode, ErrorResponse
from common.pagination import Page
from common.query import LanguageQuery
from common.types import ResourceId
from customer.api.dependencies import ReadSession
from customer.api.queries import is_storable_id, paginate
from customer.api.schemas.performance import PerformanceListQuery, PerformanceResponse
from quinquatria_persistence import Performance, PerformanceTranslation

# 실제 DB가 API 명세의 date/seq/is_live 스키마로 전환되기 전까지 사용하는 임시 테이블 정의다.
_PERFORMANCE = table(
    "performance",
    column("id", Integer()),
    column("type", Performance.__table__.c.type.type),
    column("image_uri", Text()),
    column("date", Date()),
    column("seq", Integer()),
    column("is_live", Boolean()),
)
_PERFORMANCE_TRANSLATION = table(
    "performance_translation",
    column("performance_id", Integer()),
    column("language_code", PerformanceTranslation.__table__.c.language_code.type),
    column("title", Text()),
    column("description", Text()),
)

router = APIRouter(
    tags=["performances"],
    responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)


def _select_performances() -> Select:
    return select(
        _PERFORMANCE.c.id,
        _PERFORMANCE.c.type,
        _PERFORMANCE.c.image_uri,
        _PERFORMANCE.c.date,
        _PERFORMANCE.c.seq,
        _PERFORMANCE.c.is_live,
        _PERFORMANCE_TRANSLATION.c.language_code,
        _PERFORMANCE_TRANSLATION.c.title,
        _PERFORMANCE_TRANSLATION.c.description,
    )


@router.get("/performances")
async def list_performances(
    query: Annotated[PerformanceListQuery, Query()], session: ReadSession
) -> Page[PerformanceResponse]:
    statement = (
        _select_performances()
        .join(
            _PERFORMANCE_TRANSLATION,
            _PERFORMANCE_TRANSLATION.c.performance_id == _PERFORMANCE.c.id,
        )
        .where(_PERFORMANCE_TRANSLATION.c.language_code == query.language_code.value)
        .order_by(_PERFORMANCE.c.date, _PERFORMANCE.c.seq, _PERFORMANCE.c.id)
    )
    if query.type is not None:
        statement = statement.where(_PERFORMANCE.c.type == query.type.value)
    if query.date is not None:
        statement = statement.where(_PERFORMANCE.c.date == query.date)
    return await paginate(session, statement, query, PerformanceResponse)


@router.get(
    "/performances/{performance_id}",
    responses={404: {"model": ErrorResponse}},
)
async def get_performance(
    performance_id: ResourceId,
    query: Annotated[LanguageQuery, Query()],
    session: ReadSession,
) -> PerformanceResponse:
    if not is_storable_id(performance_id):
        raise ApiError(ErrorCode.RESOURCE_NOT_FOUND)

    result = await session.execute(
        _select_performances()
        .outerjoin(
            _PERFORMANCE_TRANSLATION,
            and_(
                _PERFORMANCE_TRANSLATION.c.performance_id == _PERFORMANCE.c.id,
                _PERFORMANCE_TRANSLATION.c.language_code == query.language_code.value,
            ),
        )
        .where(_PERFORMANCE.c.id == performance_id)
    )
    performance = result.mappings().one_or_none()
    if performance is None:
        raise ApiError(ErrorCode.RESOURCE_NOT_FOUND)
    if performance["language_code"] is None:
        raise ApiError(ErrorCode.TRANSLATION_NOT_FOUND)
    return PerformanceResponse.model_validate(performance)
