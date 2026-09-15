"""명세 §4.1의 rate limit 기준이 되는 client IP를 정한다.

각 프록시는 "요청을 받은 상대의 IP"를 `X-Forwarded-For`에 덧붙인다. 따라서
신뢰하는 프록시가 N개면 오른쪽 N개가 그들이 쓴 값이고, 그 왼쪽은 클라이언트가
보낸 대로이므로 신뢰할 수 없다. 왼쪽을 믿으면 매 요청 값을 바꿔 한도를 무한히
우회할 수 있다.
"""

from fastapi import Request

_FORWARDED_FOR = "X-Forwarded-For"
_UNKNOWN = "unknown"


def _peer(request: Request) -> str:
    return request.client.host if request.client else _UNKNOWN


def client_ip(request: Request, *, trusted_proxy_hops: int) -> str:
    """신뢰 프록시 수를 기준으로 실제 클라이언트 IP를 고른다."""
    if trusted_proxy_hops <= 0:
        return _peer(request)

    forwarded = request.headers.get(_FORWARDED_FOR)
    if not forwarded:
        return _peer(request)

    hops = [entry.strip() for entry in forwarded.split(",") if entry.strip()]
    if not hops:
        return _peer(request)

    # 목록이 신뢰 홉 수보다 짧으면 더 왼쪽이 없으므로 가장 왼쪽을 쓴다.
    return hops[max(len(hops) - trusted_proxy_hops, 0)]
