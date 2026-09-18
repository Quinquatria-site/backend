"""All database access is confined to a disposable PostgreSQL container.

``postgres_url`` and ``migrated_url`` live in the repository root conftest so the
backoffice image tests share one container with these tests.
"""

from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from quinquatria_persistence import Database

from ._data import TABLES, VALID_ROWS, insert_row

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def alembic_config():
    return Config(str(ROOT / "alembic.ini"))


@pytest.fixture
def empty_database_url(postgres_url):
    """Give migration lifecycle tests their own blank database in the container."""
    name = f"migration_{uuid4().hex}"
    admin = create_engine(postgres_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield make_url(postgres_url).set(database=name)
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest_asyncio.fixture
async def database(migrated_url):
    database = Database(migrated_url)
    try:
        async with database.engine.begin() as connection:
            await connection.execute(
                text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE")
            )
        yield database
    finally:
        await database.dispose()


@pytest_asyncio.fixture
async def rows(database):
    async with database.engine.begin() as connection:
        ids = {
            table: await insert_row(connection, table, values)
            for table, values in VALID_ROWS.items()
        }
    return ids
