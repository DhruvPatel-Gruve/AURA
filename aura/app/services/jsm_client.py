"""Async HTTPX client for Jira Service Management REST API v3.

All methods are read-only except post_comment / delete_comment / create_ticket /
assign_ticket / transition_issue. Phase 0 only uses search_tickets() and get_ticket().
"""

from base64 import b64encode
from datetime import datetime
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.jsm import JSMComment, JSMTicket

log = get_logger(__name__)

_PAGE_SIZE = 50
_RESOLVED_FIELDS = "summary,description,comment,resolution,issuetype,priority,status,created,resolutiondate,assignee,reporter"
_OPEN_FIELDS = "summary,description,comment,issuetype,priority,status,created,assignee,reporter"


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        # 429 (rate limit) and 5xx (transient server-side failure) are worth
        # retrying; 4xx other than 429 means the request itself is wrong and
        # retrying it will just fail identically every time.
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    # Network-level failures (connection refused/reset, DNS blip, read
    # timeout) are transient by nature — previously only HTTP 429 responses
    # were retried, so any timeout/connection error propagated immediately
    # with zero retries despite the decorator's name implying broader coverage.
    return isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError))


def _retry_on_rate_limit():
    return retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=2, min=4, max=60),
        stop=stop_after_attempt(5),
        reraise=True,
    )


