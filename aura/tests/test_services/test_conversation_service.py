"""Tests for app.services.conversation_service."""

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text as sa_text

from app.models.jsm import JSMComment, JSMTicket
from app.services import conversation_service
from app.services.ai_config_service import ResolvedAIConfig

TENANT = "test-tenant-1"

_CONFIGURED_AI = ResolvedAIConfig(
    tenant_id=TENANT,
    embedding_provider="gemini", embedding_api_key="k", embedding_base_url=None,
    embedding_model="models/gemini-embedding-2", embedding_vector_size=768,
    llm_base_url="http://localhost:11434/v1", llm_model="qwen3:8b", llm_api_key=None,
)
_UNCONFIGURED_AI = ResolvedAIConfig(
    tenant_id=TENANT,
    embedding_provider=None, embedding_api_key=None, embedding_base_url=None,
    embedding_model=None, embedding_vector_size=None,
    llm_base_url=None, llm_model=None, llm_api_key=None,
)


def _now():
    return datetime.now(timezone.utc)


def _make_comment(author_account_id, body, created=None):
    return JSMComment(
        author="Someone",
        author_account_id=author_account_id,
        body=body,
        created=created or _now(),
    )


def _make_ticket(ticket_id="KAN-1", status="In Progress", comments=None):
    return JSMTicket(
        ticket_id=ticket_id,
        summary="Test ticket",
        status=status,
        created=_now(),
        comments=comments or [],
    )


async def _insert_conversation(db, ticket_id, reporter_account_id="reporter-1", last_aura_comment_at=None, status="active", turn_count=1):
    await db.execute(
        sa_text(
            "INSERT INTO ticket_conversations "
            "(tenant_id, ticket_id, status, reporter_account_id, last_aura_comment_at, turn_count, created_at, updated_at) "
            "VALUES (:tenant, :tid, :status, :rid, :last, :turns, :now, :now)"
        ),
        {
            "tenant": TENANT,
            "tid": ticket_id,
            "status": status,
            "rid": reporter_account_id,
            "last": (last_aura_comment_at or _now()).isoformat(),
            "turns": turn_count,
            "now": _now().isoformat(),
        },
    )
    await db.commit()


async def _seed_category(db, name, auto_comment_enabled):
    await db.execute(
        sa_text(
            "INSERT INTO category_config (category_id, tenant_id, name, team_id, auto_comment_enabled, sla_minutes, created_at, updated_at) "
            "VALUES (:cid, :tenant, :name, 'team', :enabled, 480, :now, :now)"
        ),
        {"cid": str(uuid.uuid4()), "tenant": TENANT, "name": name, "enabled": int(auto_comment_enabled), "now": _now().isoformat()},
    )
    await db.commit()


async def _seed_audit_log(db, ticket_id, category):
    await db.execute(
        sa_text(
            "INSERT INTO audit_log (entry_id, tenant_id, ticket_id, action_taken, category, audit_steps, created_at) "
            "VALUES (:eid, :tenant, :tid, 'comment_posted', :cat, '[]', :now)"
        ),
        {"eid": str(uuid.uuid4()), "tenant": TENANT, "tid": ticket_id, "cat": category, "now": _now().isoformat()},
    )
    await db.commit()


# ── start_tracking ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_tracking_inserts_row(db_session):
    await conversation_service.start_tracking(db_session, TENANT, "KAN-1", "reporter-1")

    row = (await db_session.execute(
        sa_text("SELECT status, reporter_account_id, turn_count FROM ticket_conversations WHERE tenant_id = :tid AND ticket_id = 'KAN-1'"),
        {"tid": TENANT},
    )).mappings().first()
    assert row["status"] == "active"
    assert row["reporter_account_id"] == "reporter-1"
    assert row["turn_count"] == 1


@pytest.mark.asyncio
async def test_start_tracking_is_idempotent(db_session):
    await conversation_service.start_tracking(db_session, TENANT, "KAN-1", "reporter-1")
    await conversation_service.start_tracking(db_session, TENANT, "KAN-1", "reporter-1")

    count = (await db_session.execute(
        sa_text("SELECT COUNT(*) FROM ticket_conversations WHERE tenant_id = :tid AND ticket_id = 'KAN-1'"),
        {"tid": TENANT},
    )).scalar()
    assert count == 1


# ── _find_new_reporter_comment ────────────────────────────────────────────────

def test_find_new_reporter_comment_filters_by_account_and_time():
    watermark = _now() - timedelta(minutes=5)
    old_reporter_comment = _make_comment("reporter-1", "old", created=watermark - timedelta(minutes=10))
    new_reporter_comment = _make_comment("reporter-1", "new reply", created=_now())
    technician_comment = _make_comment("tech-1", "internal note", created=_now())

    result = conversation_service._find_new_reporter_comment(
        [old_reporter_comment, technician_comment, new_reporter_comment],
        "reporter-1",
        watermark,
    )

    assert result is new_reporter_comment


def test_find_new_reporter_comment_returns_none_without_reporter_id():
    result = conversation_service._find_new_reporter_comment(
        [_make_comment("reporter-1", "hi")], None, _now() - timedelta(minutes=5)
    )
    assert result is None


