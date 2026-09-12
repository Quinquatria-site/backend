import asyncio

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from quinquatria_persistence import (
    Category,
    CategoryCode,
    CategoryTranslation,
    LanguageCode,
    Place,
)

pytestmark = pytest.mark.asyncio


def category(name="주점"):
    return Category(
        code=CategoryCode.PUB,
        category_icon_uri="images/category/icon.webp",
        translations=[CategoryTranslation(language_code=LanguageCode.KO, name=name)],
    )


async def category_counts(database):
    async with database.engine.connect() as connection:
        return (
            await connection.scalar(text("SELECT count(*) FROM category")),
            await connection.scalar(text("SELECT count(*) FROM category_translation")),
        )


async def test_transaction_commits_parent_and_translations_together(database):
    resource = category()
    async with database.transaction() as session:
        session.add(resource)
    assert resource.id > 0
    assert resource.translations[0].id > 0
    assert await category_counts(database) == (1, 1)
    async with database.session() as session:
        saved = (
            await session.scalars(
                select(Category).options(selectinload(Category.translations))
            )
        ).one()
        assert saved.code is CategoryCode.PUB
        assert saved.translations[0].language_code is LanguageCode.KO
        assert saved.translations[0].name == "주점"


async def test_exception_rolls_back_flushed_parent_and_translations(database):
    with pytest.raises(RuntimeError, match="abort operation"):
        async with database.transaction() as session:
            session.add(category())
            await session.flush()
            raise RuntimeError("abort operation")
    assert await category_counts(database) == (0, 0)


async def test_commit_time_constraint_failure_rolls_back_prior_parent_flush(database):
    reached_context_exit = False
    with pytest.raises(IntegrityError) as error:
        async with database.transaction() as session:
            resource = Category(
                code=CategoryCode.BOOTH,
                category_icon_uri="images/category/booth.webp",
            )
            session.add(resource)
            await session.flush()
            assert resource.id > 0
            session.add(
                CategoryTranslation(
                    category_id=resource.id,
                    language_code=LanguageCode.KO,
                    name=None,
                )
            )
            reached_context_exit = True
    assert reached_context_exit
    assert error.value.orig.sqlstate == "23502"
    assert await category_counts(database) == (0, 0)

    # Failed transaction cleanup must allow the next operation to commit normally.
    async with database.transaction() as session:
        session.add(category("재시도"))
    assert await category_counts(database) == (1, 1)


@pytest.mark.parametrize("flush", [False, True])
async def test_session_does_not_automatically_commit(database, flush):
    async with database.session() as session:
        session.add(category())
        if flush:
            await session.flush()
            assert await session.scalar(text("SELECT count(*) FROM category")) == 1
    assert await category_counts(database) == (0, 0)


async def test_session_allows_explicit_commit(database):
    async with database.session() as session:
        session.add(category())
        await session.commit()
    assert await category_counts(database) == (1, 1)


async def test_in_place_image_reordering_and_append_persist_across_sessions(
    database, rows
):
    async with database.transaction() as session:
        place = await session.get(Place, rows["place"])
        place.place_image_uri.reverse()
        place.place_image_uri.append("images/place/third.webp")
    async with database.session() as session:
        saved = await session.get(Place, rows["place"])
        assert saved.place_image_uri == [
            "images/place/first.webp",
            "images/place/second.webp",
            "images/place/third.webp",
        ]


async def test_concurrent_operations_use_independent_sessions_and_transactions(
    database,
):
    ready = asyncio.Queue()
    release = asyncio.Event()

    async def create_resource(name):
        async with database.transaction() as session:
            session.add(category(name))
            await session.flush()
            backend_id = await session.scalar(text("SELECT pg_backend_pid()"))
            assert await session.scalar(text("SELECT count(*) FROM category")) == 1
            await ready.put((session, backend_id))
            await release.wait()

    async with asyncio.timeout(15):
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(create_resource("첫 번째"))
            tasks.create_task(create_resource("두 번째"))
            first, second = await ready.get(), await ready.get()
            assert first[0] is not second[0]
            assert first[1] != second[1]
            assert await category_counts(database) == (0, 0)
            release.set()
    assert await category_counts(database) == (2, 2)


async def test_translation_rules_reserved_for_api_are_not_accidentally_db_constraints(
    database,
):
    async with database.transaction() as session:
        resource = Category(
            code=CategoryCode.PUB,
            category_icon_uri="images/category/icon.webp",
            translations=[
                CategoryTranslation(language_code=LanguageCode.EN, name="Pub")
            ],
        )
        session.add(resource)
    assert await category_counts(database) == (1, 1)
    async with database.transaction() as session:
        await session.execute(text("DELETE FROM category_translation"))
    assert await category_counts(database) == (1, 0)
