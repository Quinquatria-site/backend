"""번역 upsert와 언어별 삭제 (명세 §5.2)."""

from collections.abc import Callable, Iterable, MutableSequence
from typing import Protocol

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from backoffice.crud.resources import get_or_404
from backoffice.crud.schemas import TranslationIn
from common.errors import ApiError, ErrorCode, ErrorDetail
from quinquatria_persistence.base import Base
from quinquatria_persistence.enums import LanguageCode


class TranslationRow(Protocol):
    language_code: LanguageCode


def upsert_translations[R: TranslationRow](
    existing: MutableSequence[R],
    items: Iterable[TranslationIn],
    factory: Callable[..., R],
) -> None:
    """전달된 언어만 update 또는 insert한다.

    기존 행은 객체를 그대로 두고 필드만 바꿔 번역 `id`와 FK를 유지한다.
    `existing`은 기본 리소스의 `translations` relationship을 로드해 넘긴다.
    """
    by_language = {row.language_code: row for row in existing}
    for item in items:
        fields = item.model_dump(exclude={"language_code"})
        row = by_language.get(item.language_code)
        if row is None:
            existing.append(factory(language_code=item.language_code, **fields))
        else:
            for name, value in fields.items():
                setattr(row, name, value)


async def delete_translation(
    session: AsyncSession,
    *,
    owner: type[Base],
    owner_id: int,
    translation: type[Base],
    owner_fk: InstrumentedAttribute[int],
    language_code: LanguageCode,
) -> None:
    """기본 리소스 없음 → 404, KO → 409, 번역 없음 → 404 순서로 판정한다."""
    await get_or_404(session, owner, owner_id)
    if language_code is LanguageCode.KO:
        raise ApiError(
            ErrorCode.DELETE_CONFLICT,
            message="KO 번역은 삭제할 수 없습니다.",
            details=[
                ErrorDetail(
                    field="language_code", reason="KO 번역은 모든 리소스에 필요합니다."
                )
            ],
        )

    result = await session.execute(
        delete(translation).where(
            owner_fk == owner_id,
            translation.language_code == language_code,  # type: ignore[attr-defined]
        )
    )
    if result.rowcount == 0:
        raise ApiError(ErrorCode.RESOURCE_NOT_FOUND)