# ── check_for_replies ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_for_replies_triggers_turn_on_new_reply(db_session):
    watermark = _now() - timedelta(hours=1)
    await _insert_conversation(db_session, "KAN-1", reporter_account_id="reporter-1", last_aura_comment_at=watermark)

    reply = _make_comment("reporter-1", "still broken", created=_now())
    ticket = _make_ticket(comments=[reply])

    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.get_ticket = AsyncMock(return_value=ticket)

    turn_mock = AsyncMock()
    with patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm), \
         patch("app.services.conversation_service._run_conversation_turn", turn_mock), \
         patch("app.services.conversation_service.get_ai_config", return_value=_CONFIGURED_AI), \
         patch("app.services.kill_switch.is_enabled", return_value=True):
        await conversation_service.check_for_replies(db_session, TENANT)

    turn_mock.assert_called_once()
    assert turn_mock.call_args.args[2].ticket_id == "KAN-1"
    assert turn_mock.call_args.args[3] is reply


@pytest.mark.asyncio
async def test_check_for_replies_stops_when_ai_not_configured(db_session):
    await _insert_conversation(db_session, "KAN-1", reporter_account_id="reporter-1")

    with patch("app.services.kill_switch.is_enabled", return_value=True), \
         patch("app.services.conversation_service.get_ai_config", return_value=_UNCONFIGURED_AI), \
         patch("app.services.itsm_client.get_itsm_client") as mock_cls:
        await conversation_service.check_for_replies(db_session, TENANT)

    mock_cls.assert_not_called()


@pytest.mark.asyncio
async def test_check_for_replies_noop_when_no_new_comment(db_session):
    await _insert_conversation(db_session, "KAN-1", reporter_account_id="reporter-1")
    ticket = _make_ticket(comments=[])

    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.get_ticket = AsyncMock(return_value=ticket)

    turn_mock = AsyncMock()
    with patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm), \
         patch("app.services.conversation_service._run_conversation_turn", turn_mock), \
         patch("app.services.conversation_service.get_ai_config", return_value=_CONFIGURED_AI), \
         patch("app.services.kill_switch.is_enabled", return_value=True):
        await conversation_service.check_for_replies(db_session, TENANT)

    turn_mock.assert_not_called()


@pytest.mark.asyncio
async def test_check_for_replies_stops_when_kill_switch_off(db_session):
    await _insert_conversation(db_session, "KAN-1", reporter_account_id="reporter-1")

    with patch("app.services.kill_switch.is_enabled", return_value=False), \
         patch("app.services.itsm_client.get_itsm_client") as mock_cls:
        await conversation_service.check_for_replies(db_session, TENANT)

    mock_cls.assert_not_called()


# ── check_idle_timeouts ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_idle_timeouts_closes_stale_conversation(db_session):
    old = _now() - timedelta(hours=100)
    await _insert_conversation(db_session, "KAN-1", last_aura_comment_at=old)

    close_mock = AsyncMock()
    with patch("app.services.conversation_service._close_conversation", close_mock):
        await conversation_service.check_idle_timeouts(db_session, TENANT)

    close_mock.assert_called_once()
    assert close_mock.call_args.args[2] == "KAN-1"


@pytest.mark.asyncio
async def test_check_idle_timeouts_ignores_recent_conversation(db_session):
    await _insert_conversation(db_session, "KAN-1", last_aura_comment_at=_now())

    close_mock = AsyncMock()
    with patch("app.services.conversation_service._close_conversation", close_mock):
        await conversation_service.check_idle_timeouts(db_session, TENANT)

    close_mock.assert_not_called()


# ── _classify_confirmation ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_classify_confirmation_parses_true():
    mock_response = AsyncMock()
    mock_response.choices = [type("C", (), {"message": type("M", (), {"content": '{"confirmed": true}'})()})()]

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    with patch("app.services.conversation_service.get_llm_client", return_value=mock_client):
        result = await conversation_service._classify_confirmation("thanks, fixed!", TENANT, _CONFIGURED_AI)

    assert result is True


@pytest.mark.asyncio
async def test_classify_confirmation_defaults_false_on_error():
    with patch("app.services.conversation_service.get_llm_client", side_effect=Exception("down")):
        result = await conversation_service._classify_confirmation("still broken", TENANT, _CONFIGURED_AI)

    assert result is False


# ── _run_conversation_turn ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_conversation_turn_closes_on_confirmation(db_session):
    await _insert_conversation(db_session, "KAN-1")
    await _seed_category(db_session, "Network", False)
    await _seed_audit_log(db_session, "KAN-1", "Network")

    ticket = _make_ticket()
    reply = _make_comment("reporter-1", "thanks, that worked!")

    close_mock = AsyncMock()
    with patch("app.services.conversation_service.get_ai_config", return_value=_CONFIGURED_AI), \
         patch("app.services.conversation_service._classify_confirmation", new=AsyncMock(return_value=True)), \
         patch("app.services.conversation_service._close_conversation", close_mock):
        await conversation_service._run_conversation_turn(db_session, TENANT, ticket, reply, "reporter-1")

    close_mock.assert_called_once()


