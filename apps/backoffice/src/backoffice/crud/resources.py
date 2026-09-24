"""기본 리소스 단건 조회와 목록 페이지네이션 (명세 §2.5, §5.1)."""

from collections.abc import Awaitable, Callable, Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.interfaces import ORMOption

from common.errors import ApiError, ErrorCode
from common.pagination import Page
from common.query import PageQuery
from quinquatria_persistence.base import Base

POSTGRESQL_INTEGER_MAX = 2_147_483_647


async def get_or_404[M: Base](
    session: AsyncSession,
    model: type[M],
    resource_id: int,
    *options: ORMOption,
    for_update: bool = False,
) -> M:
    """INTEGER 범위를 넘는 ID는 DB에 묻지 않고 404로 처리한다."""
    if resource_id > POSTGRESQL_INTEGER_MAX:
        raise ApiError(ErrorCode.RESOURCE_NOT_FOUND)
    entity = await session.get(
        model, resource_id, options=options, with_for_update=for_update
    )
    if entity is None:
        raise ApiError(ErrorCode.RESOURCE_NOT_FOUND)
    return entity


async def paginate[M: Base, T](
    session: AsyncSession,
    statement: Select[tuple[M]],
    query: PageQuery,
    serialize: Callable[[Sequence[M]], Awaitable[Sequence[T]]],
) -> Page[T]:
    """필터·정렬이 적용된 엔티티 SELECT를 세고 한 페이지를 직렬화한다.

    `serialize`는 한 페이지의 엔티티를 한꺼번에 받는다. 이미지 key처럼 추가
    조회가 필요한 값을 행마다가 아니라 페이지 단위로 모아 읽기 위해서다.
    """
    total = await session.scalar(
        select(func.count()).select_from(statement.order_by(None).subquery())
    )
    assert total is not None

    items: Sequence[T] = []
    offset = (query.page - 1) * query.size
    if offset < total:
        rows = (await session.scalars(statement.offset(offset).limit(query.size))).all()
        items = await serialize(rows)
    return Page[T](items=list(items), page=query.page, size=query.size, total=total)
