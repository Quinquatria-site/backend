"""명세 §5.2, §6의 공지·번역 삭제."""

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, select

from quinquatria_persistence import Notice, NoticeTranslation

from .test_create import CHN, EN, KO
from .test_read import _create


def _assert_no_content(response: Response) -> None:
    assert response.status_code == 204
    assert response.content == b""
    assert "content-type" not in response.headers


async def _count(database, model) -> int:
    async with database.session() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def test_delete_notice_cascades_translations(api: AsyncClient, database) -> None:
    created = await _create(api, "GENERAL", KO, EN)
    kept = await _create(api, "GENERAL", KO)

    response = await api.delete(f"/api/v1/notices/{created['id']}")

    _assert_no_content(response)
    assert (await api.get(f"/api/v1/notices/{created['id']}")).status_code == 404
    assert await _count(database, Notice) == 1
    assert await _count(database, NoticeTranslation) == 1
    assert (await api.get(f"/api/v1/notices/{kept['id']}")).json() == kept


@pytest.mark.parametrize("notice_id", ["999", "2147483648"])
async def test_delete_missing_notice_is_404(api: AsyncClient, notice_id: str) -> None:
    response = await api.delete(f"/api/v1/notices/{notice_id}")

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"


@pytest.mark.parametrize("language", ["EN", "CHN"])
async def test_delete_translation_removes_only_that_language(
    api: AsyncClient, language: str
) -> None:
    created = await _create(api, "GENERAL", KO, EN, CHN)

    response = await api.delete(
        f"/api/v1/notices/{created['id']}/translations/{language}"
    )

    _assert_no_content(response)
    after = (await api.get(f"/api/v1/notices/{created['id']}")).json()
    assert after["translations"] == [
        row for row in created["translations"] if row["language_code"] != language
    ]


async def test_delete_ko_translation_is_conflict(api: AsyncClient) -> None:
    created = await _create(api, "GENERAL", KO, EN)

    response = await api.delete(f"/api/v1/notices/{created['id']}/translations/KO")

    assert response.status_code == 409
    assert response.json()["code"] == "DELETE_CONFLICT"
    assert (await api.get(f"/api/v1/notices/{created['id']}")).json() == created


async def test_delete_absent_translation_is_404(api: AsyncClient) -> None:
    created = await _create(api, "GENERAL", KO)

    response = await api.delete(f"/api/v1/notices/{created['id']}/translations/EN")

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"


@pytest.mark.parametrize("notice_id", ["999", "2147483648"])
async def test_delete_translation_of_missing_notice_is_404(
    api: AsyncClient, notice_id: str
) -> None:
    response = await api.delete(f"/api/v1/notices/{notice_id}/translations/EN")

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"


@pytest.mark.parametrize("language", ["en", "JP"])
async def test_delete_translation_rejects_unknown_language(
    api: AsyncClient, language: str
) -> None:
    created = await _create(api, "GENERAL", KO, EN)

    response = await api.delete(
        f"/api/v1/notices/{created['id']}/translations/{language}"
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
