"""Run the shared PostgreSQL schema migrations from the repository root."""

import asyncio
import os
import selectors
import sys
from collections.abc import Callable
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import URL, Connection, make_url
from sqlalchemy.ext.asyncio import create_async_engine

from quinquatria_persistence import models  # noqa: F401
from quinquatria_persistence.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def database_url() -> URL:
    value = os.environ.get("DATABASE_URL")
    if not value:
        raise RuntimeError("DATABASE_URL is required to run migrations")
    url = make_url(value)
    if url.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}:
        raise ValueError("DATABASE_URL must use PostgreSQL with the psycopg driver")
    return url.set(drivername="postgresql+psycopg")


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _loop_factory() -> Callable[[], asyncio.AbstractEventLoop] | None:
    """Windows에서만 psycopg async 호환 루프 팩토리를 돌려준다.

    psycopg는 async 모드에서 Windows 기본 루프인 ProactorEventLoop 위를 돌 수
    없다. `alembic upgrade`는 pytest를 거치지 않고 이 파일을 직접 실행하므로
    (`conftest.py`의 pytest-asyncio 훅이 닿지 않는 경로다) 여기서도 같은 판단을
    따로 해줘야 한다. `WindowsSelectorEventLoopPolicy`는 Python 3.16에서 제거될
    예정이라 쓰지 않고, 루프를 직접 만들어 넘긴다. 다른 플랫폼은 None을 반환해
    `asyncio.run`의 기본 동작을 그대로 둔다.
    """
    if sys.platform != "win32":
        return None
    return lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())


async def run_async_migrations() -> None:
    engine = create_async_engine(
        database_url(), poolclass=pool.NullPool, hide_parameters=True
    )
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
elif (connection := config.attributes.get("connection")) is not None:
    # Async callers supply this connection inside AsyncConnection.run_sync().
    run_migrations(connection)
else:
    asyncio.run(run_async_migrations(), loop_factory=_loop_factory())
