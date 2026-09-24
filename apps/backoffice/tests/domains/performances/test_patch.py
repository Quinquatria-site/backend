"""공연 수정과 번역 upsert·삭제, 일차 이동 (명세 §5.2, §5.6)."""

import pytest

from ._support import DAY_ONE, DAY_TWO, create, order_of


async def _patch(api, performance_id, payload):
    return await api.patch(f"/api/v1/performances/{performance_id}", json=payload)


async def test_patch_changes_only_given_fields(api) -> None:
    created = await create(api)

    response = await _patch(api, created["id"], {"type": "SPECIAL"})

    assert response.status_code == 200
    assert response.json() == created | {"type": "SPECIAL"}


async def test_patch_upserts_only_given_languages(api) -> None:
    created = await create(
        api,
        translations=[
            {"language_code": "KO", "title": "공연", "description": "설명"},
            {"language_code": "CHN", "title": "演出"},
        ],
    )
    chn, ko = created["translations"]

    response = await _patch(
        api,
        created["id"],
        {
            "translations": [
                {"language_code": "KO", "title": "새 제목"},
                {"language_code": "EN", "title": "Show"},
            ]
        },
    )

    assert response.status_code == 200
    translations = response.json()["translations"]
    assert [t["language_code"] for t in translations] == ["CHN", "EN", "KO"]
    assert translations[0] == chn
    assert translations[2] == ko | {"title": "새 제목", "description": ""}
    assert translations[1]["performance_id"] == created["id"]
    fetched = (await api.get(f"/api/v1/performances/{created['id']}")).json()
    assert fetched == response.json()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"seq": 1},
        {"is_live": True},
        {"type": None},
        {"date": None},
        {"date": "2026-10-06T00:00:00"},
        {"translations": []},
        {"translations": None},
        {"translations": [{"language_code": "EN"}]},
        {"id": 1},
    ],
)
async def test_patch_rejects_invalid_bodies(api, payload) -> None:
    created = await create(api)

    response = await _patch(api, created["id"], payload)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_patch_unknown_id_is_not_found(api) -> None:
    response = await _patch(api, 999, {"type": "SPECIAL"})

    assert response.status_code == 404


async def test_changing_date_moves_to_the_end_and_renumbers_the_source(
    api, database
) -> None:
    a = await create(api, "a")
    b = await create(api, "b")
    c = await create(api, "c")
    x = await create(api, "x", date=DAY_TWO)

    response = await _patch(api, a["id"], {"date": DAY_TWO})

    assert response.status_code == 200
    assert (response.json()["date"], response.json()["seq"]) == (DAY_TWO, 2)
    assert await order_of(database, DAY_ONE) == [(b["id"], 1), (c["id"], 2)]
    assert await order_of(database, DAY_TWO) == [(x["id"], 1), (a["id"], 2)]


async def test_sending_the_same_date_keeps_the_position(api, database) -> None:
    a = await create(api, "a")
    b = await create(api, "b")

    response = await _patch(api, a["id"], {"date": DAY_ONE})

    assert response.json()["seq"] == 1
    assert await order_of(database, DAY_ONE) == [(a["id"], 1), (b["id"], 2)]


async def test_delete_translation(api) -> None:
    created = await create(
        api,
        translations=[
            {"language_code": "KO", "title": "공연"},
            {"language_code": "EN", "title": "Show"},
        ],
    )
    path = f"/api/v1/performances/{created['id']}/translations"

    response = await api.delete(f"{path}/EN")

    assert response.status_code == 204
    assert response.content == b""
    assert "content-type" not in response.headers
    fetched = (await api.get(f"/api/v1/performances/{created['id']}")).json()
    assert [t["language_code"] for t in fetched["translations"]] == ["KO"]
    assert (await api.delete(f"{path}/EN")).status_code == 404
    assert (await api.delete(f"{path}/KO")).status_code == 409
    assert (await api.delete(f"{path}/ko")).status_code == 422
    assert (
        await api.delete("/api/v1/performances/999/translations/EN")
    ).status_code == 404
