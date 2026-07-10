"""Tests for autonomy_node (Node 6)."""

import pytest


async def _seed_category(db, name: str, auto_comment_enabled: bool, tenant_id: str = "test-tenant-1"):
    from sqlalchemy import text as sa_text
    await db.execute(
        sa_text(
            "INSERT INTO category_config "
            "(category_id, tenant_id, name, team_id, auto_comment_enabled, sla_minutes, created_at, updated_at) "
            "VALUES ('cat-auto', :tenant, :name, 'team', :enabled, 480, '2024-01-01T00:00:00', '2024-01-01T00:00:00')"
        ),
        {"name": name, "enabled": int(auto_comment_enabled), "tenant": tenant_id},
    )
    await db.commit()


@pytest.mark.asyncio
async def test_toggle_off_passes_through(base_state, mock_get_session):
    await _seed_category(mock_get_session, "Network", False)
    from app.agents.nodes.autonomy_node import autonomy_node
    result = await autonomy_node(base_state)

    assert result["auto_comment_enabled"] is False
    assert not result.get("pipeline_halted")


@pytest.mark.asyncio
async def test_toggle_on_passes_through(base_state, mock_get_session):
    await _seed_category(mock_get_session, "Network", True)
    from app.agents.nodes.autonomy_node import autonomy_node
    result = await autonomy_node(base_state)

    assert result["auto_comment_enabled"] is True
    assert not result.get("pipeline_halted")


@pytest.mark.asyncio
async def test_no_config_defaults_to_disabled(base_state, mock_get_session):
    # No row in category_config → defaults to disabled
    state = {**base_state, "category": "UnknownCategory"}
    from app.agents.nodes.autonomy_node import autonomy_node
    result = await autonomy_node(state)

    assert result["auto_comment_enabled"] is False
    assert not result.get("pipeline_halted")
