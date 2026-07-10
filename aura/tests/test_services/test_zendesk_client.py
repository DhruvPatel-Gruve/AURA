"""Tests for ZendeskClient — mirrors the JSMClient respx-based test style."""

import json

import respx
from httpx import Response

from app.services.zendesk_client import ZendeskClient

_BASE_URL = "https://test.zendesk.com"


@respx.mock
async def test_search_tickets_filters_resolved_and_hydrates():
    respx.get(f"{_BASE_URL}/api/v2/incremental/tickets.json").mock(
        return_value=Response(200, json={
            "tickets": [
                {"id": 1, "subject": "VPN down", "status": "solved",
                 "created_at": "2024-01-01T00:00:00Z", "updated_at": "2024-01-02T00:00:00Z"},
                {"id": 2, "subject": "Still open", "status": "open",
                 "created_at": "2024-01-01T00:00:00Z", "updated_at": "2024-01-02T00:00:00Z"},
            ],
            "end_of_stream": True,
        })
    )
    respx.get(f"{_BASE_URL}/api/v2/tickets/1/comments.json").mock(
        return_value=Response(200, json={"comments": [], "users": []})
    )

    async with ZendeskClient(subdomain='test', api_email='test@example.com', api_token='test-zen-token') as zd:
        tickets = await zd.search_tickets()

    assert len(tickets) == 1
    assert tickets[0].ticket_id == "1"
    assert tickets[0].status == "solved"


@respx.mock
async def test_search_open_tickets_filters_unresolved():
    respx.get(f"{_BASE_URL}/api/v2/incremental/tickets.json").mock(
        return_value=Response(200, json={
            "tickets": [
                {"id": 1, "subject": "solved one", "status": "solved",
                 "created_at": "2024-01-01T00:00:00Z", "updated_at": "2024-01-02T00:00:00Z"},
                {"id": 2, "subject": "open one", "status": "open",
                 "created_at": "2024-01-01T00:00:00Z", "updated_at": "2024-01-02T00:00:00Z"},
            ],
            "end_of_stream": True,
        })
    )
    respx.get(f"{_BASE_URL}/api/v2/tickets/2/comments.json").mock(
        return_value=Response(200, json={"comments": [], "users": []})
    )

    async with ZendeskClient(subdomain='test', api_email='test@example.com', api_token='test-zen-token') as zd:
        tickets = await zd.search_open_tickets()

    assert len(tickets) == 1
    assert tickets[0].ticket_id == "2"


@respx.mock
async def test_get_ticket_returns_none_on_404():
    respx.get(f"{_BASE_URL}/api/v2/tickets/999.json").mock(return_value=Response(404))

    async with ZendeskClient(subdomain='test', api_email='test@example.com', api_token='test-zen-token') as zd:
        ticket = await zd.get_ticket("999")

    assert ticket is None


@respx.mock
async def test_get_ticket_hydrates_comments():
    respx.get(f"{_BASE_URL}/api/v2/tickets/1.json").mock(
        return_value=Response(200, json={"ticket": {
            "id": 1, "subject": "VPN down", "status": "open",
            "created_at": "2024-01-01T00:00:00Z", "updated_at": "2024-01-02T00:00:00Z",
        }})
    )
    respx.get(f"{_BASE_URL}/api/v2/tickets/1/comments.json").mock(
        return_value=Response(200, json={
            "comments": [{"author_id": 5, "body": "Please help", "created_at": "2024-01-01T01:00:00Z"}],
            "users": [{"id": 5, "name": "Alice"}],
        })
    )

    async with ZendeskClient(subdomain='test', api_email='test@example.com', api_token='test-zen-token') as zd:
        ticket = await zd.get_ticket("1")

    assert ticket is not None
    assert len(ticket.comments) == 1
    assert ticket.comments[0].author == "Alice"


@respx.mock
async def test_get_ticket_status_reflects_custom_status_label():
    """When a ticket carries a custom_status_id, the resolved status should
    be the custom status's own label (e.g. "In Progress"), not the generic
    base category ("open") it belongs to — otherwise AURA's UI would show a
    less specific status than what's actually set on the real ticket."""
    respx.get(f"{_BASE_URL}/api/v2/tickets/1.json").mock(
        return_value=Response(200, json={"ticket": {
            "id": 1, "subject": "VPN down", "status": "open", "custom_status_id": 48466469619985,
            "created_at": "2024-01-01T00:00:00Z", "updated_at": "2024-01-02T00:00:00Z",
        }})
    )
    respx.get(f"{_BASE_URL}/api/v2/tickets/1/comments.json").mock(
        return_value=Response(200, json={"comments": [], "users": []})
    )
    respx.get(f"{_BASE_URL}/api/v2/custom_statuses.json").mock(
        return_value=Response(200, json={"custom_statuses": [
            {"id": 48466469619985, "status_category": "open", "agent_label": "In Progress", "active": True},
        ]})
    )

    async with ZendeskClient(subdomain='test', api_email='test@example.com', api_token='test-zen-token') as zd:
        ticket = await zd.get_ticket("1")

    assert ticket is not None
    assert ticket.status == "In Progress"


