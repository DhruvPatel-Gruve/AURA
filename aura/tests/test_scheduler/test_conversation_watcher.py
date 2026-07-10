"""Tests for the conversation_watcher scheduled job."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

from scheduler.jobs.conversation_watcher import run_conversation_watcher
from tests.conftest import SAMPLE_TENANT_ID as TENANT


@pytest.mark.asyncio
async def test_calls_both_checks(db_session):
    @asynccontextmanager
    async def _session():
        yield db_session

    with patch("scheduler.jobs.conversation_watcher.get_session", _session), \
         patch("scheduler.jobs.conversation_watcher.conversation_service.check_for_replies", new=AsyncMock()) as replies_mock, \
         patch("scheduler.jobs.conversation_watcher.conversation_service.check_idle_timeouts", new=AsyncMock()) as idle_mock:
        await run_conversation_watcher()

    replies_mock.assert_called_once_with(db_session, TENANT)
    idle_mock.assert_called_once_with(db_session, TENANT)


@pytest.mark.asyncio
async def test_idle_check_still_runs_if_replies_check_fails(db_session):
    @asynccontextmanager
    async def _session():
        yield db_session

    with patch("scheduler.jobs.conversation_watcher.get_session", _session), \
         patch(
             "scheduler.jobs.conversation_watcher.conversation_service.check_for_replies",
             new=AsyncMock(side_effect=Exception("boom")),
         ), \
         patch("scheduler.jobs.conversation_watcher.conversation_service.check_idle_timeouts", new=AsyncMock()) as idle_mock:
        await run_conversation_watcher()  # must not raise

    idle_mock.assert_called_once()
