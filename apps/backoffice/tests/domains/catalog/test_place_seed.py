"""지도 좌표 장소를 운영 DB에 미리 넣는 일회성 시드 (명세 §5.4)."""

import json

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from backoffice.domains.catalog.place_seed import (
    BUNDLED,
    SeedConflict,
    load,
    seed_places,
)
from quinquatria_persistence.models import Place

_ENTRIES = [
    {"code": "BOOTH", "category_sequence": 101, "x": 428, "y": 879},
    {"code": "TRASHCAN", "category_sequence": 1, "x": 494.5, "y": 791},
]


def _write(tmp_path, entries) -> str:
    path = tmp_path / "places.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


async def _places(database) -> list[tuple]:
    async with database.session() as session:
        rows = await session.execute(
            select(
                Place.category_id,
                Place.category_sequence,
                Place.x,
                Place.y,
                Place.start_hour,
                Place.end_hour,
            ).order_by(Place.id)
        )
        return [tuple(row) for row in rows]


async def test_bundled_file_lists_every_map_place() -> None:
    places = load(BUNDLED)

    assert len(places) == 73
    assert {place.code for place in places} == {
        "BOOTH",
        "PUB",
        "FOODTRUCK",
        "TRASHCAN",
        "PHOTOBOOTH",
    }


async def test_seed_creates_coordinate_and_category_only_places(
    database, tmp_path
) -> None:
    async with database.transaction() as session:
        report = await seed_places(session, load(_write(tmp_path, _ENTRIES)))

    assert (report.created, report.skipped) == (2, 0)
    assert await _places(database) == [
        (2, 101, 428.0, 879.0, None, None),
        (5, 1, 494.5, 791.0, None, None),
    ]


async def test_rerun_skips_places_already_seeded(database, tmp_path) -> None:
    places = load(_write(tmp_path, _ENTRIES))
    async with database.transaction() as session:
        await seed_places(session, places[:1])

    async with database.transaction() as session:
        report = await seed_places(session, places)

    assert (report.created, report.skipped) == (1, 1)
    assert len(await _places(database)) == 2


async def test_taken_pair_at_other_coordinates_aborts_everything(
    database, tmp_path
) -> None:
    """같은 구역 번호가 다른 자리에 있으면 덮어쓰지 않고 전체를 되돌린다."""
    async with database.transaction() as session:
        await seed_places(session, load(_write(tmp_path, _ENTRIES[:1])))
    moved = [_ENTRIES[1], {**_ENTRIES[0], "x": 1.0}]

    with pytest.raises(SeedConflict, match="BOOTH 101"):
        async with database.transaction() as session:
            await seed_places(session, load(_write(tmp_path, moved)))

    assert len(await _places(database)) == 1


@pytest.mark.parametrize(
    "entries",
    [
        [{"code": "TRASH", "category_sequence": 1, "x": 0, "y": 0}],
        [{"code": "BOOTH", "category_sequence": 0, "x": 0, "y": 0}],
        [{"code": "BOOTH", "category_sequence": 1, "x": 0}],
        [{"code": "BOOTH", "category_sequence": 1, "x": "0", "y": 0}],
        [{"code": "BOOTH", "category_sequence": 1, "x": 0, "y": 0, "name": "부스"}],
        [_ENTRIES[0], {**_ENTRIES[0], "x": 1}],
        {"code": "BOOTH", "category_sequence": 1, "x": 0, "y": 0},
    ],
    ids=[
        "unknown-code",
        "sequence-below-one",
        "missing-coordinate",
        "string-coordinate",
        "unknown-field",
        "repeated-pair",
        "not-a-list",
    ],
)
async def test_invalid_file_is_rejected_before_touching_the_database(
    tmp_path, entries
) -> None:
    with pytest.raises(ValidationError):
        load(_write(tmp_path, entries))
