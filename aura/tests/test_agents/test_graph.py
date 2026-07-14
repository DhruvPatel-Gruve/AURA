"""Graph-level integration test for the ai_config_gate_node halt path.

Proves the "no fallback, clean abstain" property end-to-end: an unconfigured
tenant's ticket never reaches priority_scorer_node (which would otherwise be
the first node to touch the embedder) and routes straight to
audit_finalizer_node instead.
"""

import pytest
from unittest.mock import MagicMock, patch

from app.services.ai_config_service import ResolvedAIConfig

_UNCONFIGURED = ResolvedAIConfig(
    tenant_id="test-tenant-1",
    embedding_provider=None, embedding_api_key=None, embedding_base_url=None,
    embedding_model=None, embedding_vector_size=None,
    llm_base_url=None, llm_model=None, llm_api_key=None,
)


@pytest.mark.asyncio
async def test_unconfigured_tenant_halts_before_priority_scorer(base_state, mock_get_session):
    from app.agents.graph import compiled_graph

    embedder_mock = MagicMock()
    with patch("app.services.kill_switch.is_enabled", return_value=True), \
         patch("app.agents.nodes.ai_config_gate_node.get_ai_config", return_value=_UNCONFIGURED), \
         patch("app.agents.nodes.priority_scorer_node.get_embedder", embedder_mock):
        result = await compiled_graph.ainvoke(base_state)

    assert result["pipeline_halted"] is True
    assert result["halt_reason"] == "ai_not_configured"
    assert result["action_taken"] == "ai_not_configured"
    embedder_mock.assert_not_called()

    node_names = [step["node_name"] for step in result["audit_steps"]]
    assert "priority_scorer_node" not in node_names
    assert "ai_config_gate_node" in node_names
