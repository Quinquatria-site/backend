"""명세 §5.2의 생성·수정 요청 본문 규칙.

모든 요청 모델은 `extra="forbid"`를 쓴다. 서버 생성 필드나 명세에 없는
필드를 보내면 422 VALIDATION_ERROR다.

모델 전체에 `strict=True`를 걸지 않는다. FastAPI는 본문을 Python mode로
검증하므로 enum·datetime 문자열까지 거부된다. `"true"`나 `1`을 boolean으로
받는 암묵 변환은 필드에 `StrictBool`, `StrictInt`를 써서 막는다.
"""

from collections.abc import Sequence
from typing import Annotated, ClassVar, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, model_validator

from quinquatria_persistence.enums import LanguageCode


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TranslationIn(RequestModel):
    """번역 항목 하나. 필드는 리소스별 하위 클래스가 더한다.

    번역은 전체 교체이므로 선택 필드의 기본값은 빈 문자열로 둔다.
    """

    language_code: LanguageCode


def _unique_languages[T: TranslationIn](items: Sequence[T]) -> Sequence[T]:
    codes = [item.language_code for item in items]
    if len(set(codes)) != len(codes):
        raise ValueError("language_code must not repeat")
    return items


def _exactly_one_ko[T: TranslationIn](items: Sequence[T]) -> Sequence[T]:
    if sum(item.language_code is LanguageCode.KO for item in items) != 1:
        raise ValueError("exactly one KO translation is required")
    return items


def _not_empty[T: TranslationIn](items: Sequence[T]) -> Sequence[T]:
    if not items:
        raise ValueError("translations must not be empty")
    return items


type CreateTranslations[T: TranslationIn] = Annotated[
    list[T], AfterValidator(_unique_languages), AfterValidator(_exactly_one_ko)
]
"""`POST` 번역 배열. KO 정확히 1개, 언어 중복 금지."""

type PatchTranslations[T: TranslationIn] = Annotated[
    list[T], AfterValidator(_not_empty), AfterValidator(_unique_languages)
]
"""`PATCH` 번역 배열. 빈 배열 금지, 언어 중복 금지, KO 생략 허용."""


class PatchModel(RequestModel):
    """`PATCH` 본문. 모든 필드를 `X | None = None`으로 선언한다.

    `None` 기본값은 "생략"을 뜻하고 실제 전달 여부는 `model_fields_set`으로
    구분한다. 명시적 `null`은 `NULLABLE`에 적은 필드(이미지 연결 해제)에만
    허용한다.
    """

    NULLABLE: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _require_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        for name in self.model_fields_set:
            if getattr(self, name) is None and name not in self.NULLABLE:
                raise ValueError(f"{name} must not be null")
        return self

    def changes(self) -> dict[str, object]:
        """전달된 기본 필드만. `translations`는 upsert로 따로 처리한다."""
        return {
            name: getattr(self, name)
            for name in self.model_fields_set
            if name != "translations"
        }
