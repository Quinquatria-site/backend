"""API 명세 §3.6의 분실물 조회 계약."""

from pydantic import BaseModel

from common.enums import LanguageCode
from common.query import ListQuery
from common.types import AwareDatetime, ResourceId


class LostItemListQuery(ListQuery):
    is_returned: bool | None = None


class LostItemResponse(BaseModel):
    id: ResourceId
    image_url: str | None
    is_returned: bool
    created_at: AwareDatetime
    language_code: LanguageCode
    title: str
    description: str
    found_location: str
