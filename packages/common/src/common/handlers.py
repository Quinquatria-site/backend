"""명세 §2.6의 오류 본문으로 변환하는 전역 예외 핸들러.

핸들러를 거치지 않는 응답 경로가 없어야 두 앱의 오류 계약이 갈라지지 않는다.
내부 예외 메시지, SQL, stack trace, 비밀값은 로그에만 남기고 응답에는 넣지
않는다.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.packages.common.src.common.errors import ApiError, ErrorCode, ErrorDetail

logger = logging.getLogger(__name__)

_JSON_SYNTAX_ERROR = "json_invalid"
_MALFORMED_JSON_MESSAGE = "JSON 구문이 올바르지 않습니다."

_STATUS_CODE: dict[int, ErrorCode] = {
    400: ErrorCode.INVALID_REQUEST,
    401: ErrorCode.INVALID_TOKEN,
    404: ErrorCode.RESOURCE_NOT_FOUND,
    409: ErrorCode.DELETE_CONFLICT,
    413: ErrorCode.IMAGE_TOO_LARGE,
    422: ErrorCode.VALIDATION_ERROR,
    429: ErrorCode.RATE_LIMIT_EXCEEDED,
}


def _response(error: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content=error.to_response().model_dump(mode="json"),
    )


def _field(location: tuple[int | str, ...]) -> str:
    """Pydantic의 `loc`을 요청 본문 기준 필드 경로로 바꾼다.

    첫 요소는 `query`, `body` 같은 위치 구분이라 제외한다.
    """
    path = location[1:] if len(location) > 1 else location
    return ".".join(str(part) for part in path)


async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
    return _response(exc)


async def handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """FastAPI가 요청 검증에 실패했을 때의 응답을 만든다.

    본문이 JSON으로 파싱되지 않는 경우도 같은 예외로 전달된다. 명세 §2.6은
    구문 오류를 400 INVALID_REQUEST로, 값 위반을 422 VALIDATION_ERROR로 나눠
    규정하므로 둘을 구분한다. 구문 오류의 `loc`은 문자 오프셋이라 클라이언트가
    고칠 필드를 가리키지 못하므로 `details`를 비운다.
    """
    errors = exc.errors()
    if any(error["type"] == _JSON_SYNTAX_ERROR for error in errors):
        return _response(
            ApiError(ErrorCode.INVALID_REQUEST, message=_MALFORMED_JSON_MESSAGE)
        )

    details = [
        ErrorDetail(field=_field(error["loc"]), reason=error["msg"]) for error in errors
    ]
    return _response(ApiError(ErrorCode.VALIDATION_ERROR, details=details))


async def handle_http_exception(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """FastAPI와 Starlette이 직접 발생시키는 HTTPException을 변환한다.

    404 Not Found나 405 Method Not Allowed처럼 라우팅 단계에서 나오는 응답이
    여기에 해당한다. 명세에 없는 상태는 원래 상태를 유지한 채 가장 가까운
    코드를 쓴다.
    """
    code = _STATUS_CODE.get(exc.status_code)
    if code is None:
        code = (
            ErrorCode.INVALID_REQUEST
            if exc.status_code < 500
            else ErrorCode.INTERNAL_SERVER_ERROR
        )
    error = ApiError(code)
    error.status_code = exc.status_code
    return _response(error)


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "처리되지 않은 예외: %s %s", request.method, request.url.path, exc_info=exc
    )
    return _response(ApiError(ErrorCode.INTERNAL_SERVER_ERROR))


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, handle_api_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(Exception, handle_unexpected_error)
