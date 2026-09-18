"""Customer 조회 API가 공유하는 SQL 실행 규칙."""

from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.pagination import Page
from common.query import PageQuery

POSTGRESQL_INTEGER_MAX = 2_147_483_647


def is_storable_id(resource_id: int) -> bool:
    """리소스 ID가 PostgreSQL INTEGER에 저장될 수 있는지 반환한다."""
    return resource_id <= POSTGRESQL_INTEGER_MAX


async def paginate[T: BaseModel](
    session: AsyncSession,
    statement: Select,
    query: PageQuery,
    model: type[T],
) -> Page[T]:
    """필터가 적용된 SELECT를 세고 안정적으로 한 페이지를 반환한다."""
    total = await session.scalar(
        select(func.count()).select_from(statement.order_by(None).subquery())
    )
    assert total is not None

    page = Page[T](items=[], page=query.page, size=query.size, total=total)
    offset = (query.page - 1) * query.size
    if offset < total:
        rows = await session.execute(statement.offset(offset).limit(query.size))
        page.items = [model.model_validate(row) for row in rows.mappings()]
    return page
