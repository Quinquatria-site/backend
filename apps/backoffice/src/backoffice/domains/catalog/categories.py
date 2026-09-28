"""카테고리 CRUD (명세 §5.3, §6)."""

from collections.abc import Sequence
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Query, Response
from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backoffice.auth.dependencies import ObjectStoreDep, SessionDep, SettingsDep
from backoffice.crud.images import image_keys, replace_image
from backoffice.crud.resources import get_or_404, paginate
from backoffice.crud.translations import delete_translation, upsert_translations
from backoffice.domains.catalog.common import detach_images, no_content
from backoffice.domains.catalog.schemas import (
    CategoryCreate,
    CategoryOut,
    CategoryPatch,
    CategoryTranslationOut,
    by_language,
)
from common.errors import ApiError, ErrorCode, ErrorDetail
from common.pagination import Page
from common.query import NoQuery, PageQuery
from common.types import ResourceId
from quinquatria_persistence.enums import CategoryCode, ImageResourceType, LanguageCode
from quinquatria_persistence.models import Category, CategoryTranslation, Place

router = APIRouter(prefix="/categories")


def _out(category: Category, keys: dict[int, str]) -> CategoryOut:
    return CategoryOut(
        id=category.id,
        code=category.code,
        category_icon_uri=keys.get(category.image_id),
        translations=[
            CategoryTranslationOut.model_validate(row)
            for row in by_language(category.translations)
        ],
    )


async def _respond(session: AsyncSession, category: Category) -> CategoryOut:
    await session.flush()
    return _out(category, await image_keys(session, [category.image_id]))


@router.post("", status_code=HTTPStatus.CREATED)
async def create_category(
    body: CategoryCreate,
    query: Annotated[NoQuery, Query()],
    session: SessionDep,
    store: ObjectStoreDep,
    settings: SettingsDep,
) -> CategoryOut:
    image_id = await replace_image(
        session,
        store,
        current_image_id=None,
        object_key=body.category_icon_uri,
        resource_type=ImageResourceType.CATEGORY_ICON,
        max_bytes=settings.max_image_bytes,
    )
    category = Category(
        code=body.code,
        image_id=image_id,
        translations=[
            CategoryTranslation(**item.model_dump()) for item in body.translations
        ],
    )
    session.add(category)
    return await _respond(session, category)


@router.patch("/{category_id}")
async def update_category(
    category_id: ResourceId,
    body: CategoryPatch,
    query: Annotated[NoQuery, Query()],
    session: SessionDep,
    store: ObjectStoreDep,
    settings: SettingsDep,
) -> CategoryOut:
    category = await get_or_404(
        session,
        Category,
        category_id,
        selectinload(Category.translations),
        for_update=True,
    )
    changes = body.changes()
    if "category_icon_uri" in changes:
        category.image_id = await replace_image(
            session,
            store,
            current_image_id=category.image_id,
            object_key=body.category_icon_uri,
            resource_type=ImageResourceType.CATEGORY_ICON,
            max_bytes=settings.max_image_bytes,
        )
    if body.code is not None:
        category.code = body.code
    if body.translations is not None:
        upsert_translations(
            category.translations, body.translations, CategoryTranslation
        )
    return await _respond(session, category)


@router.delete("/{category_id}", status_code=HTTPStatus.NO_CONTENT)
async def delete_category(
    category_id: ResourceId, query: Annotated[NoQuery, Query()], session: SessionDep
) -> Response:
    """카테고리 행을 `FOR UPDATE`로 잠근 뒤 장소 유무를 본다.

    장소 생성·이동은 카테고리를 `FOR KEY SHARE`로 잠그므로, 확인과 삭제 사이에
    장소가 끼어들 수 없다.
    """
    category = await get_or_404(session, Category, category_id, for_update=True)
    has_places = await session.scalar(
        select(exists().where(Place.category_id == category.id))
    )
    if has_places:
        raise ApiError(
            ErrorCode.DELETE_CONFLICT,
            message="장소가 연결된 카테고리는 삭제할 수 없습니다.",
            details=[
                ErrorDetail(
                    field="category_id", reason="연결된 장소를 먼저 삭제해야 합니다."
                )
            ],
        )
    await detach_images(session, [category.image_id])
    await session.execute(delete(Category).where(Category.id == category.id))
    return no_content()


@router.delete(
    "/{category_id}/translations/{language_code}", status_code=HTTPStatus.NO_CONTENT
)
async def delete_category_translation(
    category_id: ResourceId,
    language_code: LanguageCode,
    query: Annotated[NoQuery, Query()],
    session: SessionDep,
) -> Response:
    await delete_translation(
        session,
        owner=Category,
        owner_id=category_id,
        translation=CategoryTranslation,
        owner_fk=CategoryTranslation.category_id,
        language_code=language_code,
    )
    return no_content()


class CategoryQuery(PageQuery):
    code: CategoryCode | None = None


@router.get("")
async def list_categories(
    query: Annotated[CategoryQuery, Query()], session: SessionDep
) -> Page[CategoryOut]:
    statement = (
        select(Category)
        .options(selectinload(Category.translations))
        .order_by(Category.id)
    )
    if query.code is not None:
        statement = statement.where(Category.code == query.code)

    async def serialize(categories: Sequence[Category]) -> list[CategoryOut]:
        keys = await image_keys(session, (row.image_id for row in categories))
        return [_out(row, keys) for row in categories]

    return await paginate(session, statement, query, serialize)


@router.get("/{category_id}")
async def get_category(
    category_id: ResourceId, query: Annotated[NoQuery, Query()], session: SessionDep
) -> CategoryOut:
    category = await get_or_404(
        session, Category, category_id, selectinload(Category.translations)
    )
    return await _respond(session, category)