class JSMClient:
    """Thin async wrapper around the Atlassian REST API v3.

    Credentials are passed in explicitly (decrypted from that tenant's
    `platform_config` row by app.services.itsm_client.get_itsm_client())
    rather than read from process-wide Settings — each tenant holds its own
    Jira connection.
    """

    def __init__(self, *, base_url: str, project_key: str, api_email: str, api_token: str) -> None:
        token = b64encode(f"{api_email}:{api_token}".encode()).decode()
        self._base_url = base_url
        self._project_key = project_key
        self._headers = {
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self._client: httpx.AsyncClient | None = None
        self._board_id: int | None = None

    async def __aenter__(self) -> "JSMClient":
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
            raise RuntimeError("JSMClient must be used as an async context manager.")
        return self._client

    # ── Board discovery ───────────────────────────────────────────────────────

    async def _get_board_id(self) -> int:
        """Return the Agile board ID for the configured project (cached)."""
        if self._board_id is not None:
            return self._board_id
        resp = await self._http().get(
            "/rest/agile/1.0/board",
            params={"projectKeyOrId": self._project_key},
        )
        resp.raise_for_status()
        values = resp.json().get("values", [])
        if not values:
            raise RuntimeError(f"No Agile board found for project {self._project_key}")
        self._board_id = int(values[0]["id"])
        log.info("jsm.board_discovered", board_id=self._board_id, project=self._project_key)
        return self._board_id

    # ── Search ────────────────────────────────────────────────────────────────

    @_retry_on_rate_limit()
    async def _search_page(self, jql: str, start_at: int) -> dict:
        board_id = await self._get_board_id()
        resp = await self._http().get(
            f"/rest/agile/1.0/board/{board_id}/issue",
            params={
                "jql": jql,
                "fields": _RESOLVED_FIELDS,
                "startAt": start_at,
                "maxResults": _PAGE_SIZE,
            },
        )
        resp.raise_for_status()
        return resp.json()

    async def search_tickets(
        self,
        since: datetime | None = None,
        extra_jql: str = "",
    ) -> list[JSMTicket]:
        """Fetch all resolved tickets from the configured project.

        Args:
            since: Only return tickets resolved after this timestamp.
            extra_jql: Optional additional JQL clauses (AND-joined).
        """
        clauses = [
            f"project = {self._project_key}",
            "statusCategory = Done",
        ]
        if since:
            ts = since.strftime("%Y-%m-%d %H:%M")
            clauses.append(f'resolutiondate >= "{ts}"')
        if extra_jql:
            clauses.append(extra_jql)

        jql = " AND ".join(clauses) + " ORDER BY resolutiondate ASC"
        tickets: list[JSMTicket] = []
        start_at = 0

        while True:
            page = await self._search_page(jql, start_at)
            issues = page.get("issues", [])
            for raw in issues:
                ticket = _parse_ticket(raw)
                if ticket:
                    tickets.append(ticket)
            start_at += len(issues)
            if start_at >= page.get("total", 0) or not issues:
                break
            log.debug("jsm.search_page", fetched=start_at, total=page.get("total"))

        log.info("jsm.search_complete", total=len(tickets), jql=jql)
        return tickets

    async def count_tickets(self, jql_extra: str = "") -> int:
        """Total ticket count for the configured project (optionally
        narrowed by extra JQL), without fetching full issue data. Used by
        the Setup Wizard's connection test — same Agile board endpoint
        search_tickets() uses, just maxResults=1 to keep it cheap.
        """
        clauses = [f"project = {self._project_key}"]
        if jql_extra:
            clauses.append(jql_extra)
        jql = " AND ".join(clauses)
        board_id = await self._get_board_id()
        resp = await self._http().get(
            f"/rest/agile/1.0/board/{board_id}/issue",
            params={"jql": jql, "maxResults": 1, "fields": "key"},
        )
        resp.raise_for_status()
        return resp.json().get("total", 0)

    # ── Single ticket ─────────────────────────────────────────────────────────

    @_retry_on_rate_limit()
    async def get_ticket(self, ticket_id: str) -> JSMTicket | None:
        resp = await self._http().get(
            f"/rest/api/3/issue/{ticket_id}",
            params={"fields": _RESOLVED_FIELDS},
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return _parse_ticket(resp.json())

    # ── Open-ticket polling (Phase 1 JSM poller) ─────────────────────────────

    async def search_open_tickets(
        self,
        since: datetime | None = None,
    ) -> list[JSMTicket]:
        """Fetch open (unresolved) tickets created since `since`.

        Used by jsm_poller.py every 5 minutes to discover new tickets for
        the agent pipeline. Returns tickets with status != Done/Resolved.
        """
        clauses = [
            f"project = {self._project_key}",
            "statusCategory != Done",
        ]
        if since:
            ts = since.strftime("%Y-%m-%d %H:%M")
            clauses.append(f'created >= "{ts}"')

        jql = " AND ".join(clauses) + " ORDER BY created ASC"
        tickets: list[JSMTicket] = []
        start_at = 0

        while True:
            page = await self._search_open_page(jql, start_at)
            issues = page.get("issues", [])
            for raw in issues:
                ticket = _parse_ticket(raw)
                if ticket:
                    tickets.append(ticket)
            start_at += len(issues)
            if start_at >= page.get("total", 0) or not issues:
                break

        log.info("jsm.open_tickets_fetched", total=len(tickets), since=str(since))
        return tickets

    @_retry_on_rate_limit()
    async def _search_open_page(self, jql: str, start_at: int) -> dict:
        board_id = await self._get_board_id()
        resp = await self._http().get(
            f"/rest/agile/1.0/board/{board_id}/issue",
            params={
                "jql": jql,
                "fields": _OPEN_FIELDS,
                "startAt": start_at,
                "maxResults": _PAGE_SIZE,
            },
        )
        resp.raise_for_status()
        return resp.json()

    # ── Write surface — comment-only at L1, status transitions unlocked at L2 ──

    @_retry_on_rate_limit()
    async def post_comment(self, ticket_id: str, body_adf: dict) -> str:
        """Post an ADF-format comment. Returns the new comment ID."""
        resp = await self._http().post(
            f"/rest/api/3/issue/{ticket_id}/comment",
            json={"body": body_adf},
        )
        resp.raise_for_status()
        comment_id: str = resp.json()["id"]
        log.info("jsm.comment_posted", ticket_id=ticket_id, comment_id=comment_id)
        return comment_id

    async def post_comment_markdown(self, ticket_id: str, body_markdown: str) -> str:
        """Convenience wrapper: convert plain markdown to ADF then post.

        This is what confidence_gate_node uses so it never has to touch ADF.
        """
        adf = markdown_to_adf(body_markdown)
        return await self.post_comment(ticket_id, adf)

    @_retry_on_rate_limit()
    async def delete_comment(self, ticket_id: str, comment_id: str) -> bool:
        """Delete a previously posted comment (used by rollback). Returns
        True on success — Jira supports this, unlike some other providers."""
        resp = await self._http().delete(
            f"/rest/api/3/issue/{ticket_id}/comment/{comment_id}"
        )
        resp.raise_for_status()
        log.info("jsm.comment_deleted", ticket_id=ticket_id, comment_id=comment_id)
        return True

    @_retry_on_rate_limit()
    async def assign_ticket(self, ticket_id: str, account_id: str) -> None:
        """Set Jira's native Assignee field on a ticket.

        account_id is the Jira/Atlassian accountId (not an email) — resolve
        one via find_account_id_by_email() first if you only have an email.
        """
        resp = await self._http().put(
            f"/rest/api/3/issue/{ticket_id}/assignee",
            json={"accountId": account_id},
        )
        resp.raise_for_status()
        log.info("jsm.ticket_assigned", ticket_id=ticket_id, account_id=account_id)

    @_retry_on_rate_limit()
    async def get_transitions(self, ticket_id: str) -> list[dict]:
        """List transitions currently available for a ticket.

        Returns Jira's raw transition dicts, e.g. [{"id": "31", "name": "Start",
        "to": {"name": "In Progress"}}, ...]. Only transitions reachable from
        the ticket's CURRENT status are returned — this is how Jira reports
        workflow-specific transition IDs, which can't be hardcoded.
        """
        resp = await self._http().get(f"/rest/api/3/issue/{ticket_id}/transitions")
        resp.raise_for_status()
        transitions: list[dict] = resp.json().get("transitions", [])
        return transitions

    async def find_transition_id(self, ticket_id: str, target_status_name: str) -> str | None:
        """Find the transition id that moves ticket_id to target_status_name.

        Returns None if that status isn't reachable right now (e.g. the
        ticket is already there, or the workflow doesn't allow it directly)
        — callers should treat None as "nothing to do", not an error.
        """
        transitions = await self.get_transitions(ticket_id)
        target = target_status_name.strip().lower()
        for t in transitions:
            to_name = (t.get("to") or {}).get("name", "").strip().lower()
            if to_name == target:
                return t["id"]
        return None

    @_retry_on_rate_limit()
    async def transition_issue(self, ticket_id: str, transition_id: str) -> None:
        """Execute a workflow transition — moves the ticket to a new status."""
        resp = await self._http().post(
            f"/rest/api/3/issue/{ticket_id}/transitions",
            json={"transition": {"id": transition_id}},
        )
        resp.raise_for_status()
        log.info("jsm.transition_applied", ticket_id=ticket_id, transition_id=transition_id)

    @_retry_on_rate_limit()
    async def find_account_id_by_email(self, email: str) -> str | None:
        """Look up a Jira accountId by email via the user search API.

        Returns None if no matching user is found (e.g. the email doesn't
        correspond to a real Atlassian account on this site).
        """
        resp = await self._http().get(
            "/rest/api/3/user/search",
            params={"query": email},
        )
        resp.raise_for_status()
        results = resp.json()
        if not results:
            return None
        return results[0]["accountId"]

    @_retry_on_rate_limit()
    async def create_ticket(
        self,
        summary: str,
        description: str,
    ) -> str:
        """Create a new service request. Returns the new ticket ID.

        `description` is plain markdown — converted to ADF here (provider
        detail), not by the caller. Uses settings.jsm_default_issue_type
        (e.g. "Task") for the Jira issuetype — AURA's own "category" concept
        (Network, Hardware, etc, assigned later by triage_node from
        free-text) is not a valid Jira issuetype name and must never be sent
        as one; a previous version of this method did exactly that, so every
        end-user submission failed with an opaque 400 from Jira.
        """
        settings = get_settings()
        resp = await self._http().post(
            "/rest/api/3/issue",
            json={
                "fields": {
                    "project": {"key": self._project_key},
                    "summary": summary,
                    "description": markdown_to_adf(description),
                    "issuetype": {"name": settings.jsm_default_issue_type},
                }
            },
        )
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError:
            log.error("jsm.ticket_create_failed", status=resp.status_code, body=resp.text)
            raise
        ticket_id: str = resp.json()["key"]
        log.info("jsm.ticket_created", ticket_id=ticket_id)
        return ticket_id


# ── Markdown → ADF converter ──────────────────────────────────────────────────

def markdown_to_adf(text: str) -> dict:
    """Convert a simple markdown string to Atlassian Document Format (ADF).

    Handles the subset used by resolution_node output:
      **bold**        → bold mark
      _italic_ / *italic* → italic mark
      ---             → rule node (horizontal divider)
      blank line      → paragraph break
      other text      → plain paragraph

    Returns a valid ADF doc dict suitable for POST /rest/api/3/issue/{id}/comment.
    """
    import re

    content_nodes: list[dict] = []
    paragraph_lines: list[str] = []

    def _flush_paragraph() -> None:
        joined = " ".join(paragraph_lines).strip()
        if joined:
            inline_nodes = _parse_inline(joined)
            content_nodes.append({"type": "paragraph", "content": inline_nodes})
        paragraph_lines.clear()

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if not line:
            # Blank line → end the current paragraph
            _flush_paragraph()
        elif re.match(r"^-{3,}$", line):
            # Horizontal rule — flush any pending paragraph first
            _flush_paragraph()
            content_nodes.append({"type": "rule"})
        else:
            paragraph_lines.append(line)

    _flush_paragraph()  # flush any trailing content

    # ADF requires at least one content node
    if not content_nodes:
        content_nodes.append({
            "type": "paragraph",
            "content": [{"type": "text", "text": text}],
        })

    return {"version": 1, "type": "doc", "content": content_nodes}


def _parse_inline(text: str) -> list[dict]:
    """Parse inline markdown (bold, italic) into ADF inline nodes."""
    import re

    # Pattern order matters: bold before italic to avoid partial matches
    pattern = re.compile(
        r"(\*\*(.+?)\*\*)"       # **bold**
        r"|(_(.+?)_)"            # _italic_
        r"|(\*(.+?)\*)"          # *italic*
    )

    nodes: list[dict] = []
    last_end = 0

    for m in pattern.finditer(text):
        # Plain text before this match
        if m.start() > last_end:
            nodes.append({"type": "text", "text": text[last_end:m.start()]})

        if m.group(1):  # **bold**
            nodes.append({
                "type": "text",
                "text": m.group(2),
                "marks": [{"type": "strong"}],
            })
        elif m.group(3):  # _italic_
            nodes.append({
                "type": "text",
                "text": m.group(4),
                "marks": [{"type": "em"}],
            })
        elif m.group(5):  # *italic*
            nodes.append({
                "type": "text",
                "text": m.group(6),
                "marks": [{"type": "em"}],
            })

        last_end = m.end()

    # Remaining plain text after last match
    if last_end < len(text):
        nodes.append({"type": "text", "text": text[last_end:]})

    return nodes or [{"type": "text", "text": text}]


# ── Parsing helpers ───────────────────────────────────────────────────────────

def _parse_ticket(raw: dict) -> JSMTicket | None:
    """Convert a raw Jira REST v3 issue dict into a JSMTicket."""
    try:
        fields = raw.get("fields", {})
        return JSMTicket(
            ticket_id=raw["key"],
            summary=fields.get("summary") or "",
            description=_extract_text(fields.get("description")),
            comments=_parse_comments(fields.get("comment", {}).get("comments", [])),
            resolution_note=_extract_text(
                (fields.get("resolution") or {}).get("description")
            ),
            category=(fields.get("issuetype") or {}).get("name"),
            priority=(fields.get("priority") or {}).get("name", "Medium"),
            status=(fields.get("status") or {}).get("name", ""),
            created=datetime.fromisoformat(
                fields["created"].replace("Z", "+00:00")
            ),
            resolved=(
                datetime.fromisoformat(
                    fields["resolutiondate"].replace("Z", "+00:00")
                )
                if fields.get("resolutiondate")
                else None
            ),
            assignee=(fields.get("assignee") or {}).get("displayName"),
            reporter_account_id=(fields.get("reporter") or {}).get("accountId"),
        )
    except Exception as exc:
        log.warning("jsm.parse_error", ticket=raw.get("key"), error=str(exc))
        return None


def _parse_comments(raw_comments: list[dict]) -> list[JSMComment]:
    out = []
    for c in raw_comments:
        try:
            out.append(
                JSMComment(
                    author=(c.get("author") or {}).get("displayName", "Unknown"),
                    author_account_id=(c.get("author") or {}).get("accountId"),
                    body=_extract_text(c.get("body")) or "",
                    created=datetime.fromisoformat(
                        c["created"].replace("Z", "+00:00")
                    ),
                )
            )
        except Exception as exc:
            # A malformed comment (missing/unparseable `created`, etc.) must
            # not silently vanish — that's exactly the kind of gap that lets
            # a real reporter reply go undetected by conversation_service.
            log.warning("jsm.comment_parse_error", comment_id=c.get("id"), error=str(exc))
            continue
    return out


def _extract_text(node: Any) -> str | None:
    """Recursively flatten an Atlassian Document Format (ADF) node to plain text.
    Falls back to str() if the value is already a plain string.
    """
    if node is None:
        return None
    if isinstance(node, str):
        return node or None
    if isinstance(node, dict):
        if node.get("type") == "text":
            return node.get("text", "")
        parts = [_extract_text(child) for child in node.get("content", [])]
        joined = " ".join(p for p in parts if p)
        return joined or None
    if isinstance(node, list):
        parts = [_extract_text(item) for item in node]
        joined = " ".join(p for p in parts if p)
        return joined or None
    return str(node)
