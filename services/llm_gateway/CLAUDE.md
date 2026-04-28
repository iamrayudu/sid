# LLM Gateway Service

## Purpose

Single chokepoint for ALL LLM calls in SID. Every Ollama call, every embedding, goes through here.  
Provides: model routing, structured output, token counting, latency tracking, cost estimation.

**RULE**: No other service should make direct HTTP calls to Ollama. Zero exceptions.

## Files to Build

```
services/llm_gateway/
├── __init__.py      # Exports: LLMGateway, get_gateway()
├── gateway.py       # Main gateway class
└── metrics.py       # Token counting + cost estimation helpers
```

## Interface Contract

```python
class LLMGateway:
    # Fast model (Stage 1): qwen2.5:3b or llama3.2:3b
    async def fast(self, prompt: str, schema: Type[BaseModel]) -> BaseModel:
        ...
    
    # Deep model (Stage 2 + agent): qwen2.5:14b or 16GB model
    async def deep(self, prompt: str, schema: Type[BaseModel]) -> BaseModel:
        ...
    
    # Conversation (agent chat): deep model, no structured output
    async def chat(self, messages: List[dict]) -> str:
        ...
    
    # Embeddings: all-MiniLM-L6-v2 local (NEVER Ollama)
    def embed(self, text: str) -> List[float]:
        ...
    
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        ...
```

## Implementation Notes

### Ollama API

Use `openai` Python client pointed at Ollama:
```python
from openai import AsyncOpenAI
client = AsyncOpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama"  # required but not used
)
```

### Structured Output

Ollama supports JSON schema response format. Use Pydantic model → JSON schema:
```python
response = await client.chat.completions.create(
    model=self.fast_model,
    messages=[{"role": "user", "content": prompt}],
    response_format={
        "type": "json_schema",
        "json_schema": {
            "name": schema.__name__,
            "schema": schema.model_json_schema()
        }
    }
)
result = schema.model_validate_json(response.choices[0].message.content)
```

### Embeddings

Load sentence-transformers ONCE at startup:
```python
from sentence_transformers import SentenceTransformer
model = SentenceTransformer("all-MiniLM-L6-v2")
# Quantize to int8 for speed:
model = SentenceTransformer("all-MiniLM-L6-v2", 
    backend="onnx",
    model_kwargs={"file_name": "onnx/model_qint8.onnx"})
```

### Metrics Recording

Every call (fast, deep, chat) must call `_record_call()` before returning:
```python
async def _record_call(
    self,
    model: str,
    purpose: str,          # "stage1" | "stage2" | "agent_chat" | "morning" | "evening"
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int,
    success: bool
):
    # Write to llm_calls table in SQLite
    # Do NOT await this — fire and forget (asyncio.create_task)
```

The `llm_calls` table schema (in `services/memory/schema.sql`):
```sql
CREATE TABLE llm_calls (
    id TEXT PRIMARY KEY,
    timestamp TEXT,
    model TEXT,
    purpose TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    latency_ms INTEGER,
    estimated_cost_usd REAL,  -- 0.0 for local, but track for future cloud fallback
    success INTEGER           -- 1 or 0
);
```

### Singleton Pattern

```python
_gateway: Optional[LLMGateway] = None

def get_gateway() -> LLMGateway:
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway(get_settings())
    return _gateway
```

## Config (from config/models.yaml)

```yaml
fast_model: qwen2.5:3b
deep_model: qwen2.5:14b
ollama_base_url: http://localhost:11434
embed_model: all-MiniLM-L6-v2

# Local models cost $0 but we track usage for capacity planning
cost_per_1k_tokens:
  qwen2.5:3b: 0.0
  qwen2.5:14b: 0.0
  default: 0.0
```

## Dependencies (Internal)

- `config/settings.py` → `LLMConfig`
- `services/memory/db.py` → `write_llm_call()` for metrics persistence

## Dependencies (External)

```
openai>=1.0.0           # Ollama OpenAI-compatible client
sentence-transformers>=3.0.0
torch>=2.0.0
httpx>=0.25.0           # For health checks
```

## Error Handling

- Ollama not running: raise `GatewayError("Ollama not available at {url}")` with clear message
- Model not found: raise `GatewayError("Model {model} not found in Ollama")`
- Timeout (>30s): retry once, then raise
- JSON parse failure on structured output: retry with explicit "respond only in valid JSON" prefix
- Always record failed calls in `llm_calls` with `success=0`

## Testing

```python
# Test 1: fast() with valid Pydantic schema → returns typed object
# Test 2: embed("hello world") → returns List[float] of length 384
# Test 3: embed_batch(["a", "b"]) → returns 2 vectors, second call faster (cached model)
# Test 4: Ollama down → raises GatewayError with helpful message
# Test 5: After any call → llm_calls table has new row with tokens + latency
```
