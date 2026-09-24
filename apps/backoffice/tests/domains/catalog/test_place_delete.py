"""장소와 번역 삭제 (명세 §5.2, §6)."""

from sqlalchemy import func, select

from quinquatria_persistence.enums import ImageStatus
from quinquatria_persistence.models import (
    Image,
    Menu,
    MenuTranslation,
    PlaceImage,
    PlaceTranslation,
)

from ._helpers import create_category, create_menu, create_place, upload


async def _count(database, column) -> int:
    async with database.session() as session:
        return await session.scalar(select(func.count(column)))


async def _status(database, key: str) -> ImageStatus:
    async with database.session() as session:
        return await session.scalar(select(Image.status).where(Image.s3_key == key))


async def test_delete_cascades_and_detaches_every_image(
    api, database, object_store
) -> None:
    category = await create_category(api)
    place_key = await upload(api, object_store, "PLACE_IMAGE")
    menu_key = await upload(api, object_store, "MENU_IMAGE")
    place = await create_place(api, category["id"], place_image_uri=[place_key])
    await create_menu(api, place["id"], image_url=menu_key)
    await create_menu(api, place["id"])
    kept = await create_menu(api, (await create_place(api, category["id"]))["id"])

    response = await api.delete(f"/api/v1/places/{place['id']}")

    assert response.status_code == 204
    assert response.content == b""
    assert "content-type" not in response.headers
    assert (await api.get(f"/api/v1/places/{place['id']}")).status_code == 404
    assert (await api.get("/api/v1/menus")).json()["items"] == [kept]
    assert await _count(database, PlaceTranslation.id) == 1
    assert await _count(database, MenuTranslation.id) == 1
    assert await _count(database, Menu.id) == 1
    assert await _count(database, PlaceImage.id) == 0
    assert await _status(database, place_key) is ImageStatus.DETACHED
    assert await _status(database, menu_key) is ImageStatus.DETACHED


async def test_delete_missing_place_is_404(api) -> None:
    response = await api.delete("/api/v1/places/999")

    assert response.status_code == 404


async def test_translation_delete_rules(api) -> None:
    category = await create_category(api)
    place = await create_place(
        api,
        category["id"],
        translations=[
            {"language_code": "KO", "name": "주점", "host_college": "통번역대학"},
            {"language_code": "CHN", "name": "酒吧", "host_college": "口译"},
        ],
    )
    path = f"/api/v1/places/{place['id']}/translations"

    ko = await api.delete(f"{path}/KO")
    chn = await api.delete(f"{path}/CHN")
    chn_again = await api.delete(f"{path}/CHN")
    missing_place = await api.delete("/api/v1/places/999/translations/EN")

    assert (ko.status_code, ko.json()["code"]) == (409, "DELETE_CONFLICT")
    assert (chn.status_code, chn.content) == (204, b"")
    assert "content-type" not in chn.headers
    assert chn_again.status_code == 404
    assert missing_place.status_code == 404
    body = (await api.get(f"/api/v1/places/{place['id']}")).json()
    assert [row["language_code"] for row in body["translations"]] == ["KO"]
