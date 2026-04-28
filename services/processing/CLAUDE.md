# Processing Service

## Purpose

Takes raw transcribed text chunks and converts them into fully structured memory entries.  
This is a 2-stage LangGraph pipeline — the intelligence core of SID.

**Input**: `RawChunk` from async queue  
**Output**: Fully populated `MemoryEntry` written to memory service

## Files to Build

```
services/processing/
├── __init__.py          # Exports: ProcessingService, get_processor()
├── queue.py             # Async processing queue (decouples voice from LLM)
└── pipeline/
    ├── graph.py         # LangGraph pipeline wiring (builds the StateGraph)
    ├── state.py         # ProcessingState TypedDict (all intermediate data)
    └── nodes/
        ├── fast_classifier.py    # Stage 1: type + summary (fast model)
        ├── context_loader.py     # Load related memories (vector search, no LLM)
        ├── deep_extractor.py     # Stage 2: tasks, entities, relationships (deep model)
        ├── assembler.py          # Merge all outputs into MemoryEntry (no LLM)
        └── writer.py             # Write to SQLite + LanceDB (no LLM)
```

## Reuse From Friday Project

**Copy these patterns from `../friday/`**:
- `agents/pipeline/state.py` → TypedDict state pattern (adapt for SID's schema)
- `agents/pipeline/graph.py` → LangGraph StateGraph wiring
- `agents/pipeline/nodes/classifier.py` → Pydantic structured output pattern
- `memory/vector_store.py` → Lazy-loaded singleton cache

Do NOT copy: ChromaDB, Gemini calls, Friday-specific prompts.

## Pipeline State

```python
# state.py
from typing import TypedDict, Optional, List
from shared.schemas.models import RawChunk, Stage1Output, Stage2Output, MemoryEntry, SearchResult

class ProcessingState(TypedDict):
    # Input
    chunk: RawChunk

    # After fast_classifier
    stage1: Optional[Stage1Output]

    # After context_loader
    related_thoughts: List[SearchResult]

    # After deep_extractor
    stage2: Optional[Stage2Output]

    # After assembler
    memory_entry: Optional[MemoryEntry]

    # After writer
    written: bool
    thought_id: Optional[str]
```

## Stage 1 Output Schema (Pydantic, for structured output)

```python
class Stage1Output(BaseModel):
    thought_type: Literal["idea", "task", "reflection", "question", "random"]
    summary: str = Field(description="One sentence, 10-20 words max")
    clean_text: str = Field(description="Cleaned transcript, remove filler words")
    energy_hint: Literal["excited", "tired", "focused", "distracted", "neutral"]
    confidence: float = Field(ge=0.0, le=1.0, description="0-1 confidence in classification")
```

## Stage 2 Output Schema (Pydantic, for structured output)

```python
class ExtractedTask(BaseModel):
    content: str
    priority: int = Field(ge=1, le=5, description="1=urgent, 5=low")
    due_hint: Optional[str] = Field(description="'today', 'tomorrow', 'this week', or None")

class ExtractedEntity(BaseModel):
    name: str
    entity_type: Literal["person", "project", "place", "concept", "tool", "company"]

class ExtractedRelationship(BaseModel):
    related_thought_id: str
    relationship_type: Literal["EXTENDS", "CONTRADICTS", "FOLLOWS_FROM", "RELATED", "BLOCKS"]
    reason: str = Field(description="One sentence why these are related")
    strength: float = Field(ge=0.0, le=1.0)

class Stage2Output(BaseModel):
    tasks: List[ExtractedTask] = []
    entities: List[ExtractedEntity] = []
    sub_ideas: List[str] = []
    intent: str = Field(description="Why did user say this? What were they trying to do?")
    relationships: List[ExtractedRelationship] = []
    emotional_tone: Literal["positive", "negative", "neutral", "frustrated", "excited"]
```

## Pipeline Graph

```
START
  ↓
fast_classifier  (Stage 1 — fast model, ~2-3 sec)
  ↓
context_loader   (vector search for related, no LLM)
  ↓
deep_extractor   (Stage 2 — deep model, ~10-15 sec, async)
  ↓
assembler        (pure Python merge, no LLM)
  ↓
writer           (SQLite + LanceDB writes, no LLM)
  ↓
END
```

## Async Queue (queue.py)

```python
import asyncio
from collections import deque

class ProcessingQueue:
    def __init__(self):
        self._queue = asyncio.Queue()
        self._running = False
    
    async def add(self, chunk: RawChunk) -> None:
        await self._queue.put(chunk)
    
    async def start_worker(self):
        """Background worker processes chunks every 3 minutes or when queue has ≥5 items."""
        self._running = True
        while self._running:
            try:
                chunk = await asyncio.wait_for(self._queue.get(), timeout=180)  # 3 min
                await process_chunk(chunk)
            except asyncio.TimeoutError:
                # Drain any remaining items
                while not self._queue.empty():
                    chunk = self._queue.get_nowait()
                    await process_chunk(chunk)
```

## Implementation Notes

### fast_classifier.py

```python
async def fast_classifier(state: ProcessingState) -> dict:
    gateway = get_gateway()
    
    prompt = f"""Classify this thought captured via voice. Be concise.

Thought: "{state['chunk'].raw_text}"

Classify the type, clean the text (remove filler words like "um", "uh", "like"), 
write a one-sentence summary, and assess the speaker's energy level."""

    result: Stage1Output = await gateway.fast(prompt, Stage1Output)
    return {"stage1": result}
```

### context_loader.py

```python
async def context_loader(state: ProcessingState) -> dict:
    # No LLM call — pure vector search
    store = get_store()
    text = state["stage1"].clean_text if state["stage1"] else state["chunk"].raw_text
    related = await store.search(text, limit=5)
    return {"related_thoughts": related}
```

### deep_extractor.py

```python
async def deep_extractor(state: ProcessingState) -> dict:
    gateway = get_gateway()
    
    related_context = "\n".join([f"- {r.summary}" for r in state["related_thoughts"]])
    
    prompt = f"""Extract structured information from this thought.

Thought: "{state['stage1'].clean_text}"
Type: {state['stage1'].thought_type}

Related thoughts already in memory:
{related_context or "None yet"}

Extract: tasks (with priority), entities mentioned, sub-ideas, 
the intent behind this thought, relationships to existing thoughts,
and emotional tone."""

    result: Stage2Output = await gateway.deep(prompt, Stage2Output)
    return {"stage2": result}
```

## Dependencies (Internal)

- `services/llm_gateway/gateway.py` → `fast()`, `deep()`
- `services/memory/store.py` → `search()`, `save_raw_chunk()`, `update_thought()`, `upsert_vector()`
- `shared/schemas/models.py` → all TypedDicts and Pydantic models
- `config/settings.py` → `ProcessingConfig`

## Dependencies (External)

```
langgraph>=0.2.0
langchain-core>=0.3.0
pydantic>=2.0.0
```

## Testing

```python
# Test 1: Feed RawChunk through full pipeline → thought_id returned, DB row exists
# Test 2: Stage 1 classifies "build a new feature for SmartPal" as type="task"
# Test 3: Stage 2 extracts at least 1 task from "I need to call John tomorrow"
# Test 4: context_loader returns 0 results on empty DB, doesn't crash
# Test 5: Writer correctly upserts (run same chunk_id twice → only 1 row in DB)
```
