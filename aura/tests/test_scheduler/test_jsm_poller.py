"""Tests for the jsm_poller crash-visibility fallback and pipeline dispatch
for newly-seen tickets."""

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text as sa_text

import app.agents.graph  # noqa: F401 — ensures the module is importable before patching it below
from app.models.jsm import JSMTicket
from scheduler.jobs.jsm_poller import _write_error_audit_entry, run_jsm_poller
from tests.conftest import SAMPLE_TENANT_ID as TENANT


@pytest.mark.asyncio
async def test_write_error_audit_entry_persists_crash_details(db_session):
    with patch("scheduler.jobs.jsm_poller.get_session") as mock_get_session:
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _session():
            yield db_session

        mock_get_session.side_effect = _session
        await _write_error_audit_entry(TENANT, "TEST-999", "boom: LLM timeout")

    row = (await db_session.execute(
        sa_text("SELECT action_taken, audit_steps FROM audit_log WHERE tenant_id = :tenant AND ticket_id = 'TEST-999'"),
        {"tenant": TENANT},
    )).mappings().first()

    assert row is not None
    assert row["action_taken"] == "pipeline_error"
    steps = json.loads(row["audit_steps"])
    assert steps[0]["metadata"]["error"] == "boom: LLM timeout"


@pytest.mark.asyncio
async def test_new_ticket_dispatches_to_pipeline_without_transitioning(db_session):
    """The poller no longer transitions Open -> In Progress itself — that
    now happens when a technician acknowledges the ticket (tickets.py). The
    poller's only job here is picking up new tickets and invoking the graph."""

    @asynccontextmanager
    async def _session():
        yield db_session

    ticket = JSMTicket(
        ticket_id="KAN-1",
        summary="VPN down",
        status="Open",
        created=datetime.now(timezone.utc),
    )

    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.search_open_tickets = AsyncMock(return_value=[ticket])

    graph_mock = AsyncMock()

    with patch("scheduler.jobs.jsm_poller.get_session", _session), \
         patch("scheduler.jobs.jsm_poller.kill_switch.is_enabled", return_value=True), \
         patch("scheduler.jobs.jsm_poller.get_itsm_client", return_value=mock_jsm), \
         patch("app.agents.graph.compiled_graph.ainvoke", graph_mock):
        await run_jsm_poller()

    graph_mock.assert_called_once()
    mock_jsm.transition_issue.assert_not_called()
    mock_jsm.find_transition_id.assert_not_called()
