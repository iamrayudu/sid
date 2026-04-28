-- SID Memory Database Schema
-- All tables use CREATE TABLE IF NOT EXISTS for safe re-runs

CREATE TABLE IF NOT EXISTS thoughts (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    clean_text TEXT,
    type TEXT,
    summary TEXT,
    energy_hint TEXT,
    location_hint TEXT,
    processing_stage TEXT DEFAULT 'raw',
    confidence REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS extractions (
    id TEXT PRIMARY KEY,
    thought_id TEXT NOT NULL,
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    priority INTEGER DEFAULT 3,
    status TEXT DEFAULT 'pending',
    due_date TEXT,
    completed_at TEXT,
    parent_id TEXT,
    FOREIGN KEY(thought_id) REFERENCES thoughts(id)
);

CREATE TABLE IF NOT EXISTS relationships (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    type TEXT NOT NULL,
    strength REAL DEFAULT 0.5,
    reason TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT,
    mode TEXT DEFAULT 'capture',
    label TEXT,
    thought_count INTEGER DEFAULT 0,
    summary TEXT
);

CREATE TABLE IF NOT EXISTS daily_records (
    date TEXT PRIMARY KEY,
    morning_plan TEXT,
    actual_log TEXT,
    evening_reflection TEXT,
    energy_level TEXT,
    completion_rate REAL,
    pending_items TEXT
);

CREATE TABLE IF NOT EXISTS llm_calls (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    model TEXT NOT NULL,
    purpose TEXT NOT NULL,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    latency_ms INTEGER DEFAULT 0,
    estimated_cost_usd REAL DEFAULT 0.0,
    success INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS processing_queue (
    id TEXT PRIMARY KEY,
    chunk_json TEXT NOT NULL,
    priority INTEGER DEFAULT 5,
    status TEXT DEFAULT 'pending',
    retries INTEGER DEFAULT 0,
    last_error TEXT,
    enqueued_at TEXT NOT NULL,
    processed_at TEXT,
    retry_after TEXT
);

CREATE TABLE IF NOT EXISTS task_closures (
    id TEXT PRIMARY KEY,
    extraction_id TEXT NOT NULL,
    learning TEXT,
    what_went_wrong TEXT,
    would_do_differently TEXT,
    negligence_flagged INTEGER DEFAULT 0,
    energy_reflection TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(extraction_id) REFERENCES extractions(id)
);

CREATE TABLE IF NOT EXISTS weekly_records (
    week_start TEXT PRIMARY KEY,
    week_end TEXT NOT NULL,
    reflection TEXT,
    planned_tasks INTEGER DEFAULT 0,
    completed_tasks INTEGER DEFAULT 0,
    completion_rate REAL,
    patterns TEXT,
    key_learning TEXT,
    created_at TEXT NOT NULL
);

-- Performance indexes
CREATE INDEX IF NOT EXISTS idx_thoughts_session ON thoughts(session_id);
CREATE INDEX IF NOT EXISTS idx_thoughts_date ON thoughts(created_at);
CREATE INDEX IF NOT EXISTS idx_thoughts_type ON thoughts(type);
CREATE INDEX IF NOT EXISTS idx_thoughts_stage ON thoughts(processing_stage);
CREATE INDEX IF NOT EXISTS idx_extractions_thought ON extractions(thought_id);
CREATE INDEX IF NOT EXISTS idx_extractions_status ON extractions(status);
CREATE INDEX IF NOT EXISTS idx_extractions_created ON extractions(thought_id, status);
CREATE INDEX IF NOT EXISTS idx_llm_calls_timestamp ON llm_calls(timestamp);
CREATE INDEX IF NOT EXISTS idx_llm_calls_model ON llm_calls(model);
CREATE INDEX IF NOT EXISTS idx_task_closures_extraction ON task_closures(extraction_id);
CREATE INDEX IF NOT EXISTS idx_queue_pickup ON processing_queue(status, priority, enqueued_at);
