"""요청 언어로 평탄화한 분실물 조회."""

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import Select, and_, select

from common.errors import ApiError, ErrorCode, ErrorResponse
from common.pagination import Page
from common.query import LanguageQuery
from common.types import ResourceId
from customer.api.dependencies import ReadSession
from customer.api.queries import is_storable_id, paginate
from customer.api.schemas.lost_items import LostItemListQuery, LostItemResponse
from quinquatria_persistence import Image, LostItem, LostItemTranslation

router = APIRouter(
    tags=["lost-items"],
    responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)


def _select_lost_items() -> Select:
    return (
        select(
            LostItem.id,
            Image.s3_key.label("image_url"),
            LostItem.is_returned,
            LostItem.created_at,
            LostItemTranslation.language_code,
            LostItemTranslation.title,
            LostItemTranslation.description,
            LostItemTranslation.found_location,
        )
        .select_from(LostItem)
        .outerjoin(Image, Image.id == LostItem.image_id)
    )


@router.get("/lost-items")
async def list_lost_items(
    query: Annotated[LostItemListQuery, Query()], session: ReadSession
) -> Page[LostItemResponse]:
    statement = (
        _select_lost_items()
        .join(
            LostItemTranslation,
            LostItemTranslation.lost_item_id == LostItem.id,
        )
        .where(LostItemTranslation.language_code == query.language_code.value)
        .order_by(LostItem.created_at.desc(), LostItem.id.desc())
    )
    if query.is_returned is not None:
        statement = statement.where(LostItem.is_returned == query.is_returned)
    return await paginate(session, statement, query, LostItemResponse)


@router.get("/lost-items/{lost_item_id}", responses={404: {"model": ErrorResponse}})
async def get_lost_item(
    lost_item_id: ResourceId,
    query: Annotated[LanguageQuery, Query()],
    session: ReadSession,
) -> LostItemResponse:
    if not is_storable_id(lost_item_id):
        raise ApiError(ErrorCode.RESOURCE_NOT_FOUND)

    result = await session.execute(
        _select_lost_items()
        .outerjoin(
            LostItemTranslation,
            and_(
                LostItemTranslation.lost_item_id == LostItem.id,
                LostItemTranslation.language_code == query.language_code.value,
            ),
        )
        .where(LostItem.id == lost_item_id)
    )
    lost_item = result.mappings().one_or_none()
    if lost_item is None:
        raise ApiError(ErrorCode.RESOURCE_NOT_FOUND)
    if lost_item["language_code"] is None:
        raise ApiError(ErrorCode.TRANSLATION_NOT_FOUND)
    return LostItemResponse.model_validate(lost_item)
