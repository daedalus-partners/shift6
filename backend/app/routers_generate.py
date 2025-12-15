from __future__ import annotations

import os
import json
import logging
from typing import AsyncGenerator
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import httpx

from .db import SessionLocal
from .prompt_builder import build_prompt
from .models import Chat, ChatMessage

router = APIRouter(prefix="/generate", tags=["generate"])

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL_ID = os.getenv("OPENROUTER_MODEL_ID", "anthropic/claude-3.7-sonnet")
# Enable extended thinking - set budget tokens (0 to disable)
THINKING_BUDGET_TOKENS = int(os.getenv("THINKING_BUDGET_TOKENS", "10000"))


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


def _parse_completion(text: str) -> tuple[str | None, str | None]:
    """Parse completion response and return (content, thinking)."""
    try:
        data = json.loads(text)
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        
        # Extract main content
        content = message.get("content") or choice.get("text")
        
        # Extract thinking from the response if present
        thinking = None
        reasoning = message.get("reasoning")
        if reasoning:
            thinking = reasoning
        
        # Also check for thinking in content blocks (Claude format)
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "thinking":
                        thinking = block.get("thinking", "")
                    elif block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
            content = "\n".join(text_parts) if text_parts else None
        
        return content, thinking
    except Exception as e:
        print(f"[openrouter] parse.error: {type(e).__name__} {e}")
        return None, None


async def nonstream_openrouter(messages: list[dict]) -> str | None:
    # 1) Try configured model
    payload = {"model": OPENROUTER_MODEL_ID, "messages": messages, "stream": False}
    
    # Add extended thinking if budget > 0 and using a Claude model that supports it
    if THINKING_BUDGET_TOKENS > 0 and "claude" in OPENROUTER_MODEL_ID.lower():
        payload["reasoning"] = {
            "effort": "high"  # Can be "low", "medium", or "high"
        }
        logger.info(f"[thinking] Extended thinking enabled with effort=high")
    
    status, body = await _post_openrouter(payload)
    print(f"[openrouter] status={status} model={OPENROUTER_MODEL_ID}")
    if status == 200:
        content, thinking = _parse_completion(body)
        
        # Log thinking for debugging
        if thinking:
            logger.info("=" * 60)
            logger.info("[THINKING] Model's reasoning process:")
            logger.info("=" * 60)
            logger.info(thinking)
            logger.info("=" * 60)
        
        if content:
            return content
        print(f"[openrouter] parse_failed body={body[:400]}")
    else:
        print(f"[openrouter] error body={body[:400]}")

    # 2) Fallback to auto model (without thinking - not all models support it)
    payload["model"] = "openrouter/auto"
    if "reasoning" in payload:
        del payload["reasoning"]  # Remove thinking for fallback
    status, body = await _post_openrouter(payload)
    print(f"[openrouter] fallback status={status} model=openrouter/auto")
    if status == 200:
        content, thinking = _parse_completion(body)
        if thinking:
            logger.info("[THINKING - fallback] " + thinking)
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
    
    # Log the full prompt for debugging
    logger.info("=" * 60)
    logger.info(f"[PROMPT] Generating quote for client_id={client_id}")
    logger.info(f"[PROMPT] User query: {q}")
    logger.info("=" * 60)
    for i, msg in enumerate(messages):
        logger.info(f"[PROMPT] Message {i} ({msg['role']}):")
        logger.info(msg['content'][:500] + "..." if len(msg['content']) > 500 else msg['content'])
    logger.info("=" * 60)

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
    
    # Log the full prompt for debugging
    logger.info(f"[PROMPT-FULL] Generating quote for client_id={client_id}, query: {q}")

    if not OPENROUTER_API_KEY:
        return {"content": f"[demo] {q}"}

    content = await nonstream_openrouter(messages)
    if not content:
        raise HTTPException(status_code=502, detail="OpenRouter completion failed; see server logs for details")
    return {"content": content}
