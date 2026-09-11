from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from ._data import (
    DEFAULT_EMPTY_COLUMNS,
    INSTANT,
    NULLABLE_IMAGE_COLUMNS,
    TABLES,
    TRANSLATIONS,
    VALID_ROWS,
    insert_row,
)

pytestmark = pytest.mark.asyncio

REQUIRED_COLUMNS = [
    (table, column)
    for table, values in VALID_ROWS.items()
    for column in values
    if (table, column) not in NULLABLE_IMAGE_COLUMNS
] + [(table, "created_at") for table in ("notice", "lost_item")]

FOREIGN_KEYS = [
    (table, column)
    for table, values in VALID_ROWS.items()
    for column in values
    if column.endswith("_id")
]


async def assert_rejected(database, statement, parameters, sqlstate):
    with pytest.raises(DBAPIError) as error:
        async with database.engine.begin() as connection:
            await connection.execute(text(statement), parameters)
    assert error.value.orig.sqlstate == sqlstate


@pytest.mark.parametrize(("table", "column"), REQUIRED_COLUMNS)
async def test_every_required_field_rejects_null(database, rows, table, column):
    await assert_rejected(
        database,
        f"UPDATE {table} SET {column} = NULL WHERE id = :id",
        {"id": rows[table]},
        "23502",
    )


@pytest.mark.parametrize(("table", "column"), NULLABLE_IMAGE_COLUMNS)
async def test_image_fields_accept_null(database, rows, table, column):
    async with database.engine.begin() as connection:
        await connection.execute(
            text(f"UPDATE {table} SET {column} = NULL WHERE id = :id"),
            {"id": rows[table]},
        )
        assert await connection.scalar(
            text(f"SELECT {column} IS NULL FROM {table} WHERE id = :id"),
            {"id": rows[table]},
        )


async def test_description_and_found_location_default_to_empty_string(
    database, rows
):
    rows_without_defaulted_fields = {
        "place_translation": {
            "place_id": rows["place"],
            "language_code": "EN",
            "name": "Engineering Pub",
            "host_college": "College of Engineering",
        },
        "menu_translation": {
            "menu_id": rows["menu"],
            "language_code": "EN",
            "name": "Free Drink",
        },
        "performance_translation": {
            "performance_id": rows["performance"],
            "language_code": "EN",
            "title": "Performance",
        },
        "lost_item_translation": {
            "lost_item_id": rows["lost_item"],
            "language_code": "EN",
            "title": "Bag",
        },
    }
    async with database.engine.begin() as connection:
        inserted = {
            table: await insert_row(connection, table, values)
            for table, values in rows_without_defaulted_fields.items()
        }
        for table, column in DEFAULT_EMPTY_COLUMNS:
            assert (
                await connection.scalar(
                    text(f"SELECT {column} FROM {table} WHERE id = :id"),
                    {"id": inserted[table]},
                )
                == ""
            )


@pytest.mark.parametrize("table", TABLES)
@pytest.mark.parametrize("invalid_id", [0, -1, None])
async def test_ids_require_positive_non_null_integers(
    database, rows, table, invalid_id
):
    values = {"id": invalid_id, **VALID_ROWS[table]}
    columns = ", ".join(values)
    parameters = ", ".join(f":{column}" for column in values)
    await assert_rejected(
        database,
        f"INSERT INTO {table} ({columns}) OVERRIDING SYSTEM VALUE "
        f"VALUES ({parameters})",
        values,
        "23502" if invalid_id is None else "23514",
    )


@pytest.mark.parametrize(("table", "column"), FOREIGN_KEYS)
async def test_foreign_keys_reject_missing_parent(database, rows, table, column):
    await assert_rejected(
        database,
        f"UPDATE {table} SET {column} = 2147483647 WHERE id = :id",
        {"id": rows[table]},
        "23503",
    )


@pytest.mark.parametrize("table", TRANSLATIONS)
async def test_one_translation_per_parent_and_language(database, rows, table):
    values = VALID_ROWS[table]
    columns = ", ".join(values)
    parameters = ", ".join(f":{column}" for column in values)
    await assert_rejected(
        database,
        f"INSERT INTO {table} ({columns}) VALUES ({parameters})",
        values,
        "23505",
    )
    async with database.engine.begin() as connection:
        for language in ("EN", "CHN"):
            await insert_row(connection, table, {**values, "language_code": language})
        result = await connection.scalars(
            text(
                f"SELECT language_code::text FROM {table} "
                f"ORDER BY {table}.language_code"
            )
        )
        assert result.all() == ["CHN", "EN", "KO"]


