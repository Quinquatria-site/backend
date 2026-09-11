import pytest

from backend.packages.common.src.common.errors import ApiError, ErrorCode, ErrorDetail, ErrorResponse

SPEC_STATUS = {
    ErrorCode.INVALID_REQUEST: 400,
    ErrorCode.INVALID_CREDENTIALS: 401,
    ErrorCode.INVALID_TOKEN: 401,
    ErrorCode.RESOURCE_NOT_FOUND: 404,
    ErrorCode.TRANSLATION_NOT_FOUND: 404,
    ErrorCode.DELETE_CONFLICT: 409,
    ErrorCode.IMAGE_ALREADY_ATTACHED: 409,
    ErrorCode.IMAGE_TOO_LARGE: 413,
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.INVALID_IMAGE: 422,
    ErrorCode.RATE_LIMIT_EXCEEDED: 429,
    ErrorCode.INTERNAL_SERVER_ERROR: 500,
}


def test_defines_every_code_in_the_spec() -> None:
    assert set(ErrorCode) == set(SPEC_STATUS)


@pytest.mark.parametrize(("code", "status"), SPEC_STATUS.items())
def test_code_maps_to_spec_status(code: ErrorCode, status: int) -> None:
    assert ApiError(code).status_code == status


@pytest.mark.parametrize("code", list(ErrorCode))
def test_every_code_has_a_default_message(code: ErrorCode) -> None:
    assert ApiError(code).message.strip()


def test_message_can_be_overridden() -> None:
    error = ApiError(ErrorCode.DELETE_CONFLICT, message="장소가 연결된 카테고리입니다.")

    assert error.message == "장소가 연결된 카테고리입니다."


def test_details_default_to_empty_list() -> None:
    assert ApiError(ErrorCode.RESOURCE_NOT_FOUND).details == []


def test_details_are_kept_in_order() -> None:
    details = [
        ErrorDetail(field="price", reason="0 이상의 정수여야 합니다."),
        ErrorDetail(field="size", reason="1 이상 100 이하여야 합니다."),
    ]

    assert ApiError(ErrorCode.VALIDATION_ERROR, details=details).details == details


def test_response_body_matches_the_spec_shape() -> None:
    error = ApiError(
        ErrorCode.VALIDATION_ERROR,
        message="요청 값이 유효하지 않습니다.",
        details=[ErrorDetail(field="price", reason="0 이상의 정수여야 합니다.")],
    )

    assert error.to_response().model_dump() == {
        "code": "VALIDATION_ERROR",
        "message": "요청 값이 유효하지 않습니다.",
        "details": [{"field": "price", "reason": "0 이상의 정수여야 합니다."}],
    }


def test_response_body_keeps_empty_details_array() -> None:
    body = ApiError(ErrorCode.RESOURCE_NOT_FOUND).to_response().model_dump()

    assert body["details"] == []


def test_response_is_serializable_without_details() -> None:
    assert (
        ErrorResponse(code=ErrorCode.INVALID_REQUEST, message="잘못된 요청").details
        == []
    )


def test_api_error_is_an_exception() -> None:
    with pytest.raises(ApiError):
        raise ApiError(ErrorCode.INTERNAL_SERVER_ERROR)
