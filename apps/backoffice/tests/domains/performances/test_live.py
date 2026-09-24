"""`PUT /performances/{id}/live` (명세 §5.6). live 공연은 전체에서 최대 1건이다."""

import pytest
from sqlalchemy import select

from quinquatria_persistence.models import Performance

from ._support import DAY_TWO, create


async def _live(api, performance_id, value):
    return await api.put(
        f"/api/v1/performances/{performance_id}/live", json={"is_live": value}
    )


async def _live_ids(database) -> list[int]:
    async with database.session() as session:
        rows = await session.scalars(
            select(Performance.id).where(Performance.is_live).order_by(Performance.id)
        )
        return list(rows.all())


async def test_setting_live_returns_the_full_resource(api) -> None:
    created = await create(api)

    response = await _live(api, created["id"], True)

    assert response.status_code == 200
    assert response.json() == created | {"is_live": True}


async def test_setting_live_unsets_the_previous_one(api, database) -> None:
    first = await create(api, "a")
    second = await create(api, "b", date=DAY_TWO)
    await _live(api, first["id"], True)

    await _live(api, second["id"], True)

    assert await _live_ids(database) == [second["id"]]


async def test_unsetting_live_leaves_no_live_performance(api, database) -> None:
    first = await create(api, "a")
    second = await create(api, "b")
    await _live(api, first["id"], True)

    unset_other = await _live(api, second["id"], False)
    assert await _live_ids(database) == [first["id"]]
    assert unset_other.json()["is_live"] is False

    await _live(api, first["id"], False)
    assert await _live_ids(database) == []


async def test_live_is_idempotent(api, database) -> None:
    created = await create(api)

    for _ in range(2):
        response = await _live(api, created["id"], True)
        assert response.status_code == 200
    assert await _live_ids(database) == [created["id"]]


async def test_live_unknown_id_is_not_found(api) -> None:
    response = await _live(api, 999, True)

    assert response.status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"is_live": None},
        {"is_live": "true"},
        {"is_live": 1},
        {"is_live": True, "seq": 1},
        {"is_live": True, "type": "ARTIST"},
    ],
)
async def test_live_rejects_invalid_bodies(api, payload) -> None:
    created = await create(api)

    response = await api.put(f"/api/v1/performances/{created['id']}/live", json=payload)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_patch_and_list_keep_the_live_flag(api) -> None:
    created = await create(api)
    await _live(api, created["id"], True)

    patched = await api.patch(
        f"/api/v1/performances/{created['id']}", json={"date": DAY_TWO}
    )

    assert patched.json()["is_live"] is True
