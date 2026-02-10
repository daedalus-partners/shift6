"""
Task Manager API - Integrates with Google Sheets via Apps Script webhook.
Provides chat-based task creation and task listing.
"""
from __future__ import annotations

import os
import logging
import httpx
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tasks", tags=["Tasks"])

GOOGLE_SCRIPT_URL = os.getenv("GOOGLE_SCRIPT_URL", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL_ID = os.getenv("OPENROUTER_MODEL_ID", "openai/gpt-4o-mini")


class ChatRequest(BaseModel):
    message: str
    userId: Optional[str] = "web-user"


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
    people: List[str]
    client: str
    summary: str
    dueDate: str
    confidence: float


async def parse_message_with_llm(message: str) -> dict:
    """Parse a message into tasks using OpenRouter LLM."""
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY not configured")

    current_date = datetime.now().strftime("%Y-%m-%d")
    prompt = f"""Parse this message into tasks and return ONLY a JSON object, no other text.

Current Date: {current_date}
Message: "{message}"

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
  ],
  "originalMessage": "{message}"
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
            logger.error(f"OpenRouter API error: {response.status_code} - {response.text}")
            raise HTTPException(status_code=500, detail="LLM API request failed")

        data = response.json()
        if not data.get("choices") or len(data["choices"]) == 0:
            raise HTTPException(status_code=500, detail="No response from LLM")

        content = data["choices"][0]["message"]["content"]

        # Extract JSON from response
        import json
        import re

        json_match = re.search(r"\{[\s\S]*\}", content)
        if json_match:
            content = json_match.group(0)

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse LLM response as JSON: {content}")
            # Fallback response
            parsed = {
                "tasks": [
                    {
                        "people": ["team"],
                        "client": "Unsure",
                        "summary": message[:100] if len(message) > 100 else message,
                        "dueDate": "Unsure",
                        "confidence": 0.5,
                    }
                ],
                "originalMessage": message,
            }

        # Normalize tasks
        for task in parsed.get("tasks", []):
            task["people"] = [p.lower().strip() for p in task.get("people", ["team"]) if p]
            task["summary"] = (task.get("summary", "Task") or "Task")[:100]
            task["client"] = task.get("client") or "Unsure"
            task["dueDate"] = task.get("dueDate") or "Unsure"
            task["confidence"] = task.get("confidence", 0.8)

        return parsed


async def add_tasks_to_sheet(tasks: List[dict]) -> dict:
    """Add tasks to Google Sheets via Apps Script webhook."""
    if not GOOGLE_SCRIPT_URL:
        raise HTTPException(status_code=500, detail="GOOGLE_SCRIPT_URL not configured")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            GOOGLE_SCRIPT_URL,
            headers={"Content-Type": "application/json"},
            json={"action": "add_tasks", "tasks": tasks},
        )

        if response.status_code != 200:
            logger.error(f"Google Script error: {response.status_code} - {response.text}")
            raise HTTPException(status_code=500, detail="Failed to add tasks to sheet")

        data = response.json()
        if data.get("status") != "success":
            raise HTTPException(status_code=500, detail=data.get("error", "Unknown error"))

        return data


async def get_tasks_from_sheet(status_filter: Optional[str] = None) -> List[dict]:
    """Get tasks from Google Sheets via Apps Script webhook."""
    if not GOOGLE_SCRIPT_URL:
        logger.warning("GOOGLE_SCRIPT_URL not configured, returning empty task list")
        return []

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            payload = {"action": "get_tasks"}
            if status_filter:
                payload["status"] = status_filter

            response = await client.post(
                GOOGLE_SCRIPT_URL,
                headers={"Content-Type": "application/json"},
                json=payload,
            )

            if response.status_code != 200:
                logger.error(f"Google Script error: {response.status_code} - {response.text}")
                return []  # Return empty list instead of failing

            data = response.json()
            if data.get("status") != "success":
                logger.error(f"Google Script returned error: {data.get('error', 'Unknown')}")
                return []
    except Exception as e:
        logger.error(f"Failed to fetch tasks from sheet: {e}")
        return []

    return data.get("tasks", [])


@router.post("/chat", response_model=ChatResponse)
async def chat_add_task(request: ChatRequest):
    """Process a chat message and add tasks to the sheet."""
    try:
        logger.info(f"Processing chat message: {request.message[:100]}...")

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
        await add_tasks_to_sheet(task_rows)

        # Generate response
        if len(tasks) == 1:
            response_msg = f"✅ I've processed your task and added it to your productivity tracker. The task has been assigned to {', '.join(tasks[0]['people'])} for {tasks[0]['client']}."
        else:
            response_msg = f"✅ I've processed your message and created {len(tasks)} tasks in your productivity tracker. Each task has been properly categorized and assigned. Check your spreadsheet for the complete breakdown."

        return ChatResponse(success=True, response=response_msg)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error processing chat message: {e}")
        return ChatResponse(
            success=False,
            error="Failed to process your message. Please try again.",
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
