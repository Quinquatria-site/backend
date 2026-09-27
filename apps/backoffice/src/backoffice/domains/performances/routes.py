"""공연 관리 라우트. `api/router.py`가 보호 라우터에 등록한다."""

from fastapi import APIRouter

router = APIRouter(tags=["performances"])
