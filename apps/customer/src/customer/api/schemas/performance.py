"""API 명세 §3.4의 Customer 공연 조회 계약."""

import re
from datetime import date as DateValue
from typing import Annotated

from pydantic import BaseModel, Field, field_validator

from common.enums import LanguageCode, PerformanceType
from common.query import ListQuery
from common.types import ResourceId

_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


class PerformanceListQuery(ListQuery):
    type: PerformanceType | None = None
    date: DateValue | None = None

    @field_validator("date", mode="before")
    @classmethod
    def require_iso_local_date(cls, value: object) -> object:
        """Reject Pydantic's datetime and numeric-to-date coercions."""
        if value is not None and (
            not isinstance(value, str) or _DATE_PATTERN.fullmatch(value) is None
        ):
            raise ValueError("date must use YYYY-MM-DD format")
        return value


class PerformanceResponse(BaseModel):
    id: ResourceId
    type: PerformanceType
    image_uri: str | None
    date: DateValue
    seq: Annotated[int, Field(ge=1)]
    is_live: bool
    language_code: LanguageCode
    title: str
    description: str
