"""APScheduler singleton.

Lifecycle:
  start()  — called from FastAPI lifespan on startup; registers all jobs
  stop()   — called from FastAPI lifespan on shutdown; waits for running jobs
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    if _scheduler is None:
        raise RuntimeError("Scheduler not initialised — call start() first.")
    return _scheduler


async def start() -> None:
    """Initialise and start the scheduler, registering all background jobs."""
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        log.warning("scheduler.already_running")
        return

    settings = get_settings()
    _scheduler = AsyncIOScheduler(timezone="UTC")

    # ── Job registrations ──────────────────────────────────────────────────────
    # Import here to avoid circular imports at module load time
    from scheduler.jobs.assignment_timeout_checker import run_assignment_timeout_checker
    from scheduler.jobs.conversation_watcher import run_conversation_watcher
    from scheduler.jobs.ingestion_sync import run_ingestion_sync
    from scheduler.jobs.jsm_poller import run_jsm_poller
    from scheduler.jobs.sla_checker import run_sla_checker

    _scheduler.add_job(
        run_ingestion_sync,
        trigger=IntervalTrigger(hours=settings.ingestion_sync_interval_hours),
        id="ingestion_sync",
        name="Incremental knowledge ingestion",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    _scheduler.add_job(
        run_jsm_poller,
        trigger=IntervalTrigger(minutes=settings.polling_interval_minutes),
        id="jsm_poller",
        name="JSM open-ticket poller",
        replace_existing=True,
        max_instances=1,        # never overlap — one poll at a time
        misfire_grace_time=60,
    )

    _scheduler.add_job(
        run_sla_checker,
        trigger=IntervalTrigger(minutes=1),
        id="sla_checker",
        name="SLA breach checker + claim expiry",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=30,
    )

    _scheduler.add_job(
        run_assignment_timeout_checker,
        trigger=IntervalTrigger(minutes=1),
        id="assignment_timeout_checker",
        name="Ticket assignment timeout + reassignment",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=30,
    )

    _scheduler.add_job(
        run_conversation_watcher,
        trigger=IntervalTrigger(minutes=settings.polling_interval_minutes),
        id="conversation_watcher",
        name="Reporter reply watcher + idle auto-resolve",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=60,
    )

    _scheduler.start()
    log.info(
        "scheduler.started",
        ingestion_interval_hours=settings.ingestion_sync_interval_hours,
        polling_interval_minutes=settings.polling_interval_minutes,
    )


async def stop() -> None:
    """Gracefully shut down the scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=True)
        _scheduler = None
        log.info("scheduler.stopped")
