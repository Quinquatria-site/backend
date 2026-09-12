"""API 명세 §2.5가 정의한 목록 응답 구조."""

from pydantic import BaseModel, Field

from common.query import MAX_SIZE, MIN_PAGE, MIN_SIZE


class Page[T](BaseModel):
    """모든 목록 API가 반환하는 페이지네이션 응답.

    `total`은 번역과 필터 조건을 모두 적용한 뒤의 전체 개수다. `page`가 마지막
    페이지를 초과하면 `items`가 빈 배열이고 `total`은 그대로 전체 개수다.
    """

    items: list[T]
    page: int = Field(ge=MIN_PAGE)
    size: int = Field(ge=MIN_SIZE, le=MAX_SIZE)
    total: int = Field(ge=0)
