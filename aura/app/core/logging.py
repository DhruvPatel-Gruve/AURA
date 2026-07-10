import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import structlog

from app.core.config import get_settings

FRONTEND_LOGGER_NAME = "frontend"


def configure_logging() -> None:
    settings = get_settings()

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.is_production:
        # JSON lines to stdout — consumed by log aggregators
        console_renderer = structlog.processors.JSONRenderer()
    else:
        # Human-readable coloured output for local dev
        console_renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    console_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            console_renderer,
        ],
    )
    # Log files are always plain-text log lines (uncoloured ConsoleRenderer)
    # regardless of env — a .log file should read like a log, not a JSON blob.
    file_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(colors=False),
        ],
    )

    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)

    backend_file_handler = RotatingFileHandler(
        log_dir / "backend.log",
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    backend_file_handler.setFormatter(file_formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)
    root_logger.addHandler(backend_file_handler)
    root_logger.setLevel(logging.INFO)

    # Silence noisy third-party loggers
    for noisy in (
        "httpx", "httpcore", "uvicorn.access", "apscheduler",
        "sqlalchemy.engine", "sqlalchemy.pool", "aiosqlite",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Frontend logs (shipped from the browser via POST /api/v1/logs/frontend)
    # get their own file, isolated from backend.log — propagate=False so they
    # don't also land in backend.log/stdout via the root logger.
    frontend_file_handler = RotatingFileHandler(
        log_dir / "frontend.log",
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    frontend_file_handler.setFormatter(file_formatter)

    frontend_console_handler = logging.StreamHandler(sys.stdout)
    frontend_console_handler.setFormatter(console_formatter)

    frontend_logger = logging.getLogger(FRONTEND_LOGGER_NAME)
    frontend_logger.handlers.clear()
    frontend_logger.addHandler(frontend_file_handler)
    frontend_logger.addHandler(frontend_console_handler)
    frontend_logger.setLevel(logging.INFO)
    frontend_logger.propagate = False


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


def get_frontend_logger() -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(FRONTEND_LOGGER_NAME)