@pytest.mark.asyncio
async def test_run_conversation_turn_skips_when_ai_not_configured(db_session):
    await _insert_conversation(db_session, "KAN-1")
    ticket = _make_ticket()
    reply = _make_comment("reporter-1", "thanks, that worked!")

    close_mock = AsyncMock()
    classify_mock = AsyncMock()
    with patch("app.services.conversation_service.get_ai_config", return_value=_UNCONFIGURED_AI), \
         patch("app.services.conversation_service._classify_confirmation", classify_mock), \
         patch("app.services.conversation_service._close_conversation", close_mock):
        await conversation_service._run_conversation_turn(db_session, TENANT, ticket, reply, "reporter-1")

    classify_mock.assert_not_called()
    close_mock.assert_not_called()

    row = (await db_session.execute(
        sa_text("SELECT status FROM ticket_conversations WHERE tenant_id = :tid AND ticket_id = 'KAN-1'"),
        {"tid": TENANT},
    )).first()
    assert row[0] == "active"


@pytest.mark.asyncio
async def test_run_conversation_turn_generates_reply_when_not_confirmed(db_session):
    await _insert_conversation(db_session, "KAN-1")
    await _seed_category(db_session, "Network", False)
    await _seed_audit_log(db_session, "KAN-1", "Network")

    ticket = _make_ticket()
    reply = _make_comment("reporter-1", "still not working, what else can I try?")

    fake_chunks = [{"ticket_id": "OLD-1", "chunk_type": "resolution", "content": "do X"}]
    gate_result = {"action_taken": "comment_posted", "confidence": 0.95, "threshold": 0.9}

    with patch("app.services.conversation_service.get_ai_config", return_value=_CONFIGURED_AI), \
         patch("app.services.conversation_service._classify_confirmation", new=AsyncMock(return_value=False)), \
         patch("app.services.conversation_service.ensure_tenant_collection", new=AsyncMock(return_value="resolved_tickets__test")), \
         patch("app.rag.retriever.get_embedder", return_value=AsyncMock()), \
         patch.object(conversation_service.HybridRetriever, "retrieve", new=AsyncMock(return_value=fake_chunks)), \
         patch("app.services.conversation_service._generate_reply", new=AsyncMock(return_value=("**AURA** reply", 0.95, ["OLD-1"]))), \
         patch("app.services.conversation_service.apply_confidence_gate", new=AsyncMock(return_value=gate_result)) as gate_mock:
        await conversation_service._run_conversation_turn(db_session, TENANT, ticket, reply, "reporter-1")

    # apply_confidence_gate (mocked here) owns posting + bumping the
    # watermark via comment_poster.post_and_track — see test_confidence_gate_node.py
    # and test_tickets_approve_transition.py for that behavior.
    gate_mock.assert_called_once()
    assert gate_mock.call_args.kwargs["confidence"] == 0.95
    assert gate_mock.call_args.kwargs["reporter_account_id"] == "reporter-1"
    assert gate_mock.call_args.kwargs["tenant_id"] == TENANT


# ── _close_conversation ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_close_conversation_marks_resolved_and_transitions_when_enabled(db_session):
    await _insert_conversation(db_session, "KAN-1")
    await _seed_category(db_session, "Network", True)
    await _seed_audit_log(db_session, "KAN-1", "Network")

    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.post_comment_markdown = AsyncMock(return_value="closing-comment-id")

    transition_mock = AsyncMock(return_value=True)
    with patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm), \
         patch("app.services.transition_service.try_transition", transition_mock):
        await conversation_service._close_conversation(db_session, TENANT, "KAN-1", closing_comment="Closing due to inactivity")

    mock_jsm.post_comment_markdown.assert_called_once()
    transition_mock.assert_called_once()
    assert transition_mock.call_args.args[0] == TENANT
    assert transition_mock.call_args.args[1] == "KAN-1"

    row = (await db_session.execute(
        sa_text("SELECT status FROM ticket_conversations WHERE tenant_id = :tid AND ticket_id = 'KAN-1'"),
        {"tid": TENANT},
    )).first()
    assert row[0] == "resolved"


@pytest.mark.asyncio
async def test_close_conversation_transitions_regardless_of_toggle(db_session):
    """Resolved transition is unconditional — it doesn't depend on the
    per-category autonomy toggle, only on In Progress -> Resolved being
    reachable in Jira."""
    await _insert_conversation(db_session, "KAN-1")
    await _seed_category(db_session, "Network", False)
    await _seed_audit_log(db_session, "KAN-1", "Network")

    transition_mock = AsyncMock(return_value=True)
    with patch("app.services.transition_service.try_transition", transition_mock):
        await conversation_service._close_conversation(db_session, TENANT, "KAN-1", closing_comment=None)

    transition_mock.assert_called_once()
    assert transition_mock.call_args.args[0] == TENANT
    assert transition_mock.call_args.args[1] == "KAN-1"
