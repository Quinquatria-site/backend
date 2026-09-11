"""API 명세 §2.4, §2.5가 정의한 query parameter 계약.

모든 모델이 `extra="forbid"`를 쓴다. 명세에 없는 query parameter를 전달하면
Pydantic이 검증 오류를 내고, 전역 핸들러가 이를 422 VALIDATION_ERROR로
변환한다. 엔드포인트는 받는 query가 없더라도 `NoQuery`를 선언해야 이 규칙이
적용된다.
"""

from pydantic import BaseModel, ConfigDict, Field

from common.enums import LanguageCode

MIN_PAGE = 1
DEFAULT_PAGE = 1
MIN_SIZE = 1
MAX_SIZE = 100
DEFAULT_SIZE = 20


class NoQuery(BaseModel):
    """query parameter를 하나도 받지 않는 엔드포인트."""

    model_config = ConfigDict(extra="forbid")


class LanguageQuery(NoQuery):
    """번역 언어만 선택하는 Customer 단건 조회."""

    language_code: LanguageCode = LanguageCode.KO


class PageQuery(NoQuery):
    """언어 평탄화가 없는 Backoffice 목록 조회."""

    page: int = Field(DEFAULT_PAGE, ge=MIN_PAGE)
    size: int = Field(DEFAULT_SIZE, ge=MIN_SIZE, le=MAX_SIZE)


class ListQuery(LanguageQuery, PageQuery):
    """언어와 페이지를 함께 받는 Customer 목록 조회."""
