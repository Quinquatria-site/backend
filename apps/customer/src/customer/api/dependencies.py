"""요청마다 독립적인 데이터베이스 세션을 제공한다."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from quinquatria_persistence import Database


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    database: Database = request.app.state.database
    async with database.session() as session:
        yield session


type ReadSession = Annotated[AsyncSession, Depends(get_session)]