@pytest.mark.parametrize(
    ("table", "column", "allowed"),
    [
        ("category", "code", ["PUB", "BOOTH", "FOODTRUCK", "MEDI", "BRACELET"]),
        ("performance", "type", ["ARTIST", "STUDENT", "SPECIAL"]),
        ("notice", "type", ["PERMANENT", "GENERAL"]),
        *[(table, "language_code", ["CHN", "EN", "KO"]) for table in TRANSLATIONS],
    ],
)
async def test_enums_accept_exact_values_and_reject_unknown_or_lowercase(
    database, rows, table, column, allowed
):
    async with database.engine.begin() as connection:
        for value in allowed:
            await connection.execute(
                text(f"UPDATE {table} SET {column} = :value WHERE id = :id"),
                {"value": value, "id": rows[table]},
            )
    for value in ("UNKNOWN", allowed[0].lower()):
        await assert_rejected(
            database,
            f"UPDATE {table} SET {column} = :value WHERE id = :id",
            {"value": value, "id": rows[table]},
            "22P02",
        )


@pytest.mark.parametrize(
    ("table", "column", "value"),
    [
        ("place", "category_sequence", 0),
        ("place", "category_sequence", -1),
        ("menu", "price", -1),
        ("place", "end_hour", INSTANT - timedelta(microseconds=1)),
        ("performance", "end_at", INSTANT - timedelta(microseconds=1)),
    ],
)
async def test_ranges_reject_values_beyond_the_boundary(
    database, rows, table, column, value
):
    await assert_rejected(
        database,
        f"UPDATE {table} SET {column} = :value WHERE id = :id",
        {"value": value, "id": rows[table]},
        "23514",
    )


async def test_boundary_values_and_image_order_round_trip(database, rows):
    async with database.engine.connect() as connection:
        place = (
            (await connection.execute(text("SELECT * FROM place WHERE id = 1")))
            .mappings()
            .one()
        )
        assert place["category_sequence"] == 1
        assert place["start_hour"] == place["end_hour"] == INSTANT
        assert place["x"] == 12.25
        assert place["y"] == -7.5
        assert place["place_image_uri"] == VALID_ROWS["place"]["place_image_uri"]
        assert await connection.scalar(text("SELECT price FROM menu")) == 0
        assert await connection.scalar(
            text("SELECT start_at = end_at FROM performance")
        )
        for table in ("notice", "lost_item"):
            created_at = await connection.scalar(
                text(f"SELECT created_at FROM {table}")
            )
            assert created_at.utcoffset() is not None
            assert abs(datetime.now(UTC) - created_at) < timedelta(minutes=1)
        assert (
            await connection.scalar(text("SELECT is_returned FROM lost_item")) is False
        )


@pytest.mark.parametrize(
    "expression",
    [
        "ARRAY[]::text[]",
        "ARRAY[NULL]::text[]",
        "ARRAY['image.webp', NULL]::text[]",
        "ARRAY[['first.webp', 'second.webp']]::text[]",
    ],
)
async def test_place_images_require_nonempty_one_dimensional_nonnull_elements(
    database, rows, expression
):
    await assert_rejected(
        database,
        f"UPDATE place SET place_image_uri = {expression} WHERE id = 1",
        {},
        "23514",
    )


@pytest.mark.parametrize(
    ("table", "columns"),
    [
        ("place", ("start_hour", "end_hour")),
        ("performance", ("start_at", "end_at")),
        ("notice", ("created_at",)),
        ("lost_item", ("created_at",)),
    ],
)
async def test_timestamps_preserve_instant_with_non_utc_offset(
    database, rows, table, columns
):
    local_time = INSTANT.astimezone(timezone(timedelta(hours=9)))
    assignments = ", ".join(f"{column} = :instant" for column in columns)
    async with database.engine.begin() as connection:
        await connection.execute(
            text(f"UPDATE {table} SET {assignments} WHERE id = 1"),
            {"instant": local_time},
        )
        values = (
            await connection.execute(text(f"SELECT {', '.join(columns)} FROM {table}"))
        ).one()
        assert all(
            value == INSTANT and value.utcoffset() is not None for value in values
        )
