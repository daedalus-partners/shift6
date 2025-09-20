from __future__ import annotations

import os
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/prompts", tags=["prompts"])


def _path(slug: str) -> str:
    here = os.path.dirname(__file__)
    p = os.path.abspath(os.path.join(here, "..", "system_prompts", f"{slug}.md"))
    return p


@router.get("/{slug}")
def get_prompt(slug: str):
    p = _path(slug)
    if not os.path.exists(p):
        raise HTTPException(status_code=404, detail="not found")
    with open(p, "r", encoding="utf-8") as f:
        return {"slug": slug, "content": f.read()}


@router.put("/{slug}")
def put_prompt(slug: str, content: str):
    p = _path(slug)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return {"ok": True}


