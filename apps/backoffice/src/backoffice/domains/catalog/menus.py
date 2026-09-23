"""메뉴 CRUD (명세 §5.5, §6)."""

from collections.abc import Sequence
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Query, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backoffice.auth.dependencies import ObjectStoreDep, SessionDep, SettingsDep
from backoffice.crud.images import image_keys, replace_image
from backoffice.crud.resources import POSTGRESQL_INTEGER_MAX, get_or_404, paginate
from backoffice.crud.translations import delete_translation, upsert_translations
from backoffice.domains.catalog.common import (
    detach_images,
    id_equals,
    lock_parent,
    no_content,
)
from backoffice.domains.catalog.schemas import (
    MenuCreate,
    MenuOut,
    MenuPatch,
    MenuTranslationOut,
    by_language,
)
from common.errors import ApiError, ErrorCode
from common.pagination import Page
from common.query import NoQuery, PageQuery
from common.types import ResourceId
from quinquatria_persistence.enums import ImageResourceType, LanguageCode
from quinquatria_persistence.models import Menu, MenuTranslation, Place

router = APIRouter(prefix="/menus")


def _out(menu: Menu, keys: dict[int, str]) -> MenuOut:
    return MenuOut(
        id=menu.id,
        place_id=menu.place_id,
        image_url=keys.get(menu.image_id),
        price=menu.price,
        translations=[
            MenuTranslationOut.model_validate(row)
            for row in by_language(menu.translations)
        ],
    )


async def _respond(session: AsyncSession, menu: Menu) -> MenuOut:
    await session.flush()
    return _out(menu, await image_keys(session, [menu.image_id]))


async def _lock_menu(session: AsyncSession, menu_id: int) -> Menu:
    """상위 장소를 먼저 `FOR KEY SHARE`로 잠근 뒤 메뉴를 `FOR UPDATE`로 읽는다.

    장소 삭제는 장소 → 메뉴 순서로 잠근다. 같은 순서를 따라야 교착이 없고,
    삭제가 모은 메뉴 이미지 목록과 실제로 지워지는 메뉴가 어긋나지 않는다.

    잠그기 전에는 `place_id`만 읽는다. 엔티티를 먼저 올리면 `FOR UPDATE`로
    다시 읽어도 identity map의 옛 값이 남아, 기다리는 사이 commit된 변경을 놓친다.
    """
    if menu_id > POSTGRESQL_INTEGER_MAX:
        raise ApiError(ErrorCode.RESOURCE_NOT_FOUND)
    place_id = await session.scalar(select(Menu.place_id).where(Menu.id == menu_id))
    if place_id is None:
        raise ApiError(ErrorCode.RESOURCE_NOT_FOUND)
    await lock_parent(session, Place, place_id)
    menu = await get_or_404(
        session, Menu, menu_id, selectinload(Menu.translations), for_update=True
    )
    if menu.place_id != place_id:
        # 잠금을 기다리는 사이 다른 장소로 옮겨졌다. 메뉴 행을 잡았으니 더는 바뀌지 않는다.
        await lock_parent(session, Place, menu.place_id)
    return menu


@router.post("", status_code=HTTPStatus.CREATED)
async def create_menu(
    body: MenuCreate,
    query: Annotated[NoQuery, Query()],
    session: SessionDep,
    store: ObjectStoreDep,
    settings: SettingsDep,
) -> MenuOut:
    await lock_parent(session, Place, body.place_id)
    image_id = await replace_image(
        session,
        store,
        current_image_id=None,
        object_key=body.image_url,
        resource_type=ImageResourceType.MENU_IMAGE,
        max_bytes=settings.max_image_bytes,
    )
    menu = Menu(
        place_id=body.place_id,
        image_id=image_id,
        price=body.price,
        translations=[
            MenuTranslation(**item.model_dump()) for item in body.translations
        ],
    )
    session.add(menu)
    return await _respond(session, menu)


class MenuQuery(PageQuery):
    place_id: ResourceId | None = None


@router.get("")
async def list_menus(
    query: Annotated[MenuQuery, Query()], session: SessionDep
) -> Page[MenuOut]:
    statement = (
        select(Menu)
        .options(selectinload(Menu.translations))
        .order_by(Menu.place_id, Menu.id)
    )
    if query.place_id is not None:
        statement = statement.where(id_equals(Menu.place_id, query.place_id))

    async def serialize(menus: Sequence[Menu]) -> list[MenuOut]:
        keys = await image_keys(session, (menu.image_id for menu in menus))
        return [_out(menu, keys) for menu in menus]

    return await paginate(session, statement, query, serialize)


@router.get("/{menu_id}")
async def get_menu(
    menu_id: ResourceId, query: Annotated[NoQuery, Query()], session: SessionDep
) -> MenuOut:
    menu = await get_or_404(session, Menu, menu_id, selectinload(Menu.translations))
    return await _respond(session, menu)


@router.patch("/{menu_id}")
async def update_menu(
    menu_id: ResourceId,
    body: MenuPatch,
    query: Annotated[NoQuery, Query()],
    session: SessionDep,
    store: ObjectStoreDep,
    settings: SettingsDep,
) -> MenuOut:
    menu = await _lock_menu(session, menu_id)
    changes = body.changes()
    if body.place_id is not None and body.place_id != menu.place_id:
        await lock_parent(session, Place, body.place_id)
    if "image_url" in changes:
        del changes["image_url"]
        menu.image_id = await replace_image(
            session,
            store,
            current_image_id=menu.image_id,
            object_key=body.image_url,
            resource_type=ImageResourceType.MENU_IMAGE,
            max_bytes=settings.max_image_bytes,
        )
    for name, value in changes.items():
        setattr(menu, name, value)
    if body.translations is not None:
        upsert_translations(menu.translations, body.translations, MenuTranslation)
    return await _respond(session, menu)


@router.delete("/{menu_id}", status_code=HTTPStatus.NO_CONTENT)
async def delete_menu(
    menu_id: ResourceId, query: Annotated[NoQuery, Query()], session: SessionDep
) -> Response:
    menu = await _lock_menu(session, menu_id)
    await detach_images(session, [menu.image_id])
    await session.execute(delete(Menu).where(Menu.id == menu.id))
    return no_content()


@router.delete(
    "/{menu_id}/translations/{language_code}", status_code=HTTPStatus.NO_CONTENT
)
async def delete_menu_translation(
    menu_id: ResourceId,
    language_code: LanguageCode,
    query: Annotated[NoQuery, Query()],
    session: SessionDep,
) -> Response:
    await delete_translation(
        session,
        owner=Menu,
        owner_id=menu_id,
        translation=MenuTranslation,
        owner_fk=MenuTranslation.menu_id,
        language_code=language_code,
    )
    return no_content()
