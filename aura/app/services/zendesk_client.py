"""Async HTTPX client for the Zendesk Support REST API v2.

Implements the same method surface as JSMClient (see app/services/itsm_client.py
for the shared ITSMClient Protocol) so it's a drop-in swap behind
get_itsm_client() — same async-context-manager usage:
    async with ZendeskClient() as zd: ...

Known limitation: Zendesk has no API to delete an individual ticket comment
(comments are part of an immutable audit trail) — delete_comment() logs a
warning and no-ops rather than raising, so rollback of a comment-posted
action degrades gracefully instead of crashing. This is a real product
constraint, not a gap in this client.
"""

from base64 import b64encode
from datetime import datetime
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.core.logging import get_logger
from app.models.itsm import ITSMComment, ITSMTicket

log = get_logger(__name__)

_PAGE_SIZE = 100
# Zendesk's fixed base status categories — every custom status (below)
# belongs to exactly one of these. Accounts without Custom Ticket Statuses
# enabled only ever use these directly.
_VALID_STATUSES = ("new", "open", "pending", "hold", "solved", "closed")
_RESOLVED_STATUSES = ("solved", "closed")
# transition_id values for a matched custom status carry this prefix so
# transition_issue() knows to set custom_status_id instead of status.
_CUSTOM_STATUS_PREFIX = "custom:"


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError))


def _retry_on_rate_limit():
    return retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=2, min=4, max=60),
        stop=stop_after_attempt(5),
        reraise=True,
    )


