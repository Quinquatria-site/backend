"""명세 §5.7의 공지 요청·응답 본문."""

from pydantic import AwareDatetime, BaseModel

from backoffice.crud.schemas import (
    CreateTranslations,
    PatchModel,
    PatchTranslations,
    RequestModel,
    RequiredLine,
    RequiredText,
    TranslationIn,
)
from common.query import PageQuery
from quinquatria_persistence.enums import LanguageCode, NoticeType


class NoticeListQuery(PageQuery):
    type: NoticeType | None = None


class NoticeTranslationIn(TranslationIn):
    title: RequiredLine
    content: RequiredText


class NoticeCreate(RequestModel):
    """`id`, `created_at`은 서버가 만든다. 보내면 extra 필드로 422다."""

    type: NoticeType
    translations: CreateTranslations[NoticeTranslationIn]


class NoticePatch(PatchModel):
    type: NoticeType | None = None
    translations: PatchTranslations[NoticeTranslationIn] | None = None


class NoticeTranslationOut(BaseModel):
    id: int
    notice_id: int
    language_code: LanguageCode
    title: str
    content: str


class NoticeOut(BaseModel):
    id: int
    type: NoticeType
    created_at: AwareDatetime
    translations: list[NoticeTranslationOut]
