"""명세 §5.2의 공지 부분 수정과 번역 upsert."""

import pytest
from httpx import AsyncClient

from .test_create import CHN, EN, KO
from .test_read import _create


def _ids(notice: dict) -> dict[str, int]:
    return {row["language_code"]: row["id"] for row in notice["translations"]}


async def test_patch_type_only_keeps_translations(api: AsyncClient) -> None:
    created = await _create(api, "GENERAL", KO, EN)

    response = await api.patch(
        f"/api/v1/notices/{created['id']}", json={"type": "PERMANENT"}
    )

    assert response.status_code == 200
    assert response.json() == {**created, "type": "PERMANENT"}


async def test_patch_upserts_only_sent_languages(api: AsyncClient) -> None:
    created = await _create(api, "GENERAL", KO, CHN)
    new_en = {"language_code": "EN", "title": "New", "content": "Body"}
    new_ko = {"language_code": "KO", "title": "새 제목", "content": "새 본문"}

    response = await api.patch(
        f"/api/v1/notices/{created['id']}", json={"translations": [new_en, new_ko]}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "GENERAL"
    assert body["created_at"] == created["created_at"]
    assert [t["language_code"] for t in body["translations"]] == ["CHN", "EN", "KO"]
    before, after = _ids(created), _ids(body)
    assert after["KO"] == before["KO"]
    assert after["CHN"] == before["CHN"]
    chn, en, ko = body["translations"]
    assert chn == created["translations"][0]
    assert en == {"id": en["id"], "notice_id": created["id"], **new_en}
    assert ko == {"id": before["KO"], "notice_id": created["id"], **new_ko}
    assert (await api.get(f"/api/v1/notices/{created['id']}")).json() == body


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="empty"),
        pytest.param({"translations": []}, id="empty-translations"),
        pytest.param({"type": None}, id="null-type"),
        pytest.param({"translations": None}, id="null-translations"),
        pytest.param({"type": "URGENT"}, id="unknown-type"),
        pytest.param({"created_at": "2026-10-05T13:00:00+09:00"}, id="created-at"),
        pytest.param(
            {"type": "GENERAL", "created_at": "2026-10-05T13:00:00+09:00"},
            id="created-at-with-change",
        ),
        pytest.param({"id": 7}, id="server-id"),
        pytest.param({"is_urgent": True}, id="urgent-flag"),
        pytest.param({"translations": [EN, EN]}, id="duplicate-language"),
        pytest.param(
            {"translations": [{"language_code": "EN", "title": "t"}]},
            id="missing-content",
        ),
        pytest.param({"translations": [{**EN, "id": 1}]}, id="translation-id"),
    ],
)
async def test_patch_rejects_invalid_body(api: AsyncClient, body: dict) -> None:
    created = await _create(api, "GENERAL", KO)

    response = await api.patch(f"/api/v1/notices/{created['id']}", json=body)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert (await api.get(f"/api/v1/notices/{created['id']}")).json() == created


@pytest.mark.parametrize("notice_id", ["999", "2147483648"])
async def test_patch_missing_notice_is_404(api: AsyncClient, notice_id: str) -> None:
    response = await api.patch(f"/api/v1/notices/{notice_id}", json={"type": "GENERAL"})

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"
