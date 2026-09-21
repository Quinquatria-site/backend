"""이미지 파일 선두 바이트로 실제 형식을 판정한다.

발급 요청의 `content_type`과 S3의 Content-Type 헤더는 모두 client가 정한
값이므로 신뢰하지 않는다. 명세 §4.6이 "URL 발급 요청의 size와 content_type만
신뢰하지 않는다"고 요구하는 검증이다.
"""

from quinquatria_persistence.enums import ImageContentType

SIGNATURE_BYTES = 12
"""WebP 마커가 offset 8-11에 있어 12 byte가 필요하다."""

_JPEG = b"\xff\xd8\xff"
_PNG = b"\x89PNG\r\n\x1a\n"
_RIFF = b"RIFF"
_WEBP = b"WEBP"


def matches(head: bytes, content_type: ImageContentType) -> bool:
    """선두 바이트가 선언한 형식과 맞는지 본다."""
    if content_type is ImageContentType.JPEG:
        return head.startswith(_JPEG)
    if content_type is ImageContentType.PNG:
        return head.startswith(_PNG)
    # RIFF는 WAV 등도 쓰는 컨테이너라 뒤쪽 마커까지 봐야 WebP로 확정된다.
    return head.startswith(_RIFF) and head[8:12] == _WEBP
