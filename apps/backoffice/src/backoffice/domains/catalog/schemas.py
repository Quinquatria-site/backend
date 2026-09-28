"""카테고리·장소·메뉴의 요청·응답 본문 (명세 §5.3~§5.5)."""

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
)

from backoffice.crud.resources import POSTGRESQL_INTEGER_MAX
from backoffice.crud.schemas import (
    CreateTranslations,
    OptionalText,
    PatchModel,
    PatchTranslations,
    RequestModel,
    RequiredLine,
    TranslationIn,
)
from common.errors import ApiError, ErrorCode, ErrorDetail
from common.types import AwareDatetime
from quinquatria_persistence.enums import CategoryCode, LanguageCode


def by_language[T](translations: Iterable[T]) -> list[T]:
    """응답 번역 순서. 같은 세션에서 upsert한 뒤에는 로드 순서가 흐트러진다."""
    return sorted(translations, key=lambda row: (row.language_code, row.id))


type UtcDatetime = Annotated[
    datetime, AfterValidator(lambda value: value.astimezone(UTC))
]
"""응답 시각. 요청 offset이나 DB 세션 시간대와 무관하게 UTC로 맞춘다."""


class ResponseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CategoryTranslationIn(TranslationIn):
    name: RequiredLine


class CategoryCreate(RequestModel):
    code: CategoryCode
    category_icon_uri: str | None = None
    translations: CreateTranslations[CategoryTranslationIn]


class CategoryPatch(PatchModel):
    NULLABLE = frozenset({"category_icon_uri"})

    code: CategoryCode | None = None
    category_icon_uri: str | None = None
    translations: PatchTranslations[CategoryTranslationIn] | None = None


class CategoryTranslationOut(ResponseModel):
    id: int
    category_id: int
    language_code: LanguageCode
    name: str


class CategoryOut(ResponseModel):
    id: int
    code: CategoryCode
    category_icon_uri: str | None
    translations: list[CategoryTranslationOut]


type Coordinate = Annotated[StrictFloat, Field(allow_inf_nan=False)]
type Position = Annotated[StrictInt, Field(ge=1, le=POSTGRESQL_INTEGER_MAX)]
"""INTEGER 컬럼을 넘는 값이 DB 오류(500)가 되지 않게 상한도 둔다."""
type ParentId = Annotated[StrictInt, Field(ge=1)]
type PlaceImageKeys = Annotated[list[StrictStr], Field(min_length=1)]
"""빈 배열 대신 `null`로 "이미지 없음"을 표현한다 (명세 §5.4)."""


def ensure_hours_ordered(start_hour: datetime, end_hour: datetime) -> None:
    """같은 시각은 허용한다. 위반은 422 VALIDATION_ERROR다.

    `PATCH`는 한쪽만 보낼 수 있어 기존 값과 합친 결과로 판정해야 하므로,
    본문 검증기가 아니라 라우트에서 부른다.
    """
    if end_hour < start_hour:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            details=[
                ErrorDetail(field="end_hour", reason="start_hour보다 이를 수 없습니다.")
            ],
        )


class PlaceTranslationIn(TranslationIn):
    name: RequiredLine
    host_college: RequiredLine
    description: OptionalText = ""


class PlaceCreate(RequestModel):
    category_id: ParentId
    category_sequence: Position
    x: Coordinate
    y: Coordinate
    start_hour: AwareDatetime
    end_hour: AwareDatetime
    place_image_uri: PlaceImageKeys | None = None
    translations: CreateTranslations[PlaceTranslationIn]


class PlaceTranslationOut(ResponseModel):
    id: int
    place_id: int
    language_code: LanguageCode
    name: str
    host_college: str
    description: str


class PlaceOut(ResponseModel):
    id: int
    category_id: int
    category_sequence: int
    x: float
    y: float
    start_hour: UtcDatetime
    end_hour: UtcDatetime
    place_image_uri: list[str] | None
    translations: list[PlaceTranslationOut]


class PlacePatch(PatchModel):
    NULLABLE = frozenset({"place_image_uri"})

    category_id: ParentId | None = None
    category_sequence: Position | None = None
    x: Coordinate | None = None
    y: Coordinate | None = None
    start_hour: AwareDatetime | None = None
    end_hour: AwareDatetime | None = None
    place_image_uri: PlaceImageKeys | None = None
    translations: PatchTranslations[PlaceTranslationIn] | None = None


type Price = Annotated[StrictInt, Field(ge=0, le=POSTGRESQL_INTEGER_MAX)]


class MenuTranslationIn(TranslationIn):
    name: RequiredLine
    description: OptionalText = ""


class MenuCreate(RequestModel):
    place_id: ParentId
    image_url: str | None = None
    price: Price
    translations: CreateTranslations[MenuTranslationIn]


class MenuPatch(PatchModel):
    NULLABLE = frozenset({"image_url"})

    place_id: ParentId | None = None
    image_url: str | None = None
    price: Price | None = None
    translations: PatchTranslations[MenuTranslationIn] | None = None


class MenuTranslationOut(ResponseModel):
    id: int
    menu_id: int
    language_code: LanguageCode
    name: str
    description: str


class MenuOut(ResponseModel):
    id: int
    place_id: int
    image_url: str | None
    price: int
    translations: list[MenuTranslationOut]
