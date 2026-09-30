"""분실물 요청·응답 본문 (명세 §5.8)."""

from typing import ClassVar

from pydantic import BaseModel, StrictBool

from backoffice.crud.schemas import (
    CreateTranslations,
    OptionalLine,
    OptionalText,
    PatchModel,
    PatchTranslations,
    RequestModel,
    RequiredLine,
    TranslationIn,
)
from common.query import PageQuery
from common.types import AwareDatetime
from quinquatria_persistence.enums import LanguageCode


class LostItemQuery(PageQuery):
    """목록 필터. query string이라 `"true"`·`"false"`를 boolean으로 변환한다."""

    is_returned: bool | None = None


class LostItemTranslationIn(TranslationIn):
    title: RequiredLine
    description: OptionalText = ""
    found_location: OptionalLine = ""


class LostItemCreate(RequestModel):
    """`is_returned`는 JSON boolean만 받는다. `"true"`나 `1`은 422다."""

    image_url: str | None = None
    is_returned: StrictBool
    translations: CreateTranslations[LostItemTranslationIn]


class LostItemPatch(PatchModel):
    NULLABLE: ClassVar[frozenset[str]] = frozenset({"image_url"})

    image_url: str | None = None
    is_returned: StrictBool | None = None
    translations: PatchTranslations[LostItemTranslationIn] | None = None


class LostItemTranslationOut(BaseModel):
    id: int
    lost_item_id: int
    language_code: LanguageCode
    title: str
    description: str
    found_location: str


class LostItemOut(BaseModel):
    id: int
    image_url: str | None
    is_returned: bool
    created_at: AwareDatetime
    translations: list[LostItemTranslationOut]
