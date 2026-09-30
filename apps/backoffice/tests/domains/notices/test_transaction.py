"""명세 §5.2의 기본 리소스 수정과 번역 upsert가 하나의 transaction인지 검증한다."""

import pytest
from httpx import AsyncClient

from backoffice.domains.notices import routes

from .test_create import EN, KO
from .test_read import _create


def _fail(*args, **kwargs):
    raise RuntimeError("응답 직렬화 실패를 흉내 낸다")


async def test_patch_failure_rolls_back_type_and_translations(
    api: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = await _create(api, "GENERAL", KO)
    monkeypatch.setattr(routes, "_serialize", _fail)

    response = await api.patch(
        f"/api/v1/notices/{created['id']}",
        json={
            "type": "PERMANENT",
            "translations": [EN, {**KO, "title": "바뀌면 안 되는 제목"}],
        },
    )

    assert response.status_code == 500
    monkeypatch.undo()
    assert (await api.get(f"/api/v1/notices/{created['id']}")).json() == created


async def test_create_failure_leaves_nothing(
    api: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(routes, "_serialize", _fail)

    response = await api.post(
        "/api/v1/notices", json={"type": "GENERAL", "translations": [KO, EN]}
    )

    assert response.status_code == 500
    monkeypatch.undo()
    assert (await api.get("/api/v1/notices")).json()["total"] == 0
