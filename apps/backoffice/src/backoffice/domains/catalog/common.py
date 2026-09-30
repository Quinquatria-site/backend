"""카테고리·장소·메뉴 라우트가 함께 쓰는 삭제·잠금 도우미."""

from collections.abc import Iterable
from datetime import UTC, datetime
from http import HTTPStatus

from fastapi import Response
from sqlalchemy import ColumnElement, false, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from backoffice.crud.resources import POSTGRESQL_INTEGER_MAX
from backoffice.images.service import detach
from common.errors import ApiError, ErrorCode
from quinquatria_persistence.models import Category, Place


def no_content() -> Response:
    """명세 §2.2대로 Content-Type 없는 빈 204."""
    return Response(status_code=HTTPStatus.NO_CONTENT)


async def detach_images(session: AsyncSession, image_ids: Iterable[int | None]) -> None:
    """삭제되는 리소스가 쓰던 이미지를 정리 대기열에 올린다."""
    ids = [image_id for image_id in image_ids if image_id is not None]
    if ids:
        await detach(session, image_ids=ids, now=datetime.now(UTC))


def id_equals(column: InstrumentedAttribute[int], value: int) -> ColumnElement[bool]:
    """목록 ID 필터. INTEGER를 넘는 값은 없는 ID로 보고 DB에 바인딩하지 않는다.

    psycopg dialect가 `::INTEGER` 캐스트를 붙여 범위 밖 값은 DB 오류(500)가 된다.
    """
    if value > POSTGRESQL_INTEGER_MAX:
        return false()
    return column == value


async def lock_parent(
    session: AsyncSession, model: type[Category] | type[Place], parent_id: int
) -> None:
    """참조할 상위 리소스를 `FOR KEY SHARE`로 잠근다. 없으면 404다.

    상위 삭제가 먼저 잡은 `FOR UPDATE`가 끝날 때까지 기다린 뒤 다시 읽으므로,
    삭제와 겹친 요청이 FK 위반(500) 대신 404로 끝난다.
    """
    if parent_id > POSTGRESQL_INTEGER_MAX:
        raise ApiError(ErrorCode.RESOURCE_NOT_FOUND)
    found = await session.scalar(
        select(model.id)
        .where(model.id == parent_id)
        .with_for_update(read=True, key_share=True)
    )
    if found is None:
        raise ApiError(ErrorCode.RESOURCE_NOT_FOUND)