@respx.mock
async def test_post_comment_markdown_extracts_comment_id():
    respx.put(f"{_BASE_URL}/api/v2/tickets/1.json").mock(
        return_value=Response(200, json={
            "ticket": {"id": 1},
            "audit": {"events": [{"type": "Comment", "id": 42}]},
        })
    )

    async with ZendeskClient(subdomain='test', api_email='test@example.com', api_token='test-zen-token') as zd:
        comment_id = await zd.post_comment_markdown("1", "Resolved via reset")

    assert comment_id == "42"


async def test_delete_comment_returns_false_unsupported():
    async with ZendeskClient(subdomain='test', api_email='test@example.com', api_token='test-zen-token') as zd:
        result = await zd.delete_comment("1", "42")

    assert result is False


@respx.mock
async def test_assign_ticket_puts_assignee_id():
    route = respx.put(f"{_BASE_URL}/api/v2/tickets/1.json").mock(return_value=Response(200, json={"ticket": {"id": 1}}))

    async with ZendeskClient(subdomain='test', api_email='test@example.com', api_token='test-zen-token') as zd:
        await zd.assign_ticket("1", "789")

    body = json.loads(route.calls[0].request.content)
    assert body == {"ticket": {"assignee_id": 789}}


@respx.mock
async def test_find_transition_id_falls_back_to_base_enum_without_custom_statuses():
    respx.get(f"{_BASE_URL}/api/v2/custom_statuses.json").mock(
        return_value=Response(200, json={"custom_statuses": []})
    )

    async with ZendeskClient(subdomain='test', api_email='test@example.com', api_token='test-zen-token') as zd:
        assert await zd.find_transition_id("1", "Open") == "open"
        assert await zd.find_transition_id("1", "NotAStatus") is None


@respx.mock
async def test_find_transition_id_matches_custom_status_by_label():
    respx.get(f"{_BASE_URL}/api/v2/custom_statuses.json").mock(
        return_value=Response(200, json={"custom_statuses": [
            {"id": 48466469619985, "status_category": "open", "agent_label": "In Progress", "active": True},
            {"id": 48466463740433, "status_category": "open", "agent_label": "Open", "active": True},
        ]})
    )

    async with ZendeskClient(subdomain='test', api_email='test@example.com', api_token='test-zen-token') as zd:
        assert await zd.find_transition_id("1", "In Progress") == "custom:48466469619985"


@respx.mock
async def test_transition_issue_puts_status_for_base_category():
    route = respx.put(f"{_BASE_URL}/api/v2/tickets/1.json").mock(return_value=Response(200, json={"ticket": {"id": 1}}))

    async with ZendeskClient(subdomain='test', api_email='test@example.com', api_token='test-zen-token') as zd:
        await zd.transition_issue("1", "solved")

    body = json.loads(route.calls[0].request.content)
    assert body == {"ticket": {"status": "solved"}}


@respx.mock
async def test_transition_issue_puts_custom_status_id_for_custom_status():
    route = respx.put(f"{_BASE_URL}/api/v2/tickets/1.json").mock(return_value=Response(200, json={"ticket": {"id": 1}}))

    async with ZendeskClient(subdomain='test', api_email='test@example.com', api_token='test-zen-token') as zd:
        await zd.transition_issue("1", "custom:48466469619985")

    body = json.loads(route.calls[0].request.content)
    assert body == {"ticket": {"custom_status_id": 48466469619985}}


@respx.mock
async def test_find_account_id_by_email_returns_first_match():
    respx.get(f"{_BASE_URL}/api/v2/users/search.json").mock(
        return_value=Response(200, json={"users": [{"id": 321}]})
    )

    async with ZendeskClient(subdomain='test', api_email='test@example.com', api_token='test-zen-token') as zd:
        account_id = await zd.find_account_id_by_email("tech@example.com")

    assert account_id == "321"


@respx.mock
async def test_find_account_id_by_email_returns_none_when_no_match():
    respx.get(f"{_BASE_URL}/api/v2/users/search.json").mock(
        return_value=Response(200, json={"users": []})
    )

    async with ZendeskClient(subdomain='test', api_email='test@example.com', api_token='test-zen-token') as zd:
        account_id = await zd.find_account_id_by_email("nobody@example.com")

    assert account_id is None


@respx.mock
async def test_create_ticket_returns_new_ticket_id():
    respx.post(f"{_BASE_URL}/api/v2/tickets.json").mock(
        return_value=Response(201, json={"ticket": {"id": 55}})
    )

    async with ZendeskClient(subdomain='test', api_email='test@example.com', api_token='test-zen-token') as zd:
        ticket_id = await zd.create_ticket("VPN not connecting", "Getting a timeout")

    assert ticket_id == "55"
