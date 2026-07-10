from fastapi import APIRouter

from app.api.v1.routes.admin import router as admin_router
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.chat import router as chat_router
from app.api.v1.routes.dashboard import router as dashboard_router
from app.api.v1.routes.documents import router as documents_router
from app.api.v1.routes.ingestion import router as ingestion_router
from app.api.v1.routes.logs import router as logs_router
from app.api.v1.routes.master import router as master_router
from app.api.v1.routes.setup import router as setup_router
from app.api.v1.routes.tickets import router as tickets_router
from app.api.v1.routes.websocket import router as websocket_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth_router)
api_router.include_router(master_router)
api_router.include_router(setup_router)
api_router.include_router(ingestion_router)
api_router.include_router(documents_router)
api_router.include_router(admin_router)
api_router.include_router(tickets_router)
api_router.include_router(dashboard_router)
api_router.include_router(chat_router)
api_router.include_router(logs_router)

# WebSocket is registered without a prefix — path is /api/v1/ws/{user_id}
api_router.include_router(websocket_router)
