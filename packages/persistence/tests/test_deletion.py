import pytest
from psycopg.errors import RestrictViolation
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from quinquatria_persistence import Category, Menu, Place

from ._data import TABLES

pytestmark = pytest.mark.asyncio


async def counts(database):
    async with database.engine.connect() as connection:
        return {
            table: await connection.scalar(text(f"SELECT count(*) FROM {table}"))
            for table in TABLES
        }


@pytest.mark.parametrize("method", ["sql", "orm_unloaded", "orm_loaded"])
async def test_category_delete_is_restricted_and_rolls_back_every_change(
    database, rows, method
):
    with pytest.raises(IntegrityError) as error:
        async with database.transaction() as session:
            await session.execute(
                text("UPDATE category_translation SET name = 'changed' WHERE id = 1")
            )
            if method == "sql":
                await session.execute(text("DELETE FROM category WHERE id = 1"))
            else:
                statement = select(Category).where(Category.id == 1)
                if method == "orm_loaded":
                    statement = statement.options(
                        selectinload(Category.translations),
                        selectinload(Category.places),
                    )
                category = (await session.scalars(statement)).one()
                await session.delete(category)
    assert isinstance(error.value.orig, RestrictViolation)
    assert error.value.orig.sqlstate == "23001"
    assert error.value.orig.diag.constraint_name == "fk_place_category_id_category"
    assert await counts(database) == dict.fromkeys(TABLES, 1)
    async with database.engine.connect() as connection:
        assert (
            await connection.scalar(
                text("SELECT name FROM category_translation WHERE id = 1")
            )
            == "주점"
        )


@pytest.mark.parametrize("method", ["sql", "orm_unloaded", "orm_loaded"])
async def test_place_delete_cascades_menus_and_all_their_translations(
    database, rows, method
):
    async with database.transaction() as session:
        if method == "sql":
            await session.execute(text("DELETE FROM place WHERE id = 1"))
        else:
            statement = select(Place).where(Place.id == 1)
            if method == "orm_loaded":
                statement = statement.options(
                    selectinload(Place.translations),
                    selectinload(Place.menus).selectinload(Menu.translations),
                )
            place = (await session.scalars(statement)).one()
            await session.delete(place)
    expected = dict.fromkeys(TABLES, 1)
    expected.update(
        dict.fromkeys(("place", "place_translation", "menu", "menu_translation"), 0)
    )
    assert await counts(database) == expected


@pytest.mark.parametrize(
    "parent", ["category", "menu", "performance", "notice", "lost_item"]
)
async def test_deleting_parent_cascades_its_translations(database, rows, parent):
    async with database.engine.begin() as connection:
        if parent == "category":
            await connection.execute(text("DELETE FROM place"))
        await connection.execute(text(f"DELETE FROM {parent} WHERE id = 1"))
        assert await connection.scalar(text(f"SELECT count(*) FROM {parent}")) == 0
        assert (
            await connection.scalar(text(f"SELECT count(*) FROM {parent}_translation"))
            == 0
        )
