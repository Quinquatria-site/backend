"""공연 저장과 일차 내 순서(`seq`) 관리 (명세 §5.6, §6).

`seq`나 `is_live`를 바꿀 수 있는 쓰기는 모두 `lock_ordering`을 먼저 잡는다.
같은 일차에 동시에 생성하면 둘 다 같은 `max(seq) + 1`을 읽어 commit 시 unique
위반(500)이 나고, 동시 live 지정은 live 공연을 여러 건 남긴다. 그래서
transaction 단위 advisory lock으로 공연 쓰기를 직렬화한다.
"""

from collections.abc import Sequence
from datetime import date as DateValue

from sqlalchemy import case, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backoffice.crud.images import image_keys, replace_image
from backoffice.crud.resources import get_or_404, paginate
from backoffice.crud.translations import delete_translation as crud_delete_translation
from backoffice.crud.translations import upsert_translations
from backoffice.domains.performances.schemas import (
    PerformanceCreate,
    PerformanceListQuery,
    PerformanceOut,
    PerformancePatch,
    PerformanceTranslationOut,
)
from backoffice.images.store import ObjectStore
from common.errors import ApiError, ErrorCode, ErrorDetail
from common.pagination import Page
from quinquatria_persistence.enums import ImageResourceType, LanguageCode
from quinquatria_persistence.models import Performance, PerformanceTranslation

_ORDERING_LOCK_KEY = 0x5045_5246
"""`pg_advisory_xact_lock` key. 다른 도메인의 key와 겹치지 않게 "PERF"로 둔다."""

IMAGE_TYPE = ImageResourceType.PERFORMANCE_IMAGE


