"""API 명세 §3.5의 공지 조회 계약."""

from pydantic import BaseModel

from common.enums import LanguageCode, NoticeType
from common.types import AwareDatetime, ResourceId


class NoticeResponse(BaseModel):
    id: ResourceId
    type: NoticeType
    created_at: AwareDatetime
    language_code: LanguageCode
    title: str
    content: str
