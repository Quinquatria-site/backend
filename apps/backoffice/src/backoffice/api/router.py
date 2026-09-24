"""Backoffice 라우터 구성.

인가를 미들웨어가 아니라 라우터 의존성으로 건다. 대신 보호 누락은
`test_authorization.py`의 라우트 열거 테스트가 막는다. 새 리소스 라우터는
반드시 `protected_router`에 등록한다.
"""

from fastapi import APIRouter, Depends

from backoffice.api.routes import auth, root, uploads
from backoffice.auth.dependencies import require_admin
from backoffice.domains.catalog.routes import router as catalog_router
from backoffice.domains.lost_items.routes import router as lost_items_router
from backoffice.domains.notices.routes import router as notices_router
from backoffice.domains.performances.routes import router as performances_router

PUBLIC_PATHS = frozenset({"/api/v1/", "/api/v1/auth/token"})
"""인증 없이 접근하는 경로. `GET /api/v1/`는 헬스체크 용도로 남긴다."""

public_router = APIRouter()
public_router.include_router(root.router)
public_router.include_router(auth.router)

DOMAIN_ROUTERS = (
    catalog_router,
    performances_router,
    notices_router,
    lost_items_router,
)
"""이슈 #3, #4, #5, #7의 도메인 라우터. 각 이슈는 자기 도메인의 `routes.py`만
채우고 이 등록은 건드리지 않는다."""

protected_router = APIRouter(dependencies=[Depends(require_admin)])
protected_router.include_router(uploads.router)
for domain_router in DOMAIN_ROUTERS:
    protected_router.include_router(domain_router)

api_router = APIRouter()
api_router.include_router(public_router)
api_router.include_router(protected_router)
