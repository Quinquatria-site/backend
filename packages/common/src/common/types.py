"""API 명세 §2.2가 정의한 공통 필드 타입.

ID는 1 이상의 정수, price는 원 단위의 0 이상 정수, datetime은 UTC offset이
포함된 ISO 8601 문자열이다.
"""

from typing import Annotated

from pydantic import AwareDatetime as _AwareDatetime
from pydantic import Field

type ResourceId = Annotated[int, Field(ge=1)]
"""1 이상의 정수인 리소스 ID."""

type Price = Annotated[int, Field(ge=0)]
"""원 단위의 0 이상 정수인 가격."""

type AwareDatetime = _AwareDatetime
"""UTC offset이 반드시 포함된 datetime. naive datetime은 거부한다."""
