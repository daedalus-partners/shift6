"""
Task Manager API - Integrates with Google Sheets via Apps Script webhook.
Provides chat-based task creation and task listing.
"""
from __future__ import annotations

import os
import logging
import json
import httpx
from datetime import datetime
from typing import Optional, List
from urllib.parse import urljoin, urlsplit

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tasks", tags=["Tasks"])

GOOGLE_SCRIPT_URL = os.getenv("GOOGLE_SCRIPT_URL", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL_ID = os.getenv("OPENROUTER_MODEL_ID", "openai/gpt-4o-mini")

GOOGLE_SCRIPT_ALLOWED_HOSTS = {
    host.strip().lower()
    for host in os.getenv(
        "GOOGLE_SCRIPT_ALLOWED_HOSTS", "script.google.com,script.googleusercontent.com"
    ).split(",")
    if host.strip()
}


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)
    userId: Optional[str] = Field("web-user", max_length=128)


class ChatResponse(BaseModel):
    success: bool
    response: Optional[str] = None
    error: Optional[str] = None


class Task(BaseModel):
    timestamp: str
    people: List[str]
    client: str
    summary: str
    fullMessage: str
    status: str
    dueDate: str
    botNotes: str


class TasksResponse(BaseModel):
    status: str
    tasks: List[Task]


class ParsedTask(BaseModel):
    people: List[str] = Field(min_length=1, max_length=20)
    client: str = Field(min_length=1, max_length=128)
    summary: str = Field(min_length=1, max_length=100)
    dueDate: str = Field(min_length=1, max_length=32)
    confidence: float = Field(ge=0.0, le=1.0)


async def parse_message_with_llm(message: str) -> dict:
    """Parse a message into tasks using OpenRouter LLM."""
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY not configured")

    current_date = datetime.now().strftime("%Y-%m-%d")
    prompt = f"""Parse this message into tasks and return ONLY a JSON object, no other text.

Current Date: {current_date}
Message JSON value: {json.dumps(message)}

Rules:
1. Split multi-task messages into separate tasks (look for bullet points, "AND", or clear task boundaries)
2. For each task:
   - people: array of who is DOING the task (lowercase) or ["team"] if unclear
   - client: who the task is FOR. Important rules for client:
     * If message mentions specific client/company names, use that
     * For internal tasks, use "Internal"
     * If unclear, use "Unsure"
   - summary: clear, concise description of the task (max 100 chars)
   - dueDate: extract or infer due date. Format as "YYYY-MM-DD" or use "Unsure"
   - confidence: 0.0-1.0 based on how clear the task is

Return format:
{{
  "tasks": [
    {{
      "people": ["person1", "person2"],
      "client": "Client Name",
      "summary": "Task description",
      "dueDate": "2024-01-15",
      "confidence": 0.9
    }}
  ]
}}"""

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            },
            json={
                "model": OPENROUTER_MODEL_ID,
                "max_tokens": 1000,  # Limit tokens to avoid credit issues
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a task parser that ONLY returns valid JSON. Never include explanations or additional text.",
                    },
                    {"role": "user", "content": prompt},
                ],
            },
        )

        if response.status_code != 200:
            logger.error("OpenRouter task parser returned status=%s", response.status_code)
            raise HTTPException(status_code=500, detail="LLM API request failed")

        data = response.json()
        if not data.get("choices") or len(data["choices"]) == 0:
            raise HTTPException(status_code=500, detail="No response from LLM")

        content = data["choices"][0]["message"]["content"]

        # Extract JSON from response
        import re

        json_match = re.search(r"\{[\s\S]*\}", content)
        if json_match:
            content = json_match.group(0)

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("Task parser returned invalid JSON")
            raise HTTPException(status_code=502, detail="Task parser returned invalid output")

        raw_tasks = parsed.get("tasks")
        if not isinstance(raw_tasks, list) or not 1 <= len(raw_tasks) <= 20:
            raise HTTPException(status_code=502, detail="Task parser returned an invalid task list")
        try:
            tasks = [ParsedTask.model_validate(item) for item in raw_tasks]
        except Exception as exc:
            raise HTTPException(status_code=502, detail="Task parser returned invalid task fields") from exc
        normalized = []
        for task in tasks:
            item = task.model_dump()
            item["people"] = [person.lower().strip()[:128] for person in item["people"] if person.strip()]
            if not item["people"]:
                item["people"] = ["team"]
            normalized.append(item)
        return {"tasks": normalized}


def _validate_google_script_url(url: str) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in GOOGLE_SCRIPT_ALLOWED_HOSTS:
        raise HTTPException(status_code=500, detail="Google Script URL is not an allowed HTTPS destination")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=500, detail="Google Script URL must not contain credentials")
    return url


