# Memory Service

## Purpose

All persistence for SID. Structured metadata in SQLite, semantic vectors in LanceDB.  
This is the "brain" of SID — everything flows through here eventually.

**Input**: `MemoryEntry` objects from processing pipeline, search queries from agent  
**Output**: Stored entries, semantic search results, daily records, timeline

## Files to Build

```
services/memory/
├── __init__.py          # Exports: MemoryStore, get_store()
├── db.py                # SQLite setup, queries, migrations
├── schema.sql           # CREATE TABLE statements (source of truth)
├── vector_store.py      # LanceDB interface (lazy-loaded singleton)
└── store.py             # Combined MemoryStore class (unified interface)
```

## Database Location

All data lives in `~/.sid/`:
```
~/.sid/
├── sid.db               # SQLite database
└── vectors/             # LanceDB vector store directory
```

Create `~/.sid/` on first run if it doesn't exist.

## SQLite Schema (full — in schema.sql)

```sql
CREATE TABLE IF NOT EXISTS thoughts (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    clean_text TEXT,
    type TEXT,                    -- idea/task/reflection/question/random
    summary TEXT,
    energy_hint TEXT,             -- excited/tired/focused/distracted
    location_hint TEXT,
    processing_stage TEXT DEFAULT 'raw',  -- raw/stage1/stage2/complete
    confidence REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS extractions (
    id TEXT PRIMARY KEY,
    thought_id TEXT NOT NULL,
    type TEXT NOT NULL,           -- task/sub_idea/entity/goal/question
    content TEXT NOT NULL,
    priority INTEGER DEFAULT 3,   -- 1=highest, 5=lowest
    status TEXT DEFAULT 'pending', -- pending/in_progress/done/dropped
    due_date TEXT,
    completed_at TEXT,
    parent_id TEXT,
    FOREIGN KEY(thought_id) REFERENCES thoughts(id)
);

CREATE TABLE IF NOT EXISTS relationships (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    type TEXT NOT NULL,           -- EXTENDS/CONTRADICTS/FOLLOWS_FROM/RELATED/BLOCKS
    strength REAL DEFAULT 0.5,
    reason TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT,
    mode TEXT DEFAULT 'capture',  -- morning_planning/capture/reflection/check_in
    label TEXT,
    thought_count INTEGER DEFAULT 0,
    summary TEXT
);

CREATE TABLE IF NOT EXISTS daily_records (
    date TEXT PRIMARY KEY,
    morning_plan TEXT,            -- JSON: {time_slots: [...], priorities: [...]}
    actual_log TEXT,              -- JSON: what actually happened
    evening_reflection TEXT,
    energy_level TEXT,
    completion_rate REAL,
    pending_items TEXT            -- JSON: carried forward to tomorrow
);

CREATE TABLE IF NOT EXISTS llm_calls (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    model TEXT NOT NULL,
    purpose TEXT NOT NULL,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    latency_ms INTEGER,
    estimated_cost_usd REAL DEFAULT 0.0,
    success INTEGER DEFAULT 1
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_thoughts_session ON thoughts(session_id);
CREATE INDEX IF NOT EXISTS idx_thoughts_date ON thoughts(created_at);
CREATE INDEX IF NOT EXISTS idx_thoughts_type ON thoughts(type);
CREATE INDEX IF NOT EXISTS idx_extractions_thought ON extractions(thought_id);
CREATE INDEX IF NOT EXISTS idx_extractions_status ON extractions(status);
CREATE INDEX IF NOT EXISTS idx_llm_calls_timestamp ON llm_calls(timestamp);
```

## LanceDB Schema

Table name: `thought_vectors`

```python
import lancedb
import pyarrow as pa

schema = pa.schema([
    pa.field("thought_id", pa.string()),
    pa.field("text", pa.string()),          # clean_text (or raw_text if stage1 not done)
    pa.field("vector", pa.list_(pa.float32(), 384)),  # all-MiniLM-L6-v2 output
    pa.field("type", pa.string()),
    pa.field("date", pa.string()),          # YYYY-MM-DD for date filtering
    pa.field("session_id", pa.string()),
])
```

