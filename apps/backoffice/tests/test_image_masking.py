"""presigned URL의 query string은 만료 전까지 업로드 권한 그 자체다.

로그에 남으면 그 key에 누구나 쓸 수 있다. 명세 §4.5가 마스킹을 요구한다.
"""

from backoffice.images.masking import mask_presigned_url

SIGNED = (
    "https://bucket.s3.ap-northeast-2.amazonaws.com/images/place/a.webp"
    "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=AKIA%2F20261006"
    "&X-Amz-Signature=deadbeef&X-Amz-SignedHeaders=content-type%3Bhost"
)


def test_signature_is_removed() -> None:
    assert "deadbeef" not in mask_presigned_url(SIGNED)


def test_credential_is_removed() -> None:
    assert "AKIA" not in mask_presigned_url(SIGNED)


def test_object_key_survives() -> None:
    """어떤 객체에 대한 로그인지는 남아야 조사할 수 있다."""
    assert "images/place/a.webp" in mask_presigned_url(SIGNED)


def test_masked_url_marks_the_redaction() -> None:
    assert mask_presigned_url(SIGNED).endswith("?<redacted>")


def test_url_without_a_query_is_unchanged() -> None:
    plain = "https://bucket.s3.ap-northeast-2.amazonaws.com/images/place/a.webp"

    assert mask_presigned_url(plain) == plain