async def _google_script_request(client: httpx.AsyncClient, payload: dict) -> httpx.Response:
    current = _validate_google_script_url(GOOGLE_SCRIPT_URL)
    method = "POST"
    for redirect_count in range(6):
        response = await client.request(
            method,
            current,
            headers={"Content-Type": "application/json"} if method == "POST" else None,
            json=payload if method == "POST" else None,
        )
        if len(response.content) > 1024 * 1024:
            raise HTTPException(status_code=502, detail="Google Script response was too large")
        if not response.is_redirect:
            return response
        if redirect_count >= 5 or not response.headers.get("location"):
            raise HTTPException(status_code=502, detail="Google Script redirect was invalid")
        current = _validate_google_script_url(urljoin(current, response.headers["location"]))
        if response.status_code in {301, 302, 303}:
            method = "GET"
    raise HTTPException(status_code=502, detail="Google Script redirect limit exceeded")


async def add_tasks_to_sheet(tasks: List[dict]) -> dict:
    """Add tasks to Google Sheets via Apps Script webhook."""
    if not GOOGLE_SCRIPT_URL:
        return {"status": "error", "message": "GOOGLE_SCRIPT_URL not configured"}

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            response = await _google_script_request(
                client,
                {"action": "add_tasks", "tasks": tasks},
            )
            if response.status_code == 403:
                logger.error("Google Script returned 403; check deployment permissions")
                return {
                    "status": "error",
                    "message": "Google Sheet access denied. The Apps Script deployment needs 'Anyone' access.",
                }
            if response.status_code != 200:
                logger.error("Google Script returned status=%s", response.status_code)
                return {"status": "error", "message": f"Google Sheet returned status {response.status_code}"}

            data = response.json()
            if data.get("status") != "success":
                message = str(data.get("error") or "Unknown error from Google Sheet")[:300]
                return {"status": "error", "message": message}

            return data
    except HTTPException as exc:
        logger.warning("Google Script request rejected: %s", exc.detail)
        return {"status": "error", "message": str(exc.detail)[:300]}
    except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Google Script request failed: %s", type(exc).__name__)
        return {"status": "error", "message": "Could not reach Google Sheet."}


async def get_tasks_from_sheet(status_filter: Optional[str] = None) -> List[dict]:
    """Get tasks from Google Sheets via Apps Script webhook."""
    if not GOOGLE_SCRIPT_URL:
        logger.warning("GOOGLE_SCRIPT_URL not configured, returning empty task list")
        return []

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            payload = {"action": "get_tasks"}
            if status_filter:
                payload["status"] = status_filter

            response = await _google_script_request(client, payload)
            if response.status_code != 200:
                logger.error("Google Script returned status=%s", response.status_code)
                return []  # Return empty list instead of failing

            data = response.json()
            if data.get("status") != "success":
                logger.error(f"Google Script returned error: {data.get('error', 'Unknown')}")
                return []
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to fetch tasks from sheet")
        return []

    return data.get("tasks", [])


@router.post("/chat", response_model=ChatResponse)
async def chat_add_task(request: ChatRequest):
    """Process a chat message and add tasks to the sheet."""
    try:
        logger.info("Processing task message with length=%s", len(request.message))

        # Parse message with LLM
        parsed = await parse_message_with_llm(request.message)
        tasks = parsed.get("tasks", [])

        if not tasks:
            return ChatResponse(
                success=False,
                error="Could not parse any tasks from your message. Please try again.",
            )

        # Convert to sheet rows
        task_rows = []
        for i, task in enumerate(tasks):
            summary = task["summary"]
            if len(tasks) > 1:
                summary = f"{summary} ({i + 1}/{len(tasks)})"

            bot_notes = f"Web User: {request.userId}, Confidence: {task['confidence']:.2f}"
            if task["confidence"] < 0.7:
                bot_notes += " (Low confidence)"

            task_rows.append(
                {
                    "timestamp": datetime.now().isoformat(),
                    "people": task["people"],
                    "client": task["client"],
                    "summary": summary,
                    "fullMessage": request.message,
                    "status": "Not Started",
                    "dueDate": task["dueDate"],
                    "botNotes": bot_notes,
                }
            )

        # Add to sheet
        sheet_result = await add_tasks_to_sheet(task_rows)

        if sheet_result.get("status") == "error":
            error_msg = sheet_result.get("message", "Unknown error")
            logger.error(f"Failed to add tasks to sheet: {error_msg}")
            return ChatResponse(
                success=False,
                error=f"I parsed your task but couldn't save it to the spreadsheet: {error_msg}",
            )

        # Generate response
        if len(tasks) == 1:
            response_msg = f"I've processed your task and added it to your productivity tracker. The task has been assigned to {', '.join(tasks[0]['people'])} for {tasks[0]['client']}."
        else:
            response_msg = f"I've processed your message and created {len(tasks)} tasks in your productivity tracker. Each task has been properly categorized and assigned. Check your spreadsheet for the complete breakdown."

        return ChatResponse(success=True, response=response_msg)

    except Exception as e:
        logger.exception(f"Error processing chat message: {e}")
        return ChatResponse(
            success=False,
            error=f"Failed to process your message: {str(e)}",
        )


@router.get("")
async def list_tasks(status: Optional[str] = None):
    """Get all tasks from the sheet, optionally filtered by status."""
    try:
        tasks = await get_tasks_from_sheet(status)
        return {"status": "success", "tasks": tasks}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting tasks: {e}")
        raise HTTPException(status_code=500, detail="Failed to get tasks")
