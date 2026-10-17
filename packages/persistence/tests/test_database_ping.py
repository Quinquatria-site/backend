"""헬스체크가 쓰는 `Database.ping()`."""

import pytest
from sqlalchemy.exc import OperationalError

from quinquatria_persistence import Database


async def test_ping_succeeds_against_a_reachable_database(database) -> None:
    await database.ping()


async def test_ping_raises_when_the_database_is_unreachable() -> None:
    # 1번 포트에는 PostgreSQL이 없다. Windows는 거부 응답 대신 재시도로
    # 오래 매달리므로 연결 제한 시간을 짧게 준다.
    unreachable = Database(
        "postgresql+psycopg://user:secret@127.0.0.1:1/missing?connect_timeout=1"
    )
    try:
        with pytest.raises(OperationalError):
            await unreachable.ping()
    finally:
        await unreachable.dispose()
