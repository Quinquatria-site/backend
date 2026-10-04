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
"""한 언어의 이미지 목록. 빈 배열 대신 `null`로 "이미지 없음"을 표현한다 (명세 §5.7)."""


class NoticeListQuery(PageQuery):
    type: NoticeType | None = None


class NoticeTranslationIn(TranslationIn):
    """언어별 제목·본문과 그 언어로 보여줄 이미지.

    `PATCH`에서 `notice_image_uri`를 생략하면 그 언어의 이미지를 유지하고,
    `null`을 보내면 모두 해제한다. 제목만 고치다 이미지가 지워지지 않게 한다.
    """

    title: RequiredLine
    content: RequiredText
    notice_image_uri: NoticeImageKeys | None = None


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
    notice_image_uri: list[str] | None


class NoticeOut(BaseModel):
    id: int
    type: NoticeType
    created_at: AwareDatetime
    translations: list[NoticeTranslationOut]
