"""분실물·번역 삭제 (명세 §5.2, §6)."""

import pytest
from sqlalchemy import func, select

from backoffice.crud.resources import POSTGRESQL_INTEGER_MAX
from quinquatria_persistence.enums import ImageStatus
from quinquatria_persistence.models import LostItemTranslation

from ._support import URL, body, image_status, ko, seed_image

EN = {"language_code": "EN", "title": "Wallet"}


async def _create(api, **overrides) -> dict:
    response = await api.post(URL, json=body(**overrides))
    assert response.status_code == 201
    return response.json()


def _assert_empty_204(response) -> None:
    assert response.status_code == 204
    assert response.content == b""
    assert "content-type" not in response.headers


async def test_delete_removes_item_and_translations(api, database) -> None:
    created = await _create(api, translations=[ko(), EN])

    response = await api.delete(f"{URL}/{created['id']}")

    _assert_empty_204(response)
    assert (await api.get(f"{URL}/{created['id']}")).status_code == 404
    async with database.session() as session:
        remaining = await session.scalar(
            select(func.count()).select_from(LostItemTranslation)
        )
    assert remaining == 0


async def test_delete_detaches_image(api, database, object_store) -> None:
    key = await seed_image(database, object_store, "deleted")
    created = await _create(api, image_url=key)

    _assert_empty_204(await api.delete(f"{URL}/{created['id']}"))

    assert await image_status(database, key) is ImageStatus.DETACHED


@pytest.mark.parametrize("lost_item_id", [999, POSTGRESQL_INTEGER_MAX + 1])
async def test_delete_missing_is_not_found(api, lost_item_id) -> None:
    response = await api.delete(f"{URL}/{lost_item_id}")

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"


async def test_delete_translation_keeps_others(api) -> None:
    created = await _create(api, translations=[ko(), EN])

    response = await api.delete(f"{URL}/{created['id']}/translations/EN")

    _assert_empty_204(response)
    remaining = (await api.get(f"{URL}/{created['id']}")).json()["translations"]
    assert remaining == [
        t for t in created["translations"] if t["language_code"] == "KO"
    ]


async def test_delete_ko_translation_is_conflict(api) -> None:
    created = await _create(api)

    response = await api.delete(f"{URL}/{created['id']}/translations/KO")

    assert response.status_code == 409
    assert response.json()["code"] == "DELETE_CONFLICT"
    assert (await api.get(f"{URL}/{created['id']}")).json() == created


async def test_delete_missing_translation_is_not_found(api) -> None:
    created = await _create(api)

    response = await api.delete(f"{URL}/{created['id']}/translations/CHN")

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"


@pytest.mark.parametrize("language", ["KO", "EN"])
async def test_delete_translation_of_missing_item_is_not_found(api, language) -> None:
    response = await api.delete(f"{URL}/999/translations/{language}")

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"


async def test_delete_translation_rejects_unknown_language(api) -> None:
    created = await _create(api)

    response = await api.delete(f"{URL}/{created['id']}/translations/en")

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
