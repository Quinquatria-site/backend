"""명세 §5.5 Menu CRUD 계약."""

import pytest
from sqlalchemy import select

from quinquatria_persistence.enums import ImageStatus
from quinquatria_persistence.models import Image

from ._helpers import create_category, create_menu, create_place, menu_body, upload


@pytest.fixture
async def place(api) -> dict:
    category = await create_category(api)
    return await create_place(api, category["id"])


async def _status(database, key: str) -> ImageStatus:
    async with database.session() as session:
        return await session.scalar(select(Image.status).where(Image.s3_key == key))


async def test_create_returns_201_with_all_translations(api, place) -> None:
    response = await api.post(
        "/api/v1/menus",
        json=menu_body(
            place["id"],
            translations=[
                {"language_code": "KO", "name": "떡볶이", "description": "매움"},
                {"language_code": "CHN", "name": "炒年糕"},
            ],
        ),
    )

    assert response.status_code == 201
    body = response.json()
    assert body == {
        "id": body["id"],
        "place_id": place["id"],
        "image_url": None,
        "price": 5000,
        "translations": [
            {
                "id": body["translations"][0]["id"],
                "menu_id": body["id"],
                "language_code": "CHN",
                "name": "炒年糕",
                "description": "",
            },
            {
                "id": body["translations"][1]["id"],
                "menu_id": body["id"],
                "language_code": "KO",
                "name": "떡볶이",
                "description": "매움",
            },
        ],
    }
    assert (await api.get(f"/api/v1/menus/{body['id']}")).json() == body


async def test_create_with_missing_place_is_404(api) -> None:
    response = await api.post("/api/v1/menus", json=menu_body(999))

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"


async def test_zero_price_is_allowed(api, place) -> None:
    menu = await create_menu(api, place["id"], price=0)

    assert menu["price"] == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"price": -1},
        {"price": 1.5},
        {"price": "5000"},
        {"price": 2_147_483_648},
        {"place_id": True},
        {"translations": []},
        {"translations": [{"language_code": "EN", "name": "x"}]},
    ],
)
async def test_invalid_create_body_is_422(api, place, overrides) -> None:
    response = await api.post("/api/v1/menus", json=menu_body(place["id"], **overrides))

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_get_rejects_query_parameters(api, place) -> None:
    menu = await create_menu(api, place["id"])

    response = await api.get(f"/api/v1/menus/{menu['id']}", params={"place_id": 1})

    assert response.status_code == 422


async def test_list_filters_by_place_in_place_then_id_order(api, place) -> None:
    other = await create_place(api, place["category_id"])
    b = await create_menu(api, other["id"])
    a1 = await create_menu(api, place["id"])
    a2 = await create_menu(api, place["id"])

    everything = await api.get("/api/v1/menus")
    filtered = await api.get("/api/v1/menus", params={"place_id": place["id"]})

    assert everything.json()["items"] == [a1, a2, b]
    assert filtered.json() == {"items": [a1, a2], "page": 1, "size": 20, "total": 2}


async def test_list_with_out_of_range_place_is_empty(api, place) -> None:
    await create_menu(api, place["id"])

    response = await api.get("/api/v1/menus", params={"place_id": 2_147_483_648})

    assert response.status_code == 200
    assert response.json() == {"items": [], "page": 1, "size": 20, "total": 0}


async def test_patch_moves_and_upserts(api, place) -> None:
    other = await create_place(api, place["category_id"])
    menu = await create_menu(api, place["id"])

    response = await api.patch(
        f"/api/v1/menus/{menu['id']}",
        json={
            "place_id": other["id"],
            "price": 7000,
            "translations": [{"language_code": "KO", "name": "순대"}],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["place_id"], body["price"]) == (other["id"], 7000)
    assert body["translations"] == [
        menu["translations"][0] | {"name": "순대", "description": ""}
    ]


async def test_patch_to_missing_place_is_404(api, place) -> None:
    menu = await create_menu(api, place["id"])

    response = await api.patch(f"/api/v1/menus/{menu['id']}", json={"place_id": 999})

    assert response.status_code == 404


async def test_patch_rejects_null_price(api, place) -> None:
    menu = await create_menu(api, place["id"])

    response = await api.patch(f"/api/v1/menus/{menu['id']}", json={"price": None})

    assert response.status_code == 422


async def test_image_is_attached_replaced_and_detached(
    api, database, place, object_store
) -> None:
    old = await upload(api, object_store, "MENU_IMAGE")
    new = await upload(api, object_store, "MENU_IMAGE")
    menu = await create_menu(api, place["id"], image_url=old)
    assert menu["image_url"] == old

    replaced = await api.patch(f"/api/v1/menus/{menu['id']}", json={"image_url": new})
    cleared = await api.patch(f"/api/v1/menus/{menu['id']}", json={"image_url": None})

    assert replaced.json()["image_url"] == new
    assert cleared.json()["image_url"] is None
    assert await _status(database, old) is ImageStatus.DETACHED
    assert await _status(database, new) is ImageStatus.DETACHED


async def test_category_icon_key_is_not_a_menu_image(api, place, object_store) -> None:
    key = await upload(api, object_store, "CATEGORY_ICON")

    response = await api.post(
        "/api/v1/menus", json=menu_body(place["id"], image_url=key)
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_IMAGE"


async def test_image_attached_elsewhere_is_conflict(api, place, object_store) -> None:
    key = await upload(api, object_store, "MENU_IMAGE")
    await create_menu(api, place["id"], image_url=key)

    response = await api.post(
        "/api/v1/menus", json=menu_body(place["id"], image_url=key)
    )

    assert response.status_code == 409
    assert response.json()["code"] == "IMAGE_ALREADY_ATTACHED"


async def test_delete_detaches_image_and_cascades(
    api, database, place, object_store
) -> None:
    key = await upload(api, object_store, "MENU_IMAGE")
    menu = await create_menu(api, place["id"], image_url=key)

    response = await api.delete(f"/api/v1/menus/{menu['id']}")

    assert response.status_code == 204
    assert response.content == b""
    assert "content-type" not in response.headers
    assert (await api.get(f"/api/v1/menus/{menu['id']}")).status_code == 404
    assert await _status(database, key) is ImageStatus.DETACHED


async def test_delete_missing_menu_is_404(api) -> None:
    response = await api.delete("/api/v1/menus/999")

    assert response.status_code == 404


async def test_translation_delete_rules(api, place) -> None:
    menu = await create_menu(
        api,
        place["id"],
        translations=[
            {"language_code": "KO", "name": "떡볶이"},
            {"language_code": "EN", "name": "Tteokbokki"},
        ],
    )
    path = f"/api/v1/menus/{menu['id']}/translations"

    ko = await api.delete(f"{path}/KO")
    en = await api.delete(f"{path}/EN")
    en_again = await api.delete(f"{path}/EN")
    unknown = await api.delete(f"{path}/JP")

    assert (ko.status_code, ko.json()["code"]) == (409, "DELETE_CONFLICT")
    assert (en.status_code, en.content) == (204, b"")
    assert en_again.status_code == 404
    assert unknown.status_code == 422
    body = (await api.get(f"/api/v1/menus/{menu['id']}")).json()
    assert [row["language_code"] for row in body["translations"]] == ["KO"]
