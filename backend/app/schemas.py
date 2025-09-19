from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel
from typing import Optional


class ClientCreate(BaseModel):
    slug: str
    name: str


class ClientOut(BaseModel):
    id: int
    slug: str
    name: str

    class Config:
        from_attributes = True


class KnowledgeNoteCreate(BaseModel):
    text: str


class KnowledgeFileOut(BaseModel):
    id: int
    client_id: int
    source_type: str
    filename: Optional[str] = None
    text: Optional[str] = None
    uploaded_at: datetime

    class Config:
        from_attributes = True


class StyleCreate(BaseModel):
    label: Optional[str] = None
    text: str


class StyleOut(BaseModel):
    id: int
    client_id: int
    label: Optional[str] = None
    text: str
    created_at: datetime

    class Config:
        from_attributes = True


class SampleQuoteCreate(BaseModel):
    source: Optional[str] = None
    text: str


class SampleQuoteOut(BaseModel):
    id: int
    client_id: int
    source: Optional[str] = None
    text: str
    created_at: datetime

    class Config:
        from_attributes = True
