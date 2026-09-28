"""상위 리소스 삭제와 하위 리소스 쓰기가 겹칠 때의 계약 (명세 §6).

확인과 쓰기 사이에 다른 transaction이 끼어들면 FK 위반이 500으로 새어
나간다. 잠금으로 직렬화해 뒤에 온 요청이 409나 404로 판정되어야 한다.
"""

import asyncio
from datetime import UTC, datetime

from sqlalchemy import delete, select, update

from quinquatria_persistence.enums import ImageStatus
from quinquatria_persistence.models import Category, Image, Menu, Place

from ._helpers import (
    create_category,
    create_menu,
    create_place,
    menu_body,
    place_body,
    upload,
)

BLOCKED_FOR = 0.5
"""뒤의 요청이 잠금에 막혀 있음을 확인하는 시간."""


async def test_category_delete_waits_for_a_pending_place(api, database) -> None:
    category = await create_category(api)
    at = datetime(2026, 10, 6, 1, tzinfo=UTC)

    async with database.transaction() as pending:
        pending.add(
            Place(
                category_id=category["id"],
                category_sequence=1,
                x=0.0,
                y=0.0,
                start_hour=at,
                end_hour=at,
            )
        )
        await pending.flush()
        deleting = asyncio.create_task(
            api.delete(f"/api/v1/categories/{category['id']}")
        )
        await asyncio.sleep(BLOCKED_FOR)
        assert not deleting.done()

    response = await deleting
    assert response.status_code == 409
    assert response.json()["code"] == "DELETE_CONFLICT"


async def test_place_create_during_category_delete_is_404(api, database) -> None:
    category = await create_category(api)

    async with database.transaction() as deleting:
        await deleting.execute(delete(Category).where(Category.id == category["id"]))
        creating = asyncio.create_task(
            api.post("/api/v1/places", json=place_body(category["id"]))
        )
        await asyncio.sleep(BLOCKED_FOR)
        assert not creating.done()

    response = await creating
    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"


async def test_menu_create_during_place_delete_is_404(api, database) -> None:
    category = await create_category(api)
    place = await create_place(api, category["id"])

    async with database.transaction() as deleting:
        await deleting.execute(delete(Place).where(Place.id == place["id"]))
        creating = asyncio.create_task(
            api.post("/api/v1/menus", json=menu_body(place["id"]))
        )
        await asyncio.sleep(BLOCKED_FOR)
        assert not creating.done()

    response = await creating
    assert response.status_code == 404


async def test_place_create_racing_for_the_same_sequence_is_422(api, database) -> None:
    """먼저 쓴 transaction이 commit되면 unique 제약 위반이 500이 아니라 422다."""
    category = await create_category(api)
    at = datetime(2026, 10, 6, 1, tzinfo=UTC)

    async with database.transaction() as pending:
        pending.add(
            Place(
                category_id=category["id"],
                category_sequence=5,
                x=0.0,
                y=0.0,
                start_hour=at,
                end_hour=at,
            )
        )
        await pending.flush()
        creating = asyncio.create_task(
            api.post(
                "/api/v1/places",
                json=place_body(category["id"], category_sequence=5),
            )
        )
        await asyncio.sleep(BLOCKED_FOR)
        assert not creating.done()

    response = await creating
    assert response.status_code == 422
    assert response.json()["details"][0]["field"] == "category_sequence"


async def _image_id(session, key: str) -> int:
    return await session.scalar(select(Image.id).where(Image.s3_key == key))


async def test_menu_delete_detaches_the_image_committed_while_waiting(
    api, database, object_store
) -> None:
    """메뉴 잠금을 기다리는 사이 교체된 이미지까지 해제해야 정리 대상에 오른다."""
    category = await create_category(api)
    place = await create_place(api, category["id"])
    old_key = await upload(api, object_store, "MENU_IMAGE")
    new_key = await upload(api, object_store, "MENU_IMAGE")
    menu = await create_menu(api, place["id"], image_url=old_key)

    async with database.transaction() as replacing:
        old_id = await _image_id(replacing, old_key)
        new_id = await _image_id(replacing, new_key)
        await replacing.execute(
            update(Image)
            .where(Image.id == old_id)
            .values(status=ImageStatus.DETACHED, detached_at=datetime.now(UTC))
        )
        await replacing.execute(
            update(Image).where(Image.id == new_id).values(status=ImageStatus.ATTACHED)
        )
        await replacing.execute(
            update(Menu).where(Menu.id == menu["id"]).values(image_id=new_id)
        )
        deleting = asyncio.create_task(api.delete(f"/api/v1/menus/{menu['id']}"))
        await asyncio.sleep(BLOCKED_FOR)
        assert not deleting.done()

    response = await deleting
    assert response.status_code == 204
    async with database.session() as session:
        status = await session.scalar(select(Image.status).where(Image.id == new_id))
    assert status is ImageStatus.DETACHED


async def test_menu_patch_sees_the_place_committed_while_waiting(api, database) -> None:
    category = await create_category(api)
    before = await create_place(api, category["id"])
    after = await create_place(api, category["id"])
    menu = await create_menu(api, before["id"])

    async with database.transaction() as moving:
        await moving.execute(
            update(Menu).where(Menu.id == menu["id"]).values(place_id=after["id"])
        )
        patching = asyncio.create_task(
            api.patch(f"/api/v1/menus/{menu['id']}", json={"price": 1})
        )
        await asyncio.sleep(BLOCKED_FOR)
        assert not patching.done()

    response = await patching
    assert response.status_code == 200, response.text
    assert response.json()["place_id"] == after["id"]
