# Shared Schemas

## Purpose

Single source of truth for all Pydantic models used across SID services.  
Every service imports from here. No duplicate model definitions anywhere.

## Files to Build

```
shared/schemas/
└── models.py   # ALL Pydantic models and TypedDicts
```

## Complete Model Definitions

Build `models.py` with all of these:

### Input/Output Data Flow Models

```python
from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime

# --- Voice Pipeline ---

class RawChunk(BaseModel):
    """Output of voice/transcriber.py. Input to processing queue."""
    chunk_id: str
    session_id: str
    timestamp: str          # ISO8601
    raw_text: str
    audio_duration_sec: float
    silence_ratio: float = 0.0

# --- Stage 1 Processing ---

class Stage1Output(BaseModel):
    """Output of fast_classifier node."""
    thought_type: Literal["idea", "task", "reflection", "question", "random"]
    summary: str
    clean_text: str
    energy_hint: Literal["excited", "tired", "focused", "distracted", "neutral"]
    confidence: float = Field(ge=0.0, le=1.0)

# --- Stage 2 Processing ---

class ExtractedTask(BaseModel):
    content: str
    priority: int = Field(ge=1, le=5, default=3)
    due_hint: Optional[str] = None

class ExtractedEntity(BaseModel):
    name: str
    entity_type: Literal["person", "project", "place", "concept", "tool", "company"]

class ExtractedRelationship(BaseModel):
    related_thought_id: str
    relationship_type: Literal["EXTENDS", "CONTRADICTS", "FOLLOWS_FROM", "RELATED", "BLOCKS"]
    reason: str
    strength: float = Field(ge=0.0, le=1.0, default=0.5)

class Stage2Output(BaseModel):
    """Output of deep_extractor node."""
    tasks: List[ExtractedTask] = []
    entities: List[ExtractedEntity] = []
    sub_ideas: List[str] = []
    intent: str = ""
    relationships: List[ExtractedRelationship] = []
    emotional_tone: Literal["positive", "negative", "neutral", "frustrated", "excited"] = "neutral"

# --- Memory Models (mirror DB schema) ---

class Thought(BaseModel):
    """Maps to 'thoughts' table."""
    id: str
    session_id: str
    timestamp: str
    raw_text: str
    clean_text: Optional[str] = None
    type: Optional[str] = None
    summary: Optional[str] = None
    energy_hint: Optional[str] = None
    location_hint: Optional[str] = None
    processing_stage: str = "raw"
    confidence: Optional[float] = None
    created_at: str
    updated_at: str

class Extraction(BaseModel):
    """Maps to 'extractions' table."""
    id: str
    thought_id: str
    type: str
    content: str
    priority: int = 3
    status: str = "pending"
    due_date: Optional[str] = None
    completed_at: Optional[str] = None
    parent_id: Optional[str] = None

class Relationship(BaseModel):
    """Maps to 'relationships' table."""
    id: str
    source_id: str
    target_id: str
    type: str
    strength: float = 0.5
    reason: Optional[str] = None
    created_at: str

class Session(BaseModel):
    """Maps to 'sessions' table."""
    id: str
    date: str
    start_time: str
    end_time: Optional[str] = None
    mode: str = "capture"
    label: Optional[str] = None
    thought_count: int = 0
    summary: Optional[str] = None

class DailyRecord(BaseModel):
    """Maps to 'daily_records' table."""
    date: str
    morning_plan: Optional[str] = None   # JSON string
    actual_log: Optional[str] = None     # JSON string
    evening_reflection: Optional[str] = None
    energy_level: Optional[str] = None
    completion_rate: Optional[float] = None
    pending_items: Optional[str] = None  # JSON string

class LLMCallRecord(BaseModel):
    """Maps to 'llm_calls' table."""
    id: str
    timestamp: str
    model: str
    purpose: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    estimated_cost_usd: float = 0.0
    success: int = 1

# --- Assembled / Response Models ---

class MemoryEntry(BaseModel):
    """Final assembled output from processing pipeline."""
    thought: Thought
    extractions: List[Extraction] = []
    relationships: List[Relationship] = []

class SearchResult(BaseModel):
    """One result from semantic search."""
    thought_id: str
    text: str
    summary: Optional[str] = None
    type: Optional[str] = None
    date: str
    session_id: str
    score: float   # cosine similarity, 0-1

class StatsResult(BaseModel):
    """Response from GET /api/stats."""
    total_thoughts: int
    thoughts_today: int
    pending_tasks: int
    llm_calls_today: int
    tokens_today_fast: int
    tokens_today_deep: int
    avg_latency_stage1_ms: float
    avg_latency_stage2_ms: float
    processing_queue_depth: int
    db_size_mb: float
```

## Import Convention

Every service should import models like:
```python
from shared.schemas.models import RawChunk, Thought, MemoryEntry, SearchResult
```

Never redefine these locally.

## Evolution

When adding new fields to a model:
1. Add to `models.py` first
2. Add corresponding migration to `services/memory/schema.sql`
3. Update any service code that constructs or reads the model