class ZendeskClient:
    """Thin async wrapper around the Zendesk Support REST API v2.

    Credentials are passed in explicitly (decrypted from that tenant's
    `platform_config` row by app.services.itsm_client.get_itsm_client())
    rather than read from process-wide Settings — each tenant holds its own
    Zendesk connection.
    """

    def __init__(self, *, subdomain: str, api_email: str, api_token: str) -> None:
        token = b64encode(f"{api_email}/token:{api_token}".encode()).decode()
        self._base_url = f"https://{subdomain}.zendesk.com"
        self._headers = {
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self._client: httpx.AsyncClient | None = None
        self._custom_statuses_cache: list[dict] | None = None

    async def __aenter__(self) -> "ZendeskClient":
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers,
            timeout=httpx.Timeout(30.0),
        )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("ZendeskClient must be used as an async context manager.")
        return self._client

    # ── Search ────────────────────────────────────────────────────────────────

    async def search_tickets(self, since: datetime | None = None) -> list[ITSMTicket]:
        """Fetch resolved (solved/closed) tickets, optionally since a timestamp."""
        raw_tickets = await self._incremental_export(since)
        tickets = [t for t in raw_tickets if t.get("status") in _RESOLVED_STATUSES]
        results: list[ITSMTicket] = []
        for raw in tickets:
            ticket = await self._hydrate_ticket(raw)
            if ticket:
                results.append(ticket)
        log.info("zendesk.search_complete", total=len(results))
        return results

    async def search_open_tickets(self, since: datetime | None = None) -> list[ITSMTicket]:
        """Fetch open (unresolved) tickets since `since` — used by jsm_poller.py."""
        raw_tickets = await self._incremental_export(since)
        tickets = [t for t in raw_tickets if t.get("status") not in _RESOLVED_STATUSES]
        results: list[ITSMTicket] = []
        for raw in tickets:
            ticket = await self._hydrate_ticket(raw)
            if ticket:
                results.append(ticket)
        log.info("zendesk.open_tickets_fetched", total=len(results), since=str(since))
        return results

    async def _incremental_export(self, since: datetime | None) -> list[dict]:
        """Page through Zendesk's Incremental Ticket Export API — purpose
        built for "give me everything changed since X," which is exactly
        our `since` param's job. Unlike Jira's JQL search, there's no
        separate open/resolved query — this returns everything changed in
        the window and callers filter by `status` client-side.
        """
        start_time = int(since.timestamp()) if since else 0
        all_tickets: list[dict] = []
        url = "/api/v2/incremental/tickets.json"
        params: dict | None = {"start_time": start_time}

        while True:
            page = await self._get_page(url, params)
            all_tickets.extend(page.get("tickets", []))
            if page.get("end_of_stream", True) or not page.get("next_page"):
                break
            url = page["next_page"]
            params = None  # next_page is already a full URL with querystring
        return all_tickets

    @_retry_on_rate_limit()
    async def _get_page(self, url: str, params: dict | None) -> dict:
        # next_page from Zendesk is an absolute URL including the host —
        # httpx's base_url is ignored when the path itself is absolute, so
        # this works for both the first (relative) and subsequent (absolute) calls.
        resp = await self._http().get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    async def _list_custom_statuses(self) -> list[dict]:
        """Zendesk accounts can define Custom Ticket Statuses — named labels
        (e.g. "In Progress") within one of the fixed base categories above.
        Cached per-client-instance since it almost never changes mid-request
        and every status transition/lookup needs it."""
        if self._custom_statuses_cache is not None:
            return self._custom_statuses_cache
        try:
            resp = await self._http().get("/api/v2/custom_statuses.json")
            resp.raise_for_status()
            statuses = resp.json().get("custom_statuses", [])
        except Exception as exc:
            log.warning("zendesk.custom_statuses_fetch_failed", error=str(exc))
            statuses = []
        self._custom_statuses_cache = statuses
        return statuses

    # ── Single ticket ─────────────────────────────────────────────────────────

    @_retry_on_rate_limit()
    async def get_ticket(self, ticket_id: str) -> ITSMTicket | None:
        resp = await self._http().get(f"/api/v2/tickets/{ticket_id}.json")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return await self._hydrate_ticket(resp.json()["ticket"])

    async def _hydrate_ticket(self, raw: dict) -> ITSMTicket | None:
        """Convert a raw Zendesk ticket dict (+ a comments fetch) into an
        ITSMTicket. Comments are a separate call in Zendesk (unlike Jira,
        which embeds them on the issue) — hence the extra round trip here.
        """
        try:
            ticket_id = str(raw["id"])
            comments = await self._get_comments(ticket_id)
            status = raw.get("status") or ""
            custom_status_id = raw.get("custom_status_id")
            if custom_status_id:
                for cs in await self._list_custom_statuses():
                    if cs.get("id") == custom_status_id and cs.get("agent_label"):
                        status = cs["agent_label"]  # e.g. "In Progress" instead of the base "open"
                        break
            return ITSMTicket(
                ticket_id=ticket_id,
                summary=raw.get("subject") or "",
                description=raw.get("description"),
                comments=comments,
                resolution_note=None,  # Zendesk has no distinct resolution-note field
                category=raw.get("type"),  # incident/problem/question/task
                priority=(raw.get("priority") or "normal"),
                status=status,
                created=_parse_ts(raw["created_at"]),
                resolved=_parse_ts(raw["updated_at"]) if raw.get("status") in _RESOLVED_STATUSES else None,
                assignee=str(raw["assignee_id"]) if raw.get("assignee_id") else None,
                reporter_account_id=str(raw["requester_id"]) if raw.get("requester_id") else None,
            )
        except Exception as exc:
            log.warning("zendesk.parse_error", ticket=raw.get("id"), error=str(exc))
            return None

    @_retry_on_rate_limit()
    async def _get_comments(self, ticket_id: str) -> list[ITSMComment]:
        # include=users side-loads author names in one call instead of an
        # N+1 lookup per comment.
        resp = await self._http().get(
            f"/api/v2/tickets/{ticket_id}/comments.json",
            params={"include": "users"},
        )
        resp.raise_for_status()
        data = resp.json()
        users_by_id = {u["id"]: u.get("name", "Unknown") for u in data.get("users", [])}

        out: list[ITSMComment] = []
        for c in data.get("comments", []):
            try:
                author_id = c.get("author_id")
                out.append(ITSMComment(
                    author=users_by_id.get(author_id, "Unknown"),
                    author_account_id=str(author_id) if author_id else None,
                    body=c.get("body") or "",
                    created=_parse_ts(c["created_at"]),
                ))
            except Exception as exc:
                log.warning("zendesk.comment_parse_error", comment_id=c.get("id"), error=str(exc))
                continue
        return out

    # ── Write surface ─────────────────────────────────────────────────────────

    @_retry_on_rate_limit()
    async def post_comment_markdown(self, ticket_id: str, body_markdown: str) -> str:
        """Zendesk has no separate "create comment" endpoint — updating the
        ticket with a new comment object appends it to the ticket's audit
        trail. Zendesk comments render plain text (no ADF-equivalent), so
        markdown is passed through as-is rather than converted.
        """
        resp = await self._http().put(
            f"/api/v2/tickets/{ticket_id}.json",
            json={"ticket": {"comment": {"body": body_markdown, "public": True}}},
        )
        resp.raise_for_status()
        comment_id = _extract_comment_id(resp.json())
        log.info("zendesk.comment_posted", ticket_id=ticket_id, comment_id=comment_id)
        return comment_id

    async def delete_comment(self, ticket_id: str, comment_id: str) -> bool:
        """Not supported by Zendesk's API — comments are part of an
        immutable audit trail. Logs and no-ops so a rollback attempt
        degrades gracefully instead of raising. Returns False so callers
        (rollback_store) can report the true outcome instead of claiming
        success.
        """
        log.warning(
            "zendesk.delete_comment_unsupported",
            ticket_id=ticket_id, comment_id=comment_id,
        )
        return False

    @_retry_on_rate_limit()
    async def assign_ticket(self, ticket_id: str, account_id: str) -> None:
        resp = await self._http().put(
            f"/api/v2/tickets/{ticket_id}.json",
            json={"ticket": {"assignee_id": int(account_id)}},
        )
        resp.raise_for_status()
        log.info("zendesk.ticket_assigned", ticket_id=ticket_id, account_id=account_id)

    async def find_transition_id(self, ticket_id: str, target_status_name: str) -> str | None:
        """Zendesk has no per-account custom *workflow* like Jira's — there's
        no "list available transitions" endpoint — but accounts can define
        Custom Ticket Statuses (named labels like "In Progress" within one
        of the fixed base categories). Prefer a matching custom status by
        label; fall back to the fixed base-category enum for accounts that
        don't use custom statuses.
        """
        target = target_status_name.strip().lower()
        for cs in await self._list_custom_statuses():
            if not cs.get("active"):
                continue
            if (cs.get("agent_label") or "").strip().lower() == target:
                return f"{_CUSTOM_STATUS_PREFIX}{cs['id']}"
        return target if target in _VALID_STATUSES else None

    @_retry_on_rate_limit()
    async def transition_issue(self, ticket_id: str, transition_id: str) -> None:
        if transition_id.startswith(_CUSTOM_STATUS_PREFIX):
            custom_status_id = int(transition_id[len(_CUSTOM_STATUS_PREFIX):])
            body = {"ticket": {"custom_status_id": custom_status_id}}
        else:
            body = {"ticket": {"status": transition_id}}
        resp = await self._http().put(f"/api/v2/tickets/{ticket_id}.json", json=body)
        resp.raise_for_status()
        log.info("zendesk.transition_applied", ticket_id=ticket_id, status=transition_id)

    @_retry_on_rate_limit()
    async def find_account_id_by_email(self, email: str) -> str | None:
        resp = await self._http().get(
            "/api/v2/users/search.json",
            params={"query": email},
        )
        resp.raise_for_status()
        users = resp.json().get("users", [])
        return str(users[0]["id"]) if users else None

    @_retry_on_rate_limit()
    async def create_ticket(self, summary: str, description: str) -> str:
        """Create a new ticket. Returns the new ticket's numeric id (as a
        string). No requester_id is set — Zendesk defaults the requester to
        the authenticated API user, matching how JSMClient.create_ticket
        doesn't set the reporter explicitly either.
        """
        resp = await self._http().post(
            "/api/v2/tickets.json",
            json={"ticket": {"subject": summary, "comment": {"body": description}}},
        )
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError:
            log.error("zendesk.ticket_create_failed", status=resp.status_code, body=resp.text)
            raise
        ticket_id = str(resp.json()["ticket"]["id"])
        log.info("zendesk.ticket_created", ticket_id=ticket_id)
        return ticket_id


# ── Parsing helpers ───────────────────────────────────────────────────────────

def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _extract_comment_id(update_response: dict) -> str:
    """Zendesk's ticket-update response includes an `audit.events` array;
    the just-created comment shows up there with its own id. Fall back to a
    synthetic id (still unique, just not Zendesk's own) if the shape ever
    changes — rollback bookkeeping needs *some* id, not necessarily
    Zendesk's internal one, since delete_comment() is a no-op anyway.
    """
    events = (update_response.get("audit") or {}).get("events") or []
    for event in events:
        if event.get("type") == "Comment" and event.get("id") is not None:
            return str(event["id"])
    ticket_id = (update_response.get("ticket") or {}).get("id", "unknown")
    return f"{ticket_id}-comment-{datetime.now().timestamp():.0f}"