## MemoryStore Interface

```python
class MemoryStore:
    # WRITE
    async def save_raw_chunk(self, chunk: RawChunk) -> str:
        """Save raw chunk before processing. Returns thought_id."""
    
    async def update_thought(self, thought_id: str, updates: dict) -> None:
        """Update thought after stage1 or stage2 processing."""
    
    async def save_extraction(self, extraction: Extraction) -> str:
        """Save a task, idea, entity, etc. extracted from a thought."""
    
    async def save_relationship(self, rel: Relationship) -> str:
        """Save a semantic relationship between two thoughts."""
    
    async def upsert_vector(self, thought_id: str, text: str, meta: dict) -> None:
        """Add or update vector embedding for a thought."""
    
    async def write_llm_call(self, call: LLMCallRecord) -> None:
        """Record an LLM API call for observability."""
    
    # READ
    async def get_thought(self, thought_id: str) -> Optional[Thought]:
        ...
    
    async def get_timeline(self, date: str) -> List[Thought]:
        """All thoughts for a given date (YYYY-MM-DD)."""
    
    async def search(self, query: str, limit: int = 10) -> List[SearchResult]:
        """Semantic search: embed query → LanceDB ANN search → enrich with SQLite metadata."""
    
    async def get_pending_tasks(self) -> List[Extraction]:
        """All extractions with status='pending', ordered by priority."""
    
    async def get_stats(self) -> StatsResult:
        """Usage stats: thought counts, LLM call aggregates, today's summary."""
    
    async def get_unchecked_count(self, since_timestamp: str) -> int:
        """Count thoughts added since given timestamp (for agent check-in trigger)."""
```

## Implementation Notes

### db.py — SQLite

```python
import aiosqlite
from pathlib import Path

DB_PATH = Path.home() / ".sid" / "sid.db"

async def get_db() -> aiosqlite.Connection:
    # Use context manager pattern
    # Run schema.sql on first connection
    # Enable WAL mode for concurrent reads: PRAGMA journal_mode=WAL;

async def init_db():
    # Read schema.sql, execute all CREATE TABLE IF NOT EXISTS statements
    # Called once at startup from main.py
```

### vector_store.py — LanceDB

```python
import lancedb
from pathlib import Path

VECTOR_PATH = str(Path.home() / ".sid" / "vectors")
_db = None
_table = None

def get_table():
    global _db, _table
    if _table is None:
        _db = lancedb.connect(VECTOR_PATH)
        if "thought_vectors" not in _db.table_names():
            _table = _db.create_table("thought_vectors", schema=SCHEMA)
        else:
            _table = _db.open_table("thought_vectors")
    return _table
```

### store.py — Combined Interface

```python
# Imports both db.py and vector_store.py
# Provides the clean MemoryStore class
# search() method:
#   1. Embed query text via llm_gateway
#   2. LanceDB ANN search → get thought_ids + scores
#   3. SQLite fetch full thought data for each id
#   4. Return SearchResult objects with full context
```

## Dependencies (Internal)

- `config/settings.py` → DB paths
- `shared/schemas/models.py` → `RawChunk`, `Thought`, `Extraction`, `Relationship`, etc.
- `services/llm_gateway/gateway.py` → `embed()` for vector store

## Dependencies (External)

```
aiosqlite>=0.19.0
lancedb>=0.6.0
pyarrow>=14.0.0
sentence-transformers>=3.0.0  # via llm_gateway
```

## Testing

```python
# Test 1: init_db() → all tables created, indexes created
# Test 2: save_raw_chunk() → thought row exists in SQLite with processing_stage='raw'
# Test 3: upsert_vector() → LanceDB has 1 row; calling again → still 1 row (upsert)
# Test 4: search("project idea") → returns thoughts sorted by semantic similarity
# Test 5: get_stats() → returns dict with today's thought count and LLM call count
```
