"""공연 요청·응답 본문 (명세 §5.6).

`seq`와 `is_live`는 서버가 정한다. 요청 모델에 선언하지 않으므로
`extra="forbid"`가 두 필드를 422로 거부한다.
"""

import re
from datetime import date as DateValue
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, Field, StrictBool, StrictInt

from backoffice.crud.schemas import (
    CreateTranslations,
    OptionalText,
    PatchModel,
    PatchTranslations,
    RequestModel,
    RequiredLine,
    TranslationIn,
)
from common.query import PageQuery
from quinquatria_persistence.enums import LanguageCode, PerformanceType

_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


def _require_iso_local_date(value: object) -> object:
    """Pydantic의 datetime·숫자→date 변환을 막고 `YYYY-MM-DD`만 받는다."""
    if not isinstance(value, str) or _DATE_PATTERN.fullmatch(value) is None:
        raise ValueError("date must use YYYY-MM-DD format")
    return value


type FestivalDate = Annotated[DateValue, BeforeValidator(_require_iso_local_date)]


class PerformanceListQuery(PageQuery):
    type: PerformanceType | None = None
    date: FestivalDate | None = None


class PerformanceTranslationIn(TranslationIn):
    title: RequiredLine
    description: OptionalText = ""


class PerformanceCreate(RequestModel):
    type: PerformanceType
    image_uri: str | None = None
    date: FestivalDate
    translations: CreateTranslations[PerformanceTranslationIn]


class PerformancePatch(PatchModel):
    NULLABLE = frozenset({"image_uri"})

    type: PerformanceType | None = None
    image_uri: str | None = None
    date: FestivalDate | None = None
    translations: PatchTranslations[PerformanceTranslationIn] | None = None


class LiveUpdate(RequestModel):
    is_live: StrictBool


class ReorderRequest(RequestModel):
    """`order` 위치가 곧 `seq`다. 집합 일치는 DB를 봐야 하므로 서비스가 검사한다."""

    date: FestivalDate
    order: Annotated[list[Annotated[StrictInt, Field(ge=1)]], Field(min_length=1)]


class PerformanceTranslationOut(BaseModel):
    id: int
    performance_id: int
    language_code: LanguageCode
    title: str
    description: str


class PerformanceOut(BaseModel):
    id: int
    type: PerformanceType
    image_uri: str | None
    date: DateValue
    seq: int
    is_live: bool
    translations: list[PerformanceTranslationOut]
