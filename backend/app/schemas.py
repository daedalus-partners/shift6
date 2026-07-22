from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional


class ClientCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)

    @field_validator("slug")
    @classmethod
    def valid_slug(cls, value: str) -> str:
        from .prompt_paths import validate_client_slug

        return validate_client_slug(value)


class ClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    slug: str
    name: str

class KnowledgeNoteCreate(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)


class KnowledgeFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    client_id: int
    source_type: str
    filename: Optional[str] = None
    text: Optional[str] = None
    uploaded_at: datetime

class StyleCreate(BaseModel):
    label: Optional[str] = Field(None, max_length=64)
    text: str = Field(min_length=1, max_length=50_000)


class StyleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    client_id: int
    label: Optional[str] = None
    text: str
    created_at: datetime

class SampleQuoteCreate(BaseModel):
    source: Optional[str] = Field(None, max_length=128)
    text: str = Field(min_length=1, max_length=20_000)


class SampleQuoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    client_id: int
    source: Optional[str] = None
    text: str
    created_at: datetime
