"""Tests for JSMClient's status-transition methods."""

import respx
from httpx import Response

from app.services.jsm_client import JSMClient

_BASE_URL = "https://test.atlassian.net"

_TRANSITIONS_RESPONSE = {
    "transitions": [
        {"id": "11", "name": "Start Progress", "to": {"name": "In Progress"}},
        {"id": "31", "name": "Resolve", "to": {"name": "Resolved"}},
    ]
}


@respx.mock
async def test_get_transitions_returns_raw_list():
    respx.get(f"{_BASE_URL}/rest/api/3/issue/KAN-1/transitions").mock(
        return_value=Response(200, json=_TRANSITIONS_RESPONSE)
    )

    async with JSMClient(base_url='https://test.atlassian.net', project_key='TEST', api_email='test@example.com', api_token='test-token') as jsm:
        transitions = await jsm.get_transitions("KAN-1")

    assert len(transitions) == 2
    assert transitions[0]["id"] == "11"


@respx.mock
async def test_find_transition_id_matches_by_target_status_case_insensitive():
    respx.get(f"{_BASE_URL}/rest/api/3/issue/KAN-1/transitions").mock(
        return_value=Response(200, json=_TRANSITIONS_RESPONSE)
    )

    async with JSMClient(base_url='https://test.atlassian.net', project_key='TEST', api_email='test@example.com', api_token='test-token') as jsm:
        transition_id = await jsm.find_transition_id("KAN-1", "in progress")

    assert transition_id == "11"


@respx.mock
async def test_find_transition_id_returns_none_when_unreachable():
    respx.get(f"{_BASE_URL}/rest/api/3/issue/KAN-1/transitions").mock(
        return_value=Response(200, json=_TRANSITIONS_RESPONSE)
    )

    async with JSMClient(base_url='https://test.atlassian.net', project_key='TEST', api_email='test@example.com', api_token='test-token') as jsm:
        transition_id = await jsm.find_transition_id("KAN-1", "Closed")

    assert transition_id is None


@respx.mock
async def test_transition_issue_posts_transition_id():
    route = respx.post(f"{_BASE_URL}/rest/api/3/issue/KAN-1/transitions").mock(
        return_value=Response(204)
    )

    async with JSMClient(base_url='https://test.atlassian.net', project_key='TEST', api_email='test@example.com', api_token='test-token') as jsm:
        await jsm.transition_issue("KAN-1", "11")

    assert route.called
    request = route.calls[0].request
    import json
    body = json.loads(request.content)
    assert body == {"transition": {"id": "11"}}
