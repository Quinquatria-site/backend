"""장소 위치 표현(명세 §5.4): 점은 `x`·`y`, 구역은 `area` 다각형이다.

DB CHECK가 두 표현이 섞이지 않게 하고, `Polygon` 타입이 꼭짓점 순서와 값을
그대로 왕복시킨다.
"""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from quinquatria_persistence import Place, Vertex

from ._data import insert_row

pytestmark = pytest.mark.asyncio

TRIANGLE = "((0,0),(4,0),(4,3))"


async def _insert(database, values):
    async with database.engine.begin() as connection:
        return await insert_row(connection, "place", values)


async def test_polygon_place_without_point_is_accepted(database):
    place_id = await _insert(database, {"is_polygon": True, "area": TRIANGLE})

    async with database.engine.connect() as connection:
        row = (
            await connection.execute(
                text("SELECT x, y, npoints(area) FROM place WHERE id = :id"),
                {"id": place_id},
            )
        ).one()
    assert tuple(row) == (None, None, 3)


async def test_point_place_defaults_to_not_polygon(database):
    place_id = await _insert(database, {"x": 1.0, "y": 2.0})

    async with database.engine.connect() as connection:
        assert (
            await connection.scalar(
                text("SELECT is_polygon FROM place WHERE id = :id"), {"id": place_id}
            )
            is False
        )


@pytest.mark.parametrize(
    "values",
    [
        {"x": 1.0, "y": 2.0, "area": TRIANGLE},
        {"x": 1.0},
        {"is_polygon": True},
        {"is_polygon": True, "area": TRIANGLE, "x": 1.0},
        {"is_polygon": True, "area": TRIANGLE, "y": 1.0},
        {"is_polygon": True, "area": "((0,0),(4,0))"},
        {"is_polygon": False, "area": TRIANGLE},
    ],
    ids=[
        "point-with-area",
        "point-missing-y",
        "polygon-missing-area",
        "polygon-with-x",
        "polygon-with-y",
        "polygon-two-vertices",
        "area-without-flag",
    ],
)
async def test_mixed_or_incomplete_shape_is_rejected(database, values):
    with pytest.raises(DBAPIError) as error:
        await _insert(database, values)
    assert error.value.orig.sqlstate == "23514"


async def test_orm_round_trips_vertices_in_order(database):
    area = [Vertex(0.1, 0.2), Vertex(-1e-300, 1.7976931348623157e308), Vertex(5, -3)]
    async with database.transaction() as session:
        place = Place(is_polygon=True, area=area)
        session.add(place)
        await session.flush()
        place_id = place.id

    async with database.session() as session:
        stored = await session.scalar(select(Place.area).where(Place.id == place_id))
    assert stored == area
    assert all(isinstance(vertex, Vertex) for vertex in stored)


async def test_orm_switches_point_to_polygon(database):
    async with database.transaction() as session:
        place = Place(x=1.0, y=2.0)
        session.add(place)
        await session.flush()
        assert place.is_polygon is False
        place.is_polygon, place.x, place.y = True, None, None
        place.area = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
        place_id = place.id

    async with database.session() as session:
        stored = await session.get(Place, place_id)
        assert (stored.is_polygon, stored.x, stored.y) == (True, None, None)
        assert stored.area == [Vertex(0, 0), Vertex(1, 0), Vertex(1, 1)]
