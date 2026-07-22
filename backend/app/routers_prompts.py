from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .prompt_paths import prompt_path

router = APIRouter(prefix="/prompts", tags=["prompts"])


class PromptUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=100_000)


def _path(slug: str):
    try:
        return prompt_path(slug)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{slug}")
def get_prompt(slug: str):
    p = _path(slug)
    if not p.exists():
        raise HTTPException(status_code=404, detail="not found")
    with p.open("r", encoding="utf-8") as f:
        return {"slug": slug, "content": f.read()}


@router.put("/{slug}")
def put_prompt(slug: str, payload: PromptUpdate):
    p = _path(slug)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        f.write(payload.content)
    return {"ok": True}

