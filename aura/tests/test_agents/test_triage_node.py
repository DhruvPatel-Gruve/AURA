"""Tests for triage_node (Node 4)."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.ai_config_service import ResolvedAIConfig

_CONFIGURED_AI = ResolvedAIConfig(
    tenant_id="test-tenant-1",
    embedding_provider="gemini", embedding_api_key="k", embedding_base_url=None,
    embedding_model="models/gemini-embedding-2", embedding_vector_size=768,
    llm_base_url="http://localhost:11434/v1", llm_model="qwen3:8b", llm_api_key=None,
)


async def _seed_category(db, name="Network", team_id="net-team", tenant_id="test-tenant-1"):
    from sqlalchemy import text as sa_text
    await db.execute(
        sa_text(
            "INSERT INTO category_config "
            "(category_id, tenant_id, name, team_id, auto_comment_enabled, sla_minutes, created_at, updated_at) "
            "VALUES ('cat-1', :tenant, :name, :team, 0, 480, '2024-01-01T00:00:00', '2024-01-01T00:00:00')"
        ),
        {"name": name, "team": team_id, "tenant": tenant_id},
    )
    await db.commit()


def _make_llm_response(content: str):
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


@pytest.mark.asyncio
async def test_no_categories_returns_other(base_state, mock_get_session):
    from app.agents.nodes.triage_node import triage_node
    result = await triage_node(base_state)

    assert result["category"] == "Other"
    assert result["assigned_team"] is None


@pytest.mark.asyncio
async def test_llm_success_classifies_correctly(base_state, mock_get_session):
    db = mock_get_session
    await _seed_category(db, "Network", "net-team")

    llm_resp = _make_llm_response(json.dumps({"category": "Network", "confidence": 0.92}))
    mock_client = MagicMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=llm_resp)

    with patch("app.agents.nodes.triage_node.get_ai_config", return_value=_CONFIGURED_AI), \
         patch("app.agents.nodes.triage_node.get_llm_client", return_value=mock_client):
        from app.agents.nodes.triage_node import triage_node
        result = await triage_node(base_state)

    assert result["category"] == "Network"
    assert result["assigned_team"] == "net-team"


@pytest.mark.asyncio
async def test_llm_failure_falls_back_to_other(base_state, mock_get_session):
    db = mock_get_session
    await _seed_category(db, "Network", "net-team")

    mock_client = MagicMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=Exception("Connection refused"))

    with patch("app.agents.nodes.triage_node.get_ai_config", return_value=_CONFIGURED_AI), \
         patch("app.agents.nodes.triage_node.get_llm_client", return_value=mock_client):
        from app.agents.nodes.triage_node import triage_node
        result = await triage_node(base_state)

    assert result["category"] == "Other"


@pytest.mark.asyncio
async def test_markdown_fence_stripped(base_state, mock_get_session):
    db = mock_get_session
    await _seed_category(db, "Network", "net-team")

    fenced = "```json\n" + json.dumps({"category": "Network", "confidence": 0.88}) + "\n```"
    llm_resp = _make_llm_response(fenced)
    mock_client = MagicMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=llm_resp)

    with patch("app.agents.nodes.triage_node.get_ai_config", return_value=_CONFIGURED_AI), \
         patch("app.agents.nodes.triage_node.get_llm_client", return_value=mock_client):
        from app.agents.nodes.triage_node import triage_node
        result = await triage_node(base_state)

    assert result["category"] == "Network"
