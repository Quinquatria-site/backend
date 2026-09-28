"""카테고리·장소·메뉴 관리 라우트. `api/router.py`가 보호 라우터에 등록한다."""

from fastapi import APIRouter

from backoffice.domains.catalog import categories, menus, places

router = APIRouter(tags=["catalog"])
router.include_router(categories.router)
router.include_router(places.router)
router.include_router(menus.router)
