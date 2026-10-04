"""API 명세 §3.2, §3.3의 카테고리·장소·메뉴 조회 계약."""

from pydantic import BaseModel, ConfigDict

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


class VertexResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    x: float
    y: float


class PlaceResponse(BaseModel):
    """위치만 있는 장소도 빈 마커로 내보낸다. 아직 채우지 않은 값은 `null`이다.

    점 장소는 `x`, `y`가, 구역 장소(`is_polygon`)는 `area`가 위치다.
    """

    id: ResourceId
    category_id: ResourceId | None
    category_sequence: int | None
    is_polygon: bool
    x: float | None
    y: float | None
    area: list[VertexResponse] | None
    start_hour: AwareDatetime | None
    end_hour: AwareDatetime | None
    place_image_uri: list[str] | None
    language_code: LanguageCode | None
    name: str | None
    host_college: str | None
    description: str | None


class PlaceDetailResponse(PlaceResponse):
    menus: list[MenuResponse]
