"""`performance`는 일차(`date`) 안의 노출 순서(`seq`)를 DB로 보장한다 (명세 §5.6).

0004 마이그레이션이 `start_at`/`end_at`을 `date`, `seq`, `is_live`로 바꾼다.
기존 행의 변환과 되돌리기도 여기서 확인한다.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from ._data import FESTIVAL_DAY, VALID_ROWS, insert_row

SEOUL = timezone(timedelta(hours=9))


async def _performances(connection, *sequences: int) -> list[int]:
    return [
        await insert_row(
            connection, "performance", VALID_ROWS["performance"] | {"seq": seq}
        )
        for seq in sequences
    ]


async def test_is_live_defaults_to_false(database) -> None:
    async with database.engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO performance (type, date, seq) VALUES ('ARTIST', :d, 1)"),
            {"d": FESTIVAL_DAY},
        )
        assert await connection.scalar(text("SELECT is_live FROM performance")) is False


async def test_a_date_cannot_repeat_a_sequence(database) -> None:
    async with database.engine.begin() as connection:
        await _performances(connection, 1)

    with pytest.raises(IntegrityError):
        async with database.engine.begin() as connection:
            await _performances(connection, 1)


async def test_other_dates_may_reuse_a_sequence(database) -> None:
    async with database.engine.begin() as connection:
        await _performances(connection, 1)
        await insert_row(
            connection,
            "performance",
            VALID_ROWS["performance"] | {"date": FESTIVAL_DAY + timedelta(days=1)},
        )
        assert await connection.scalar(text("SELECT count(*) FROM performance")) == 2


async def test_sequences_may_be_rewritten_within_one_transaction(database) -> None:
    """deferrable 제약이라 순서 재배치의 중간 상태가 허용된다."""
    async with database.engine.begin() as connection:
        first, second = await _performances(connection, 1, 2)

    async with database.engine.begin() as connection:
        await connection.execute(
            text("UPDATE performance SET seq = 1 WHERE id = :id"), {"id": second}
        )
        await connection.execute(
            text("UPDATE performance SET seq = 2 WHERE id = :id"), {"id": first}
        )
        order = (
            await connection.scalars(text("SELECT id FROM performance ORDER BY seq"))
        ).all()

    assert order == [second, first]


def _seed_old_schema(connection) -> None:
    rows = [
        # 서울 기준 10/6 늦은 밤은 UTC로는 같은 날, 10/7 새벽은 UTC로는 10/6이다.
        (10, datetime(2026, 10, 6, 21, tzinfo=SEOUL)),
        (11, datetime(2026, 10, 6, 18, tzinfo=SEOUL)),
        (12, datetime(2026, 10, 7, 1, tzinfo=SEOUL)),
        (13, datetime(2026, 10, 6, 18, tzinfo=SEOUL)),
    ]
    for performance_id, start_at in rows:
        connection.execute(
            text(
                "INSERT INTO performance (id, type, start_at, end_at) "
                "OVERRIDING SYSTEM VALUE VALUES (:id, 'ARTIST', :start, :start)"
            ),
            {"id": performance_id, "start": start_at},
        )


def test_upgrade_converts_start_at_into_seoul_date_and_sequence(
    empty_database_url, alembic_config
) -> None:
    engine = create_engine(empty_database_url)
    try:
        with engine.begin() as connection:
            alembic_config.attributes["connection"] = connection
            command.upgrade(alembic_config, "0004_place_sequence_unique")
            _seed_old_schema(connection)
            command.upgrade(alembic_config, "0005_performance_date_seq")
            rows = connection.execute(
                text("SELECT id, date, seq, is_live FROM performance ORDER BY id")
            ).all()

        # 같은 시각(11, 13)은 id로 순서를 정한다.
        assert [tuple(row) for row in rows] == [
            (10, date(2026, 10, 6), 3, False),
            (11, date(2026, 10, 6), 1, False),
            (12, date(2026, 10, 7), 1, False),
            (13, date(2026, 10, 6), 2, False),
        ]
    finally:
        engine.dispose()


def test_downgrade_restores_order_as_seoul_midnight_offsets(
    empty_database_url, alembic_config
) -> None:
    """되돌리면 시각은 잃지만 일차와 순서는 `start_at`에 보존된다."""
    engine = create_engine(empty_database_url)
    try:
        with engine.begin() as connection:
            alembic_config.attributes["connection"] = connection
            command.upgrade(alembic_config, "0004_place_sequence_unique")
            _seed_old_schema(connection)
            command.upgrade(alembic_config, "0005_performance_date_seq")
            command.downgrade(alembic_config, "0004_place_sequence_unique")
            rows = connection.execute(
                text("SELECT id, start_at, end_at FROM performance ORDER BY id")
            ).all()
            command.upgrade(alembic_config, "0005_performance_date_seq")
            reapplied = connection.execute(
                text("SELECT id, date, seq FROM performance ORDER BY id")
            ).all()

        midnight = datetime(2026, 10, 6, tzinfo=SEOUL)
        assert [tuple(row) for row in rows] == [
            (10, midnight + timedelta(seconds=2), midnight + timedelta(seconds=2)),
            (11, midnight, midnight),
            (12, midnight + timedelta(days=1), midnight + timedelta(days=1)),
            (13, midnight + timedelta(seconds=1), midnight + timedelta(seconds=1)),
        ]
        assert [tuple(row) for row in reapplied] == [
            (10, date(2026, 10, 6), 3),
            (11, date(2026, 10, 6), 1),
            (12, date(2026, 10, 7), 1),
            (13, date(2026, 10, 6), 2),
        ]
    finally:
        engine.dispose()
