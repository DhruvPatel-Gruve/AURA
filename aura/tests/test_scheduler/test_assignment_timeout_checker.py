"""Tests for the assignment_timeout_checker scheduled job."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

from scheduler.jobs.assignment_timeout_checker import run_assignment_timeout_checker
from tests.conftest import SAMPLE_TENANT_ID as TENANT


@pytest.mark.asyncio
async def test_calls_check_overdue(db_session):
    @asynccontextmanager
    async def _session():
        yield db_session

    with patch("scheduler.jobs.assignment_timeout_checker.get_session", _session), \
         patch("scheduler.jobs.assignment_timeout_checker.assignment_service.check_overdue", new=AsyncMock()) as mock_check:
        await run_assignment_timeout_checker()

    mock_check.assert_called_once_with(db_session, TENANT)


@pytest.mark.asyncio
async def test_swallows_exceptions_without_crashing(db_session):
    @asynccontextmanager
    async def _session():
        yield db_session

    with patch("scheduler.jobs.assignment_timeout_checker.get_session", _session), \
         patch(
             "scheduler.jobs.assignment_timeout_checker.assignment_service.check_overdue",
             new=AsyncMock(side_effect=Exception("db exploded")),
         ):
        await run_assignment_timeout_checker()  # must not raise
