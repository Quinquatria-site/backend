"""API 명세 §2.6이 정의한 오류 코드와 응답 계약.

응답 본문에는 내부 예외 메시지, SQL, stack trace, 비밀값을 포함하지 않는다.
"""

from collections.abc import Mapping
from enum import StrEnum
from http import HTTPStatus

from pydantic import BaseModel, Field


class ErrorCode(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    INVALID_TOKEN = "INVALID_TOKEN"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    TRANSLATION_NOT_FOUND = "TRANSLATION_NOT_FOUND"
    DELETE_CONFLICT = "DELETE_CONFLICT"
    IMAGE_ALREADY_ATTACHED = "IMAGE_ALREADY_ATTACHED"
    IMAGE_TOO_LARGE = "IMAGE_TOO_LARGE"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_IMAGE = "INVALID_IMAGE"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"


_STATUS: dict[ErrorCode, int] = {
    ErrorCode.INVALID_REQUEST: HTTPStatus.BAD_REQUEST,
    ErrorCode.INVALID_CREDENTIALS: HTTPStatus.UNAUTHORIZED,
    ErrorCode.INVALID_TOKEN: HTTPStatus.UNAUTHORIZED,
    ErrorCode.RESOURCE_NOT_FOUND: HTTPStatus.NOT_FOUND,
    ErrorCode.TRANSLATION_NOT_FOUND: HTTPStatus.NOT_FOUND,
    ErrorCode.DELETE_CONFLICT: HTTPStatus.CONFLICT,
    ErrorCode.IMAGE_ALREADY_ATTACHED: HTTPStatus.CONFLICT,
    ErrorCode.IMAGE_TOO_LARGE: HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
    ErrorCode.VALIDATION_ERROR: HTTPStatus.UNPROCESSABLE_ENTITY,
    ErrorCode.INVALID_IMAGE: HTTPStatus.UNPROCESSABLE_ENTITY,
    ErrorCode.RATE_LIMIT_EXCEEDED: HTTPStatus.TOO_MANY_REQUESTS,
    ErrorCode.INTERNAL_SERVER_ERROR: HTTPStatus.INTERNAL_SERVER_ERROR,
}

_MESSAGE: dict[ErrorCode, str] = {
    ErrorCode.INVALID_REQUEST: "요청을 처리할 수 없습니다.",
    ErrorCode.INVALID_CREDENTIALS: "인증에 실패했습니다.",
    ErrorCode.INVALID_TOKEN: "유효하지 않은 토큰입니다.",
    ErrorCode.RESOURCE_NOT_FOUND: "요청한 리소스를 찾을 수 없습니다.",
    ErrorCode.TRANSLATION_NOT_FOUND: "요청한 언어의 번역이 없습니다.",
    ErrorCode.DELETE_CONFLICT: "하위 리소스가 있어 삭제할 수 없습니다.",
    ErrorCode.IMAGE_ALREADY_ATTACHED: "다른 리소스가 사용 중인 이미지입니다.",
    ErrorCode.IMAGE_TOO_LARGE: "허용 크기를 초과한 이미지입니다.",
    ErrorCode.VALIDATION_ERROR: "요청 값이 유효하지 않습니다.",
    ErrorCode.INVALID_IMAGE: "이미지 검증에 실패했습니다.",
    ErrorCode.RATE_LIMIT_EXCEEDED: "요청이 너무 잦습니다. 잠시 후 다시 시도해 주세요.",
    ErrorCode.INTERNAL_SERVER_ERROR: "서버 내부 오류가 발생했습니다.",
}


class ErrorDetail(BaseModel):
    """오류의 추가 정보 한 건."""

    field: str
    reason: str


class ErrorResponse(BaseModel):
    """모든 오류 응답의 본문."""

    code: ErrorCode
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)


class ApiError(Exception):
    """명세의 오류 응답으로 변환되는 예외.

    `code`가 HTTP 상태와 기본 메시지를 결정한다. 사용자에게 보여줄 구체적인
    설명이 있으면 `message`로 덮어쓴다.

    `headers`는 405의 `Allow`처럼 상태 코드와 함께 보내야 하는 헤더를 싣는다.
    전송 계층에만 쓰이고 §2.6 본문에는 들어가지 않는다.
    """

    def __init__(
        self,
        code: ErrorCode,
        *,
        message: str | None = None,
        details: list[ErrorDetail] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.code = code
        self.status_code = _STATUS[code]
        self.message = message if message is not None else _MESSAGE[code]
        self.details = details if details is not None else []
        self.headers = dict(headers) if headers else None
        super().__init__(self.message)

    def to_response(self) -> ErrorResponse:
        return ErrorResponse(code=self.code, message=self.message, details=self.details)
