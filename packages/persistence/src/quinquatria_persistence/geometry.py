"""PostgreSQL 기본 `polygon` 타입과 Python 꼭짓점 목록의 변환.

psycopg에는 `polygon` 어댑터가 없어 값이 텍스트(`((x1,y1),(x2,y2),...)`)로
오간다. 이 모듈이 그 텍스트와 `Vertex` 목록을 서로 바꾼다. 연결마다 타입을
등록할 필요가 없어 async 엔진의 연결 수명과 무관하게 동작한다.
"""

import re
from collections.abc import Iterable
from typing import NamedTuple

from sqlalchemy import cast
from sqlalchemy.dialects.postgresql import base as postgresql_base
from sqlalchemy.types import UserDefinedType


class Vertex(NamedTuple):
    x: float
    y: float


_POINT = re.compile(r"\(\s*([^(),\s]+)\s*,\s*([^(),\s]+)\s*\)")


def format_polygon(vertices: Iterable[tuple[float, float]]) -> str:
    # repr(float)은 가장 짧은 왕복 표현이라 DB에 넣고 읽어도 값이 바뀌지 않는다.
    return "(" + ",".join(f"({float(x)!r},{float(y)!r})" for x, y in vertices) + ")"


def parse_polygon(value: str) -> list[Vertex]:
    return [Vertex(float(x), float(y)) for x, y in _POINT.findall(value)]


class Polygon(UserDefinedType[list[Vertex]]):
    """닫힌 다각형. 첫 꼭짓점을 끝에 반복하지 않는다 (PostgreSQL이 닫는다)."""

    cache_ok = True

    def get_col_spec(self, **kw: object) -> str:
        return "POLYGON"

    def bind_expression(self, bindvalue):
        # 문자열 파라미터가 text로 바인딩돼도 polygon으로 해석되게 한다.
        return cast(bindvalue, self)

    def bind_processor(self, dialect):
        def process(value):
            return None if value is None else format_polygon(value)

        return process

    def result_processor(self, dialect, coltype):
        def process(value):
            return None if value is None else parse_polygon(value)

        return process


# 반영(reflection)이 polygon 열을 알아보게 한다. 없으면 `alembic check`가 이 열의
# 타입을 판정하지 못하고 경고만 남긴다.
postgresql_base.ischema_names["polygon"] = Polygon
