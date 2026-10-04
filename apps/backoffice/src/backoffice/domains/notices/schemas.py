"""명세 §5.7의 공지 요청·응답 본문."""

from typing import Annotated

from pydantic import AwareDatetime, BaseModel, Field, StrictStr

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

type NoticeImageKeys = Annotated[list[StrictStr], Field(min_length=1)]
"""빈 배열 대신 `null`로 "이미지 없음"을 표현한다 (명세 §5.7)."""


class NoticeListQuery(PageQuery):
    type: NoticeType | None = None


class NoticeTranslationIn(TranslationIn):
    title: RequiredLine
    content: RequiredText


class NoticeCreate(RequestModel):
    """`id`, `created_at`은 서버가 만든다. 보내면 extra 필드로 422다."""

    type: NoticeType
    notice_image_uri: NoticeImageKeys | None = None
    translations: CreateTranslations[NoticeTranslationIn]


class NoticePatch(PatchModel):
    NULLABLE = frozenset({"notice_image_uri"})

    type: NoticeType | None = None
    notice_image_uri: NoticeImageKeys | None = None
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
    notice_image_uri: list[str] | None
    translations: list[NoticeTranslationOut]
