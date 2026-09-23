"""장소 이미지 배열의 순서 보존과 교체 (명세 §4.6, §5.4)."""

from sqlalchemy import select

from quinquatria_persistence.enums import ImageStatus
from quinquatria_persistence.models import Image

from ._helpers import create_category, create_place, place_body, upload


async def _status(database, key: str) -> ImageStatus:
    async with database.session() as session:
        return await session.scalar(select(Image.status).where(Image.s3_key == key))


async def _keys(api, store, count: int) -> list[str]:
    return [await upload(api, store, "PLACE_IMAGE") for _ in range(count)]


async def test_create_preserves_image_order(api, database, object_store) -> None:
    category = await create_category(api)
    keys = await _keys(api, object_store, 3)
    ordered = [keys[2], keys[0], keys[1]]

    place = await create_place(api, category["id"], place_image_uri=ordered)

    assert place["place_image_uri"] == ordered
    assert (await api.get(f"/api/v1/places/{place['id']}")).json() == place
    assert (await api.get("/api/v1/places")).json()["items"] == [place]
    for key in keys:
        assert await _status(database, key) is ImageStatus.ATTACHED


async def test_duplicate_keys_are_invalid_image(api, object_store) -> None:
    category = await create_category(api)
    [key] = await _keys(api, object_store, 1)

    response = await api.post(
        "/api/v1/places", json=place_body(category["id"], place_image_uri=[key, key])
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_IMAGE"


async def test_patch_reorders_replaces_and_detaches(
    api, database, object_store
) -> None:
    category = await create_category(api)
    a, b, c, d = await _keys(api, object_store, 4)
    place = await create_place(api, category["id"], place_image_uri=[a, b, c])

    response = await api.patch(
        f"/api/v1/places/{place['id']}", json={"place_image_uri": [c, d, a]}
    )

    assert response.status_code == 200
    assert response.json()["place_image_uri"] == [c, d, a]
    got = await api.get(f"/api/v1/places/{place['id']}")
    assert got.json()["place_image_uri"] == [c, d, a]
    assert await _status(database, b) is ImageStatus.DETACHED
    assert await _status(database, d) is ImageStatus.ATTACHED


async def test_patch_null_detaches_every_image(api, database, object_store) -> None:
    category = await create_category(api)
    a, b = await _keys(api, object_store, 2)
    place = await create_place(api, category["id"], place_image_uri=[a, b])

    response = await api.patch(
        f"/api/v1/places/{place['id']}", json={"place_image_uri": None}
    )

    assert response.json()["place_image_uri"] is None
    assert await _status(database, a) is ImageStatus.DETACHED
    assert await _status(database, b) is ImageStatus.DETACHED


async def test_failed_image_rolls_back_fields_and_translations(
    api, database, object_store
) -> None:
    category = await create_category(api)
    [a] = await _keys(api, object_store, 1)
    place = await create_place(api, category["id"], place_image_uri=[a])

    response = await api.patch(
        f"/api/v1/places/{place['id']}",
        json={
            "x": 0.5,
            "place_image_uri": ["images/place/missing.webp"],
            "translations": [
                {"language_code": "KO", "name": "바뀜", "host_college": "바뀜"}
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_IMAGE"
    assert (await api.get(f"/api/v1/places/{place['id']}")).json() == place
    assert await _status(database, a) is ImageStatus.ATTACHED
