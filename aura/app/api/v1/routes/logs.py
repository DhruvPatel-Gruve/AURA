"""Frontend log ingestion.

POST /logs/frontend — the browser has no filesystem, so it ships log entries
here to be written into their own file (logs/frontend.log), separate from
the backend's own logs/backend.log. No auth is required since errors can
happen before login (e.g. on the login page itself); rate limiting guards
against abuse.
"""

from fastapi import APIRouter, Request

from app.core.config import get_settings
from app.core.logging import get_frontend_logger
from app.core.rate_limit import limiter
from app.models.api_schemas import FrontendLogEntry, OkResponse

router = APIRouter(prefix="/logs", tags=["logs"])
_settings = get_settings()

_LEVEL_TO_METHOD = {"debug": "debug", "info": "info", "warn": "warning", "error": "error"}


@router.post("/frontend", response_model=OkResponse)
@limiter.limit(_settings.rate_limit_frontend_logs)
async def log_frontend_entry(request: Request, body: FrontendLogEntry) -> OkResponse:
    log = get_frontend_logger()
    method = _LEVEL_TO_METHOD[body.level]
    getattr(log, method)(
        "frontend.event",
        message=body.message,
        context=body.context,
        url=body.url,
        stack=body.stack,
        client_timestamp=body.timestamp.isoformat() if body.timestamp else None,
    )
    return OkResponse()
