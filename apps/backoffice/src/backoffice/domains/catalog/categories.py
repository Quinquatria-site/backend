"""카테고리 조회·수정 (명세 §5.3).

카테고리는 migration이 넣는 고정 목록이라 생성·삭제 경로를 두지 않는다.
"""

from collections.abc import Sequence
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backoffice.auth.dependencies import ObjectStoreDep, SessionDep, SettingsDep
from backoffice.crud.images import image_keys, replace_image
from backoffice.crud.resources import get_or_404, paginate
from backoffice.crud.translations import delete_translation, upsert_translations
from backoffice.domains.catalog.common import no_content
from backoffice.domains.catalog.schemas import (
    CategoryOut,
    CategoryPatch,
    CategoryTranslationOut,
    by_language,
)
from backoffice.revalidation.events import RevalidationTag, mark_changed
from common.pagination import Page
from common.query import NoQuery, PageQuery
from common.types import ResourceId
from quinquatria_persistence.enums import CategoryCode, ImageResourceType, LanguageCode
from quinquatria_persistence.models import Category, CategoryTranslation

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
    if body.translations is not None:
        upsert_translations(
            category.translations, body.translations, CategoryTranslation
        )
    result = await _respond(session, category)
    mark_changed(session, RevalidationTag.CATEGORIES)
    return result


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
    mark_changed(session, RevalidationTag.CATEGORIES)
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
