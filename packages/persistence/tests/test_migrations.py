import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from quinquatria_persistence import Base, Database

from ._data import DEFAULT_EMPTY_COLUMNS, NULLABLE_IMAGE_COLUMNS, TABLES, VALID_ROWS

EXPECTED_ENUMS = {
    "language_code": ["CHN", "EN", "KO"],
    "category_code": ["PUB", "BOOTH", "FOODTRUCK", "MEDI", "BRACELET"],
    "performance_type": ["ARTIST", "STUDENT", "SPECIAL"],
    "notice_type": ["PERMANENT", "GENERAL"],
}

EXPECTED_INDEXES = {
    "category": {("code", "id")},
    "place": {("category_id", "category_sequence", "id")},
    "menu": {("place_id", "id")},
    "performance": {("start_at", "id"), ("type", "start_at", "id")},
    "notice": {("created_at", "id"), ("type", "created_at", "id")},
    "lost_item": {("created_at", "id"), ("is_returned", "created_at", "id")},
}


def assert_schema(connection):
    inspector = inspect(connection)
    assert set(inspector.get_table_names()) == {*TABLES, "alembic_version"}
    assert {
        enum["name"]: enum["labels"] for enum in inspector.get_enums(schema="public")
    } == EXPECTED_ENUMS
    for table in TABLES:
        columns = {column["name"]: column for column in inspector.get_columns(table)}
        expected_fields = {"id", *VALID_ROWS[table]}
        if table in {"notice", "lost_item"}:
            expected_fields.add("created_at")
            assert columns["created_at"]["default"] is not None
        assert set(columns) == expected_fields
        assert {
            (table, column["name"])
            for column in columns.values()
            if column["nullable"]
        } == {field for field in NULLABLE_IMAGE_COLUMNS if field[0] == table}
        for default_table, default_column in DEFAULT_EMPTY_COLUMNS:
            if default_table == table:
                assert columns[default_column]["default"] is not None
        assert columns["id"]["identity"]
        assert inspector.get_pk_constraint(table)["constrained_columns"] == ["id"]
        indexes = {
            tuple(index["column_names"])
            for index in inspector.get_indexes(table)
            if not index["unique"]
        }
        assert indexes == EXPECTED_INDEXES.get(table, set())

    context = MigrationContext.configure(
        connection,
        opts={"compare_type": True, "compare_server_default": True},
    )
    assert compare_metadata(context, Base.metadata) == []


def test_empty_database_upgrade_repeat_downgrade_and_reapply(
    empty_database_url, alembic_config, monkeypatch
):
    # Exercise the normal environment-variable path used by the Alembic CLI.
    monkeypatch.setenv(
        "DATABASE_URL", empty_database_url.render_as_string(hide_password=False)
    )
    engine = create_engine(empty_database_url)
    try:
        with engine.connect() as connection:
            assert inspect(connection).get_table_names() == []
            assert (
                int(connection.scalar(text("SHOW server_version_num"))) // 10000 == 18
            )

        command.upgrade(alembic_config, "head")
        with engine.connect() as connection:
            assert_schema(connection)
            revision = connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
            assert revision

        command.upgrade(alembic_config, "head")
        with engine.connect() as connection:
            assert_schema(connection)
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == revision
            )

        command.downgrade(alembic_config, "base")
        with engine.connect() as connection:
            assert set(inspect(connection).get_table_names()) == {"alembic_version"}
            assert inspect(connection).get_enums(schema="public") == []
            assert connection.scalar(text("SELECT count(*) FROM alembic_version")) == 0

        command.upgrade(alembic_config, "head")
        with engine.connect() as connection:
            assert_schema(connection)
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_programmatic_migration_accepts_async_connection_bridge(
    empty_database_url, alembic_config
):
    database = Database(empty_database_url)
    try:
        async with database.engine.begin() as connection:

            def upgrade(sync_connection):
                alembic_config.attributes["connection"] = sync_connection
                command.upgrade(alembic_config, "head")

            await connection.run_sync(upgrade)
            await connection.run_sync(assert_schema)
    finally:
        await database.dispose()
