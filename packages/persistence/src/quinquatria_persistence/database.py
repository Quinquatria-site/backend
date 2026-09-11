"""Application-owned engines and explicit units of work."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class Database:
    """Own one engine per application, with a fresh session per operation.

    Pass the configured URL at application startup and await ``dispose()`` at
    shutdown. Importing this module neither reads configuration nor connects.
    Sessions must not be shared between concurrent tasks.
    """

    def __init__(self, url: str | URL) -> None:
        database_url = make_url(url)
        if database_url.drivername in {"postgres", "postgresql"}:
            database_url = database_url.set(drivername="postgresql+psycopg")
        if database_url.drivername != "postgresql+psycopg":
            raise ValueError("Database requires PostgreSQL with the psycopg driver")

        self.engine = create_async_engine(
            database_url,
            pool_pre_ping=True,
            hide_parameters=True,
        )
        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Provide a session without committing; close rolls back pending work."""
        async with self._sessions() as session:
            yield session

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        """Commit on success, roll back on failure, and always close the session.

        Pass this session to every operation in the unit of work. Operations
        must not commit independently or open a second transaction context.
        """
        async with self._sessions.begin() as session:
            yield session

    async def dispose(self) -> None:
        """Release the engine's connection pool during application shutdown."""
        await self.engine.dispose()
