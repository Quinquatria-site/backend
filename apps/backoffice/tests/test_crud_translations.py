"""명세 §5.2의 번역 upsert와 언어별 삭제."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backoffice.crud.schemas import TranslationIn
from backoffice.crud.translations import delete_translation, upsert_translations
from common.errors import ApiError, ErrorCode
from quinquatria_persistence.enums import LanguageCode, NoticeType
from quinquatria_persistence.models import Notice, NoticeTranslation


class _NoticeTranslation(TranslationIn):
    title: str
    content: str


async def _seed(database, *languages: LanguageCode) -> int:
    async with database.transaction() as session:
        notice = Notice(
            type=NoticeType.GENERAL,
            translations=[
                NoticeTranslation(language_code=code, title=code.value, content="본문")
                for code in languages
            ],
        )
        session.add(notice)
        await session.flush()
        return notice.id


async def _translations(database, notice_id: int) -> list[NoticeTranslation]:
    async with database.session() as session:
        rows = await session.scalars(
            select(NoticeTranslation)
            .where(NoticeTranslation.notice_id == notice_id)
            .order_by(NoticeTranslation.language_code, NoticeTranslation.id)
        )
        return list(rows)


async def test_upsert_updates_in_place_and_inserts_missing(database) -> None:
    notice_id = await _seed(database, LanguageCode.KO, LanguageCode.CHN)
    before = {
        row.language_code: row.id for row in await _translations(database, notice_id)
    }

    async with database.transaction() as session:
        notice = await session.get(
            Notice, notice_id, options=[selectinload(Notice.translations)]
        )
        upsert_translations(
            notice.translations,
            [
                _NoticeTranslation(
                    language_code=LanguageCode.KO, title="새 제목", content="새 본문"
                ),
                _NoticeTranslation(
                    language_code=LanguageCode.EN, title="EN", content="body"
                ),
            ],
            NoticeTranslation,
        )

    after = await _translations(database, notice_id)
    assert [row.language_code for row in after] == [
        LanguageCode.CHN,
        LanguageCode.EN,
        LanguageCode.KO,
    ]
    by_code = {row.language_code: row for row in after}
    assert by_code[LanguageCode.KO].id == before[LanguageCode.KO]
    assert by_code[LanguageCode.KO].title == "새 제목"
    assert by_code[LanguageCode.CHN].id == before[LanguageCode.CHN]
    assert by_code[LanguageCode.CHN].title == "CHN"


async def _delete(database, notice_id: int, code: LanguageCode) -> None:
    async with database.transaction() as session:
        await delete_translation(
            session,
            owner=Notice,
            owner_id=notice_id,
            translation=NoticeTranslation,
            owner_fk=NoticeTranslation.notice_id,
            language_code=code,
        )


async def test_delete_removes_only_requested_language(database) -> None:
    notice_id = await _seed(database, LanguageCode.KO, LanguageCode.EN)

    await _delete(database, notice_id, LanguageCode.EN)

    assert [row.language_code for row in await _translations(database, notice_id)] == [
        LanguageCode.KO
    ]


@pytest.mark.parametrize(
    ("owner_exists", "code", "expected"),
    [
        (False, LanguageCode.EN, ErrorCode.RESOURCE_NOT_FOUND),
        (False, LanguageCode.KO, ErrorCode.RESOURCE_NOT_FOUND),
        (True, LanguageCode.KO, ErrorCode.DELETE_CONFLICT),
        (True, LanguageCode.CHN, ErrorCode.RESOURCE_NOT_FOUND),
    ],
    ids=["no-owner", "no-owner-ko", "ko", "missing-language"],
)
async def test_delete_errors(database, owner_exists, code, expected) -> None:
    notice_id = await _seed(database, LanguageCode.KO) if owner_exists else 999

    with pytest.raises(ApiError) as caught:
        await _delete(database, notice_id, code)

    assert caught.value.code is expected
