from fastapi import APIRouter

from customer.api.routes import catalog, lost_items, notices, performances, root

api_router = APIRouter()
api_router.include_router(root.router)
api_router.include_router(catalog.router)
api_router.include_router(performances.router)
api_router.include_router(notices.router)
api_router.include_router(lost_items.router)
