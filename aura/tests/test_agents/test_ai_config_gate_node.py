"""Tests for ai_config_gate_node (Node 1b)."""

import pytest
from unittest.mock import patch

from app.services.ai_config_service import ResolvedAIConfig

_CONFIGURED = ResolvedAIConfig(
    tenant_id="test-tenant-1",
    embedding_provider="gemini", embedding_api_key="k", embedding_base_url=None,
    embedding_model="models/gemini-embedding-2", embedding_vector_size=768,
    llm_base_url="http://localhost:11434/v1", llm_model="qwen3:8b", llm_api_key=None,
)
_EMBEDDINGS_ONLY = ResolvedAIConfig(
    tenant_id="test-tenant-1",
    embedding_provider="gemini", embedding_api_key="k", embedding_base_url=None,
    embedding_model="models/gemini-embedding-2", embedding_vector_size=768,
    llm_base_url=None, llm_model=None, llm_api_key=None,
)
_LLM_ONLY = ResolvedAIConfig(
    tenant_id="test-tenant-1",
    embedding_provider=None, embedding_api_key=None, embedding_base_url=None,
    embedding_model=None, embedding_vector_size=None,
    llm_base_url="http://localhost:11434/v1", llm_model="qwen3:8b", llm_api_key=None,
)
_UNCONFIGURED = ResolvedAIConfig(
    tenant_id="test-tenant-1",
    embedding_provider=None, embedding_api_key=None, embedding_base_url=None,
    embedding_model=None, embedding_vector_size=None,
    llm_base_url=None, llm_model=None, llm_api_key=None,
)


def test_ai_configured_passes(base_state):
    with patch("app.agents.nodes.ai_config_gate_node.get_ai_config", return_value=_CONFIGURED):
        from app.agents.nodes.ai_config_gate_node import ai_config_gate_node
        result = ai_config_gate_node(base_state)

    assert result.get("pipeline_halted") is None or result.get("pipeline_halted") is False
    assert len(result["audit_steps"]) == 1
    assert result["audit_steps"][0]["node_name"] == "ai_config_gate_node"


def test_ai_not_configured_halts(base_state):
    with patch("app.agents.nodes.ai_config_gate_node.get_ai_config", return_value=_UNCONFIGURED):
        from app.agents.nodes.ai_config_gate_node import ai_config_gate_node
        result = ai_config_gate_node(base_state)

    assert result["pipeline_halted"] is True
    assert result["halt_reason"] == "ai_not_configured"
    assert result["action_taken"] == "ai_not_configured"
    assert len(result["audit_steps"]) == 1


@pytest.mark.parametrize("config", [_EMBEDDINGS_ONLY, _LLM_ONLY])
def test_partial_config_halts(base_state, config):
    """Both embeddings AND LLM must be configured — either alone still halts."""
    with patch("app.agents.nodes.ai_config_gate_node.get_ai_config", return_value=config):
        from app.agents.nodes.ai_config_gate_node import ai_config_gate_node
        result = ai_config_gate_node(base_state)

    assert result["pipeline_halted"] is True
    assert result["action_taken"] == "ai_not_configured"
