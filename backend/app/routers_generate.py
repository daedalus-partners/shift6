from __future__ import annotations

import os
import json
import re
from typing import AsyncGenerator
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import httpx

from .db import SessionLocal
from .prompt_builder import build_prompt
from .models import Chat, ChatMessage

router = APIRouter(prefix="/generate", tags=["generate"])


def _sanitize_quote(text: str) -> str:
    """Clean up LLM output: replace em/en dashes, fix spacing issues."""
    # Replace em dashes (—) and en dashes (–) with regular hyphens
    text = text.replace("—", "-").replace("–", "-")
    # Fix missing spaces after periods, commas, colons (but not in numbers like 3.14)
    text = re.sub(r'([a-zA-Z])\.([A-Z])', r'\1. \2', text)
    text = re.sub(r'([a-zA-Z]),([a-zA-Z])', r'\1, \2', text)
    text = re.sub(r'([a-zA-Z]):([a-zA-Z])', r'\1: \2', text)
    # Fix words that got concatenated (lowercase followed by lowercase with no space)
    # This catches patterns like "financialinfrastructure" -> won't fix, too risky
    # But we can fix newlines that became concatenated
    text = re.sub(r'(\w)\n(\w)', r'\1 \2', text)
    # Normalize multiple spaces to single space
    text = re.sub(r' +', ' ', text)
    return text.strip()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL_ID = os.getenv("OPENROUTER_MODEL_ID", "anthropic/claude-3.7-sonnet")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://shift6.local/",
        "X-Title": "Shift6 Client Quote Generator",
    }


async def _post_openrouter(payload: dict) -> tuple[int, str]:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60)) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=_headers(),
                json=payload,
            )
            status = resp.status_code
            text = resp.text
            return status, text
    except Exception as e:
        # Log and return pseudo status
        print(f"[openrouter] request.error: {type(e).__name__} {e}")
        return 599, str(e)


def _parse_completion(text: str) -> str | None:
    try:
        data = json.loads(text)
        choice = (data.get("choices") or [{}])[0]
        return (choice.get("message") or {}).get("content") or choice.get("text")
    except Exception as e:
        print(f"[openrouter] parse.error: {type(e).__name__} {e}")
        return None


async def nonstream_openrouter(messages: list[dict]) -> str | None:
    # 1) Try configured model
    payload = {"model": OPENROUTER_MODEL_ID, "messages": messages, "stream": False}
    status, body = await _post_openrouter(payload)
    print(f"[openrouter] status={status} model={OPENROUTER_MODEL_ID}")
    if status == 200:
        content = _parse_completion(body)
        if content:
            return content
        print(f"[openrouter] parse_failed body={body[:400]}")
    else:
        print(f"[openrouter] error body={body[:400]}")

    # 2) Fallback to auto model
    payload["model"] = "openrouter/auto"
    status, body = await _post_openrouter(payload)
    print(f"[openrouter] fallback status={status} model=openrouter/auto")
    if status == 200:
        content = _parse_completion(body)
        if content:
            return content
        print(f"[openrouter] fallback parse_failed body={body[:400]}")
    else:
        print(f"[openrouter] fallback error body={body[:400]}")

    return None


def _sse_from_text(content: str) -> AsyncGenerator[str, None]:
    async def gen():
        words = content.split()
        chunk = []
        for w in words:
            chunk.append(w)
            if len(chunk) >= 12:
                yield f"data: {' '.join(chunk)}\n\n"
                chunk = []
        if chunk:
            yield f"data: {' '.join(chunk)}\n\n"
    return gen()


@router.get("/{client_id}")
async def generate(client_id: int, q: str, include_web: bool = False, request: Request = None, db: Session = Depends(get_db)):
    # Build prompt and messages; skip retrieval during generation for robust startup
    _, messages = build_prompt(db, client_id, q, use_retrieval=False, include_web=bool(include_web))

    if not OPENROUTER_API_KEY:
        async def fake_stream():
            yield f"data: [demo] {q}\n\n"
        # persist user + assistant demo
        chat = Chat(client_id=client_id, title=None)
        db.add(chat)
        db.commit()
        db.refresh(chat)
        db.add(ChatMessage(chat_id=chat.id, client_id=client_id, role="user", content=q))
        db.add(ChatMessage(chat_id=chat.id, client_id=client_id, role="assistant", content=f"[demo] {q}"))
        db.commit()
        return StreamingResponse(fake_stream(), media_type="text/event-stream")

    content = await nonstream_openrouter(messages)
    if not content:
        raise HTTPException(status_code=502, detail="OpenRouter completion failed; see server logs for details")
    # Sanitize the content (fix em dashes, spacing issues)
    content = _sanitize_quote(content)
    # persist chat
    chat = Chat(client_id=client_id, title=None)
    db.add(chat)
    db.commit()
    db.refresh(chat)
    db.add(ChatMessage(chat_id=chat.id, client_id=client_id, role="user", content=q))
    db.add(ChatMessage(chat_id=chat.id, client_id=client_id, role="assistant", content=content))
    db.commit()
    return StreamingResponse(_sse_from_text(content), media_type="text/event-stream")


@router.get("/full/{client_id}")
async def generate_full(client_id: int, q: str, include_web: bool = False, request: Request = None, db: Session = Depends(get_db)):
    # Non-streaming variant for clients/environments where EventSource is blocked
    _, messages = build_prompt(db, client_id, q, use_retrieval=False, include_web=bool(include_web))

    if not OPENROUTER_API_KEY:
        return {"content": f"[demo] {q}"}

    content = await nonstream_openrouter(messages)
    if not content:
        raise HTTPException(status_code=502, detail="OpenRouter completion failed; see server logs for details")
    # Sanitize the content (fix em dashes, spacing issues)
    content = _sanitize_quote(content)
    return {"content": content}
