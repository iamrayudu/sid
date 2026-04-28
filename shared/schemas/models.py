from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Voice pipeline
# ---------------------------------------------------------------------------

class RawChunk(BaseModel):
    """Output of voice/transcriber.py. Input to processing queue."""
    chunk_id: str
    session_id: str
    timestamp: str              # ISO8601
    raw_text: str
    audio_duration_sec: float
    silence_ratio: float = 0.0


# ---------------------------------------------------------------------------
# Stage 1 — Fast classifier output
# ---------------------------------------------------------------------------

class Stage1Output(BaseModel):
    thought_type: Literal["idea", "task", "reflection", "question", "random"]
    summary: str = Field(description="One sentence, 10-20 words max")
    clean_text: str = Field(description="Cleaned transcript, no filler words")
    energy_hint: Literal["excited", "tired", "focused", "distracted", "neutral"]
    confidence: float = Field(ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Stage 2 — Deep extractor output
# ---------------------------------------------------------------------------

class ExtractedTask(BaseModel):
    content: str
    priority: int = Field(ge=1, le=5, default=3)
    due_hint: Optional[str] = None  # 'today', 'tomorrow', 'this week', or None


class ExtractedEntity(BaseModel):
    name: str
    entity_type: Literal["person", "project", "place", "concept", "tool", "company"]


class ExtractedRelationship(BaseModel):
    related_thought_id: str
    relationship_type: Literal["EXTENDS", "CONTRADICTS", "FOLLOWS_FROM", "RELATED", "BLOCKS"]
    reason: str = Field(description="One sentence why these are related")
    strength: float = Field(ge=0.0, le=1.0, default=0.5)


class Stage2Output(BaseModel):
    tasks: List[ExtractedTask] = []
    entities: List[ExtractedEntity] = []
    sub_ideas: List[str] = []
    intent: str = Field(default="", description="Why did user say this?")
    relationships: List[ExtractedRelationship] = []
    emotional_tone: Literal["positive", "negative", "neutral", "frustrated", "excited"] = "neutral"


# ---------------------------------------------------------------------------
# DB mirror models (match SQLite schema exactly)
# ---------------------------------------------------------------------------

class Thought(BaseModel):
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
    id: str
    thought_id: str
    type: str                   # task/sub_idea/entity/goal/question
    content: str
    priority: int = 3
    status: str = "pending"     # pending/in_progress/done/dropped
    due_date: Optional[str] = None
    completed_at: Optional[str] = None
    parent_id: Optional[str] = None


class Relationship(BaseModel):
    id: str
    source_id: str
    target_id: str
    type: str
    strength: float = 0.5
    reason: Optional[str] = None
    created_at: str


class Session(BaseModel):
    id: str
    date: str
    start_time: str
    end_time: Optional[str] = None
    mode: str = "capture"       # morning_planning/capture/reflection/check_in
    label: Optional[str] = None
    thought_count: int = 0
    summary: Optional[str] = None


class DailyRecord(BaseModel):
    date: str
    morning_plan: Optional[str] = None     # JSON string
    actual_log: Optional[str] = None       # JSON string
    evening_reflection: Optional[str] = None
    energy_level: Optional[str] = None
    completion_rate: Optional[float] = None
    pending_items: Optional[str] = None    # JSON string


class LLMCallRecord(BaseModel):
    id: str
    timestamp: str
    model: str
    purpose: str                # stage1/stage2/agent_chat/morning/evening
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    estimated_cost_usd: float = 0.0
    success: int = 1


# ---------------------------------------------------------------------------
# Assembled / response models
# ---------------------------------------------------------------------------

class MemoryEntry(BaseModel):
    """Final assembled output from processing pipeline."""
    thought: Thought
    extractions: List[Extraction] = []
    relationships: List[Relationship] = []


class SearchResult(BaseModel):
    thought_id: str
    text: str
    summary: Optional[str] = None
    type: Optional[str] = None
    date: str
    session_id: str
    score: float                # cosine similarity 0-1


class StatsResult(BaseModel):
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
