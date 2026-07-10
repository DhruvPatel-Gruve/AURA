"""Per-tenant mutual exclusion for ingestion runs.

Both the manual `POST /ingestion/trigger` route and the scheduled
`run_ingestion_sync` APScheduler job drive the same `IngestionPipeline` for
a given tenant. Each previously guarded only against concurrency with itself
(a module-level `_running` flag in ingestion.py; `max_instances=1` for the
scheduler job), so a manual trigger firing while the scheduled job is
mid-run for the SAME tenant (or vice versa) could pass Qdrant's dedup check
in both call paths before either upserts, double-embedding tickets and
double-writing ingestion audit rows.

One `asyncio.Lock` per tenant closes that gap without serializing unrelated
tenants' ingestion runs behind each other.
"""

import asyncio

_locks: dict[str, asyncio.Lock] = {}


def _lock_for(tenant_id: str) -> asyncio.Lock:
    lock = _locks.get(tenant_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[tenant_id] = lock
    return lock


async def try_acquire(tenant_id: str) -> bool:
    """Non-blocking acquire. Safe under asyncio's single-threaded event loop:
    the `locked()` check and the following `acquire()` execute with no
    `await` yield in between when the lock is free, so there is no window
    for another coroutine to interleave and acquire it first."""
    lock = _lock_for(tenant_id)
    if lock.locked():
        return False
    await lock.acquire()
    return True


def release(tenant_id: str) -> None:
    lock = _locks.get(tenant_id)
    if lock is not None and lock.locked():
        lock.release()