async def lock_ordering(session: AsyncSession) -> None:
    """commit·rollback까지 다른 공연 쓰기를 기다리게 한다.

    일차별 행 잠금은 빈 일차의 첫 생성을 막지 못하고, 일차 여러 개를 잡는
    `PATCH`는 교착 위험이 있다. 공연 쓰기는 운영자 작업이라 전역 직렬화로 충분하다.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": _ORDERING_LOCK_KEY}
    )


async def get_performance(session: AsyncSession, performance_id: int) -> Performance:
    return await get_or_404(
        session,
        Performance,
        performance_id,
        selectinload(Performance.translations),
    )


async def list_performances(
    session: AsyncSession, query: PerformanceListQuery
) -> Page[PerformanceOut]:
    statement = (
        select(Performance)
        .options(selectinload(Performance.translations))
        .order_by(Performance.date, Performance.seq, Performance.id)
    )
    if query.type is not None:
        statement = statement.where(Performance.type == query.type)
    if query.date is not None:
        statement = statement.where(Performance.date == query.date)
    return await paginate(
        session, statement, query, lambda rows: serialize(session, rows)
    )


async def next_seq(session: AsyncSession, day: DateValue) -> int:
    current = await session.scalar(
        select(func.max(Performance.seq)).where(Performance.date == day)
    )
    return (current or 0) + 1


async def create_performance(
    session: AsyncSession,
    store: ObjectStore,
    payload: PerformanceCreate,
    *,
    max_image_bytes: int,
) -> Performance:
    await lock_ordering(session)
    performance = Performance(
        type=payload.type,
        date=payload.date,
        seq=await next_seq(session, payload.date),
        is_live=False,
        translations=[],
    )
    performance.image_id = await replace_image(
        session,
        store,
        current_image_id=None,
        object_key=payload.image_uri,
        resource_type=IMAGE_TYPE,
        max_bytes=max_image_bytes,
    )
    upsert_translations(
        performance.translations, payload.translations, PerformanceTranslation
    )
    session.add(performance)
    await session.flush()
    return performance


async def renumber(session: AsyncSession, day: DateValue) -> None:
    """공연이 빠진 일차의 남은 공연에 기존 순서대로 `1`부터 다시 매긴다."""
    ranked = (
        select(
            Performance.id,
            func.row_number()
            .over(order_by=(Performance.seq, Performance.id))
            .label("position"),
        )
        .where(Performance.date == day)
        .subquery()
    )
    await session.execute(
        update(Performance)
        .where(Performance.id == ranked.c.id, Performance.seq != ranked.c.position)
        .values(seq=ranked.c.position)
        .execution_options(synchronize_session="fetch")
    )


async def update_performance(
    session: AsyncSession,
    store: ObjectStore,
    performance_id: int,
    payload: PerformancePatch,
    *,
    max_image_bytes: int,
) -> Performance:
    await lock_ordering(session)
    performance = await get_performance(session, performance_id)
    if payload.type is not None:
        performance.type = payload.type
    if payload.date is not None and payload.date != performance.date:
        source = performance.date
        performance.seq = await next_seq(session, payload.date)
        performance.date = payload.date
        await session.flush()
        await renumber(session, source)
    if "image_uri" in payload.model_fields_set:
        performance.image_id = await replace_image(
            session,
            store,
            current_image_id=performance.image_id,
            object_key=payload.image_uri,
            resource_type=IMAGE_TYPE,
            max_bytes=max_image_bytes,
        )
    if payload.translations is not None:
        upsert_translations(
            performance.translations, payload.translations, PerformanceTranslation
        )
    await session.flush()
    return performance


async def set_live(
    session: AsyncSession, performance_id: int, is_live: bool
) -> Performance:
    """`true`면 다른 live 공연을 내리고 이 공연만 올린다."""
    await lock_ordering(session)
    performance = await get_performance(session, performance_id)
    if is_live:
        await session.execute(
            update(Performance)
            .where(Performance.is_live, Performance.id != performance.id)
            .values(is_live=False)
            .execution_options(synchronize_session="fetch")
        )
    performance.is_live = is_live
    await session.flush()
    return performance


async def reorder(session: AsyncSession, day: DateValue, order: list[int]) -> None:
    """`order`가 그 일차의 공연 ID 집합과 정확히 같을 때만 순서를 바꾼다.

    어긋나면 다른 운영자의 동시 추가·삭제로 보고 거부한다 (명세 §5.6).
    """
    await lock_ordering(session)
    current = set(
        (
            await session.scalars(select(Performance.id).where(Performance.date == day))
        ).all()
    )
    if len(set(order)) != len(order) or set(order) != current:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            details=[
                ErrorDetail(
                    field="order",
                    reason="해당 일차의 공연 ID를 빠짐없이 중복 없이 담아야 합니다.",
                )
            ],
        )
    positions = {performance_id: seq for seq, performance_id in enumerate(order, 1)}
    await session.execute(
        update(Performance)
        .where(Performance.id.in_(order))
        .values(seq=case(positions, value=Performance.id))
        .execution_options(synchronize_session="fetch")
    )


async def delete_performance(
    session: AsyncSession,
    store: ObjectStore,
    performance_id: int,
    *,
    max_image_bytes: int,
) -> None:
    """이미지는 `DETACHED`로 넘기고, 번역은 FK `ON DELETE CASCADE`로 지운다."""
    await lock_ordering(session)
    performance = await get_or_404(session, Performance, performance_id)
    day = performance.date
    await replace_image(
        session,
        store,
        current_image_id=performance.image_id,
        object_key=None,
        resource_type=IMAGE_TYPE,
        max_bytes=max_image_bytes,
    )
    await session.delete(performance)
    await session.flush()
    await renumber(session, day)


async def delete_translation(
    session: AsyncSession, performance_id: int, language_code: LanguageCode
) -> None:
    await crud_delete_translation(
        session,
        owner=Performance,
        owner_id=performance_id,
        translation=PerformanceTranslation,
        owner_fk=PerformanceTranslation.performance_id,
        language_code=language_code,
    )


async def serialize(
    session: AsyncSession, performances: Sequence[Performance]
) -> list[PerformanceOut]:
    """이미지 key를 한 번에 읽고, 번역은 `language_code, id` 순으로 정렬한다.

    같은 세션에서 upsert한 직후에는 relationship 목록이 다시 정렬되지 않는다.
    """
    keys = await image_keys(session, (p.image_id for p in performances))
    return [
        PerformanceOut(
            id=performance.id,
            type=performance.type,
            image_uri=keys.get(performance.image_id)
            if performance.image_id is not None
            else None,
            date=performance.date,
            seq=performance.seq,
            is_live=performance.is_live,
            translations=[
                PerformanceTranslationOut(
                    id=translation.id,
                    performance_id=translation.performance_id,
                    language_code=translation.language_code,
                    title=translation.title,
                    description=translation.description,
                )
                for translation in sorted(
                    performance.translations,
                    key=lambda row: (row.language_code.value, row.id),
                )
            ],
        )
        for performance in performances
    ]


async def serialize_one(
    session: AsyncSession, performance: Performance
) -> PerformanceOut:
    return (await serialize(session, [performance]))[0]
