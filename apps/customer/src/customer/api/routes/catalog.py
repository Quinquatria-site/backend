"""요청 언어로 평탄화한 카테고리·장소·메뉴 조회."""

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import Select, and_, func, select
from sqlalchemy.dialects.postgresql import aggregate_order_by

from common.errors import ApiError, ErrorCode, ErrorResponse
from common.pagination import Page
from common.query import LanguageQuery, ListQuery
from common.types import ResourceId
from customer.api.dependencies import ReadSession
from customer.api.queries import is_storable_id, paginate
from customer.api.schemas.catalog import (
    CategoryResponse,
    MenuResponse,
    PlaceDetailResponse,
    PlaceListQuery,
    PlaceResponse,
)
from quinquatria_persistence import (
    Category,
    CategoryTranslation,
    Image,
    Menu,
    MenuTranslation,
    Place,
    PlaceImage,
    PlaceTranslation,
)

router = APIRouter(
    tags=["catalog"],
    responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)


def _select_places() -> Select:
    # 이미지가 없는 장소는 집계 행이 없어 외부 조인 결과가 NULL이 된다.
    # 기존 `place_image_uri` 배열이 비어 있을 수 없던 계약과 같다.
    images = (
        select(
            PlaceImage.place_id,
            func.array_agg(aggregate_order_by(Image.s3_key, PlaceImage.seq)).label(
                "place_image_uri"
            ),
        )
        .join(Image, Image.id == PlaceImage.image_id)
        .group_by(PlaceImage.place_id)
        .subquery("place_images")
    )
    return select(
        Place.id,
        Place.category_id,
        Place.category_sequence,
        Place.x,
        Place.y,
        Place.start_hour,
        Place.end_hour,
        images.c.place_image_uri,
        PlaceTranslation.language_code,
        PlaceTranslation.name,
        PlaceTranslation.host_college,
        PlaceTranslation.description,
    ).select_from(Place.__table__.outerjoin(images, images.c.place_id == Place.id))


@router.get("/categories")
async def list_categories(
    query: Annotated[ListQuery, Query()], session: ReadSession
) -> Page[CategoryResponse]:
    statement = (
        select(
            Category.id,
            Category.code,
            Image.s3_key.label("category_icon_uri"),
            CategoryTranslation.language_code,
            CategoryTranslation.name,
        )
        .select_from(Category)
        .outerjoin(Image, Image.id == Category.image_id)
        .join(CategoryTranslation, CategoryTranslation.category_id == Category.id)
        .where(CategoryTranslation.language_code == query.language_code.value)
        .order_by(Category.id)
    )
    return await paginate(session, statement, query, CategoryResponse)


@router.get("/places")
async def list_places(
    query: Annotated[PlaceListQuery, Query()], session: ReadSession
) -> Page[PlaceResponse]:
    if query.category_id is not None and not is_storable_id(query.category_id):
        return Page(items=[], page=query.page, size=query.size, total=0)

    statement = (
        _select_places()
        .join(PlaceTranslation, PlaceTranslation.place_id == Place.id)
        .where(PlaceTranslation.language_code == query.language_code.value)
        .order_by(Place.category_id, Place.category_sequence, Place.id)
    )
    if query.category_id is not None:
        statement = statement.where(Place.category_id == query.category_id)
    return await paginate(session, statement, query, PlaceResponse)


@router.get("/places/{place_id}", responses={404: {"model": ErrorResponse}})
async def get_place(
    place_id: ResourceId,
    query: Annotated[LanguageQuery, Query()],
    session: ReadSession,
) -> PlaceDetailResponse:
    if not is_storable_id(place_id):
        raise ApiError(ErrorCode.RESOURCE_NOT_FOUND)

    result = await session.execute(
        _select_places()
        .outerjoin(
            PlaceTranslation,
            and_(
                PlaceTranslation.place_id == Place.id,
                PlaceTranslation.language_code == query.language_code.value,
            ),
        )
        .where(Place.id == place_id)
    )
    place = result.mappings().one_or_none()
    if place is None:
        raise ApiError(ErrorCode.RESOURCE_NOT_FOUND)
    if place["language_code"] is None:
        raise ApiError(ErrorCode.TRANSLATION_NOT_FOUND)

    menus = await session.execute(
        select(
            Menu.id,
            Menu.place_id,
            Image.s3_key.label("image_url"),
            Menu.price,
            MenuTranslation.language_code,
            MenuTranslation.name,
            MenuTranslation.description,
        )
        .select_from(Menu)
        .outerjoin(Image, Image.id == Menu.image_id)
        .join(MenuTranslation, MenuTranslation.menu_id == Menu.id)
        .where(
            Menu.place_id == place_id,
            MenuTranslation.language_code == query.language_code.value,
        )
        .order_by(Menu.id)
    )
    return PlaceDetailResponse(
        **place, menus=[MenuResponse.model_validate(row) for row in menus.mappings()]
    )
