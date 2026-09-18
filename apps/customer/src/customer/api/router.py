from fastapi import APIRouter

from customer.api.routes import catalog, root

api_router = APIRouter()
api_router.include_router(root.router)
api_router.include_router(catalog.router)
