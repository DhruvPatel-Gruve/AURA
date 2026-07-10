"""Employee chat routes — RAG-grounded Q&A, with per-conversation memory.
All scoped to the caller's tenant (both the chat session state and which
knowledge base is searched).

POST /chat              — send a message, get a grounded reply
GET  /chat/history      — messages for the current active session (if any)
POST /chat/close        — close the active session; next message starts fresh

A user has at most one active `chat_sessions` row at a time. History fed to
the LLM (and returned by GET /chat/history) is scoped to that session, not
the user's whole lifetime of messages — closing it means the next message
starts with zero memory of the closed conversation.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Annotated

import asyncio

from fastapi import APIRouter, Depends, Request
from openai import AsyncOpenAI
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.rate_limit import limiter
from app.core.security import require_any_auth
from app.db.qdrant_client import ensure_tenant_collection
from app.db.sqlite import get_db
from app.models.api_schemas import (
    ChatCloseResponse,
    ChatHistoryResponse,
    ChatMessage,
    ChatRequest,
    ChatResponse,
)
from app.rag.retriever import HybridRetriever

log = get_logger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])
_settings = get_settings()

_MAX_HISTORY = 10
_MAX_CTX_CHARS = 3000


async def _get_or_create_active_session(db: AsyncSession, tenant_id: str, user_id: str) -> str:
    row = (await db.execute(
        sa_text("SELECT session_id FROM chat_sessions WHERE tenant_id = :tenant AND user_id = :uid AND status = 'active'"),
        {"tenant": tenant_id, "uid": user_id},
    )).first()
    if row:
        return row[0]

    session_id = str(uuid.uuid4())
    await db.execute(
        sa_text(
            "INSERT INTO chat_sessions (session_id, tenant_id, user_id, status, created_at) "
            "VALUES (:sid, :tenant, :uid, 'active', :now)"
        ),
        {"sid": session_id, "tenant": tenant_id, "uid": user_id, "now": datetime.now(timezone.utc).isoformat()},
    )
    return session_id


@router.post("", response_model=ChatResponse)
@limiter.limit(_settings.rate_limit_chat)
async def send_message(
    request: Request,
    body: ChatRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_any_auth)],
) -> ChatResponse:
    settings = get_settings()
    tenant_id = current_user["tenant_id"]
    user_id = current_user["user_id"]
    now = datetime.now(timezone.utc)

    session_id = await _get_or_create_active_session(db, tenant_id, user_id)

    # ── Retrieve context ──────────────────────────────────────────────────────
    collection = await ensure_tenant_collection(tenant_id)
    retriever = HybridRetriever()
    chunks = await retriever.retrieve(query_text=body.message, top_k=4, collection=collection)

    context_parts = []
    total_chars = 0
    for chunk in chunks:
        block = f"[{chunk['ticket_id']}]: {chunk['content']}"
        if total_chars + len(block) > _MAX_CTX_CHARS:
            break
        context_parts.append(block)
        total_chars += len(block)
    formatted_context = "\n\n".join(context_parts)
    citations = list({c["ticket_id"] for c in chunks[:len(context_parts)]})

    # ── Load recent chat history — scoped to this conversation only ─────────
    hist_result = await db.execute(
        sa_text(
            "SELECT role, content FROM chat_messages WHERE tenant_id = :tenant AND session_id = :sid "
            "ORDER BY timestamp DESC LIMIT :lim"
        ),
        {"tenant": tenant_id, "sid": session_id, "lim": _MAX_HISTORY},
    )
    history_rows = list(reversed(hist_result.mappings().all()))
    history_messages = [{"role": r["role"], "content": r["content"]} for r in history_rows]

    # ── Call LLM ─────────────────────────────────────────────────────────────
    system_prompt = (
        "You are AURA, an IT support assistant. "
        "Answer the employee's question using ONLY the provided context from resolved tickets. "
        "If the context doesn't contain an answer, say so honestly — do not make up steps.\n\n"
        f"Context:\n{formatted_context or '(no relevant context found)'}"
    )
    messages = [{"role": "system", "content": system_prompt}] + history_messages + [
        {"role": "user", "content": body.message}
    ]

    reply = "I'm sorry, I couldn't find a relevant answer in the knowledge base. Please contact your IT helpdesk directly."
    try:
        client = AsyncOpenAI(
            base_url=settings.ollama_base_url,
            api_key="ollama",
            timeout=settings.ollama_timeout_seconds,
        )
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=settings.ollama_model,
                messages=messages,
                max_tokens=512,
                temperature=0.3,
            ),
            timeout=settings.ollama_timeout_seconds,
        )
        reply = response.choices[0].message.content or reply
    except Exception as exc:
        log.warning("chat.llm_call_failed", error=str(exc))

    # ── Persist both turns ────────────────────────────────────────────────────
    for role, content in [("user", body.message), ("assistant", reply)]:
        await db.execute(
            sa_text(
                "INSERT INTO chat_messages (message_id, tenant_id, ticket_id, user_id, session_id, role, content, citations, timestamp) "
                "VALUES (:mid, :tenant, :tid, :uid, :sid, :role, :content, :cit, :ts)"
            ),
            {
                "mid": str(uuid.uuid4()),
                "tenant": tenant_id,
                "tid": "",           # general chat — not tied to a specific ticket
                "uid": user_id,
                "sid": session_id,
                "role": role,
                "content": content,
                "cit": json.dumps(citations if role == "assistant" else []),
                "ts": now.isoformat(),
            },
        )

    return ChatResponse(reply=reply, citations=citations, timestamp=now, session_id=session_id)


@router.post("/close", response_model=ChatCloseResponse)
async def close_chat_session(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_any_auth)],
) -> ChatCloseResponse:
    """Close the caller's active session, if any. The next message starts a
    brand-new session with no memory of this one — messages themselves are
    kept (never deleted), just excluded from future context/history scope.
    """
    now = datetime.now(timezone.utc).isoformat()
    result = await db.execute(
        sa_text(
            "UPDATE chat_sessions SET status = 'closed', closed_at = :now "
            "WHERE tenant_id = :tenant AND user_id = :uid AND status = 'active'"
        ),
        {"tenant": current_user["tenant_id"], "uid": current_user["user_id"], "now": now},
    )
    return ChatCloseResponse(closed=result.rowcount > 0)


@router.get("/history", response_model=ChatHistoryResponse)
async def get_chat_history(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_any_auth)],
) -> ChatHistoryResponse:
    tenant_id = current_user["tenant_id"]
    session_row = (await db.execute(
        sa_text("SELECT session_id FROM chat_sessions WHERE tenant_id = :tenant AND user_id = :uid AND status = 'active'"),
        {"tenant": tenant_id, "uid": current_user["user_id"]},
    )).first()
    if session_row is None:
        return ChatHistoryResponse(messages=[], session_id=None)
    session_id = session_row[0]

    result = await db.execute(
        sa_text(
            "SELECT role, content, citations, timestamp FROM chat_messages "
            "WHERE tenant_id = :tenant AND session_id = :sid ORDER BY timestamp ASC LIMIT 100"
        ),
        {"tenant": tenant_id, "sid": session_id},
    )
    messages = []
    for r in result.mappings():
        try:
            cits = json.loads(r["citations"]) if r["citations"] else []
        except (json.JSONDecodeError, TypeError):
            cits = []
        messages.append(ChatMessage(
            role=r["role"],
            content=r["content"],
            timestamp=datetime.fromisoformat(r["timestamp"]),
            citations=cits,
        ))
    return ChatHistoryResponse(messages=messages, session_id=session_id)
