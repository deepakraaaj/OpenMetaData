from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field

class DiscoverySource(str, Enum):
    PULLED_FROM_DB_SCHEMA = "pulled_from_db_schema"
    INFERRED_BY_SYSTEM = "inferred_by_system"
    CONFIRMED_BY_USER = "confirmed_by_user"
    PROVIDED_BY_USER = "provided_by_user"

class SourceAttribution(BaseModel):
    source: DiscoverySource = Field(default=DiscoverySource.PULLED_FROM_DB_SCHEMA)
    user: str | None = None
    timestamp: str | None = None
    rationale: str | None = None
    tooling_notes: str | None = None
