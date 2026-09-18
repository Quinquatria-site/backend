"""API 명세 §3.2, §3.3의 카테고리·장소·메뉴 조회 계약."""

from pydantic import BaseModel

from common.enums import CategoryCode, LanguageCode
from common.query import ListQuery
from common.types import AwareDatetime, Price, ResourceId


class PlaceListQuery(ListQuery):
    category_id: ResourceId | None = None


class CategoryResponse(BaseModel):
    id: ResourceId
    code: CategoryCode
    category_icon_uri: str | None
    language_code: LanguageCode
    name: str


class MenuResponse(BaseModel):
    id: ResourceId
    place_id: ResourceId
    image_url: str | None
    price: Price
    language_code: LanguageCode
    name: str
    description: str


class PlaceResponse(BaseModel):
    id: ResourceId
    category_id: ResourceId
    category_sequence: int
    x: float
    y: float
    start_hour: AwareDatetime
    end_hour: AwareDatetime
    place_image_uri: list[str] | None
    language_code: LanguageCode
    name: str
    host_college: str
    description: str


class PlaceDetailResponse(PlaceResponse):
    menus: list[MenuResponse]
