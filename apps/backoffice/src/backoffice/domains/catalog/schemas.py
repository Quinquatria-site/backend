"""카테고리·장소·메뉴의 요청·응답 본문 (명세 §5.3~§5.5)."""

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
)

from backoffice.crud.resources import POSTGRESQL_INTEGER_MAX
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


class CategoryPatch(PatchModel):
    """`code`는 고정 목록의 식별자라 바꿀 수 없다 (명세 §5.3)."""

    NULLABLE = frozenset({"category_icon_uri"})

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


class VertexIn(RequestModel):
    x: Coordinate
    y: Coordinate


type Area = Annotated[list[VertexIn], Field(min_length=3)]
"""구역 꼭짓점. 첫 점을 끝에 반복하지 않아도 닫힌 다각형이다 (명세 §5.4)."""


PLACE_PAIRS = (("category_id", "category_sequence"), ("start_hour", "end_hour"))
"""함께 있거나 함께 비어야 하는 장소 필드 (명세 §5.4)."""

PLACE_SHAPE_FIELDS = ("is_polygon", "x", "y", "area")
"""위치 표현을 판정할 때 함께 보는 장소 필드 (명세 §5.4)."""


def _shape_errors(values: dict[str, object]) -> list[ErrorDetail]:
    """점 장소는 `x`·`y`만, 구역 장소는 `area`만 값이 있어야 한다."""
    if values["is_polygon"]:
        required, forbidden, kind = ("area",), ("x", "y"), "구역"
    else:
        required, forbidden, kind = ("x", "y"), ("area",), "점"
    return [
        ErrorDetail(field=field, reason=f"{kind} 장소에는 값이 필요합니다.")
        for field in required
        if values[field] is None
    ] + [
        ErrorDetail(field=field, reason=f"{kind} 장소에는 값을 둘 수 없습니다.")
        for field in forbidden
        if values[field] is not None
    ]


def ensure_place_rules(values: dict[str, object]) -> None:
    """요청 반영 후 장소 값으로 위치 표현·짝·시각 순서를 판정한다. 위반은 422다.

    `PATCH`는 일부만 보낼 수 있어 기존 값과 합친 결과로 판정해야 하므로,
    본문 검증기가 아니라 라우트에서 부른다.
    """
    shape = _shape_errors(values)
    if shape:
        raise ApiError(ErrorCode.VALIDATION_ERROR, details=shape)
    missing = [
        second if values[second] is None else first
        for first, second in PLACE_PAIRS
        if (values[first] is None) != (values[second] is None)
    ]
    if missing:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            details=[
                ErrorDetail(field=field, reason="짝을 이루는 값과 함께 보내야 합니다.")
                for field in missing
            ],
        )
    start_hour, end_hour = values["start_hour"], values["end_hour"]
    if start_hour is not None and end_hour < start_hour:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            details=[
                ErrorDetail(field="end_hour", reason="start_hour보다 이를 수 없습니다.")
            ],
        )


class PlaceTranslationIn(TranslationIn):
    """좌표 외에는 필수가 아니다. 비운 칸은 빈 문자열로 저장한다 (명세 §5.4)."""

    name: OptionalLine = ""
    host_college: OptionalLine = ""
    description: OptionalText = ""


class PlaceCreate(RequestModel):
    """위치만 필수다. 나머지는 생성 뒤 `PATCH`로 채울 수 있다 (명세 §5.4).

    점 장소는 `x`, `y`를, 구역 장소(`is_polygon: true`)는 `area`를 보낸다.
    """

    is_polygon: StrictBool = False
    x: Coordinate | None = None
    y: Coordinate | None = None
    area: Area | None = None
    category_id: ParentId | None = None
    category_sequence: Position | None = None
    start_hour: AwareDatetime | None = None
    end_hour: AwareDatetime | None = None
    place_image_uri: PlaceImageKeys | None = None
    translations: CreateTranslations[PlaceTranslationIn] | None = None


class PlaceTranslationOut(ResponseModel):
    id: int
    place_id: int
    language_code: LanguageCode
    name: str
    host_college: str
    description: str


class VertexOut(ResponseModel):
    x: float
    y: float


class PlaceOut(ResponseModel):
    id: int
    category_id: int | None
    category_sequence: int | None
    is_polygon: bool
    x: float | None
    y: float | None
    area: list[VertexOut] | None
    start_hour: UtcDatetime | None
    end_hour: UtcDatetime | None
    place_image_uri: list[str] | None
    translations: list[PlaceTranslationOut]


class PlacePatch(PatchModel):
    NULLABLE = frozenset(
        {
            "place_image_uri",
            "x",
            "y",
            "area",
            *(name for pair in PLACE_PAIRS for name in pair),
        }
    )

    category_id: ParentId | None = None
    category_sequence: Position | None = None
    is_polygon: StrictBool | None = None
    x: Coordinate | None = None
    y: Coordinate | None = None
    area: Area | None = None
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
