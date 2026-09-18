"""로그에 남기기 전에 presigned URL에서 권한 부분을 지운다.

파라미터를 골라 지우지 않고 query string 전체를 버린다. 고르는 방식은 새
서명 파라미터가 생기면 조용히 새기 시작한다.
"""


def mask_presigned_url(url: str) -> str:
    """object key까지만 남기고 query string을 지운다."""
    base, separator, _ = url.partition("?")
    return f"{base}?<redacted>" if separator else base
