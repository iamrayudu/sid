# Agent Service

## Purpose

The behavior engine of SID. Manages proactive interactions, daily routines, and conversational memory retrieval.  
This is what makes SID feel like a companion, not just a recorder.

**Core principle**: Capture first. Intelligence second. Interruption only when earned.

## Files to Build

```
services/agent/
├── __init__.py          # Exports: AgentService, get_agent()
├── fsm.py               # Finite State Machine (states + transitions)
├── scheduler.py         # APScheduler jobs (hourly, morning, evening)
├── chat_agent.py        # LangChain tool-calling agent (query memory)
└── routines/
    ├── morning.py       # Morning briefing generator
    └── evening.py       # Evening reflection + journal generator
```

## Agent FSM (fsm.py)

```python
from enum import Enum

class AgentState(Enum):
    IDLE = "idle"
    CAPTURING = "capturing"
    PROCESSING = "processing"
    CHECK_IN = "check_in"
    PLANNING = "planning"
    REFLECTING = "reflecting"

class AgentFSM:
    def __init__(self):
        self.state = AgentState.IDLE
        self._suppressed_until: Optional[datetime] = None
    
    def transition(self, to: AgentState) -> bool:
        """Returns True if transition allowed."""
        allowed = TRANSITION_RULES[self.state]
        if to in allowed:
            self.state = to
            return True
        return False
    
    def can_interrupt(self) -> bool:
        """Check if agent is allowed to proactively speak."""
        if self.state == AgentState.CAPTURING:
            return False  # NEVER interrupt while user is speaking
        if self._suppressed_until and datetime.now() < self._suppressed_until:
            return False  # User said "not now"
        return True
    
    def suppress(self, hours: int = 2):
        """User said 'not now' — suppress check-ins for N hours."""
        self._suppressed_until = datetime.now() + timedelta(hours=hours)

# Valid transitions
TRANSITION_RULES = {
    AgentState.IDLE: [AgentState.CAPTURING, AgentState.CHECK_IN, AgentState.PLANNING, AgentState.REFLECTING],
    AgentState.CAPTURING: [AgentState.IDLE, AgentState.PROCESSING],
    AgentState.PROCESSING: [AgentState.IDLE, AgentState.CAPTURING],
    AgentState.CHECK_IN: [AgentState.IDLE, AgentState.CAPTURING, AgentState.REFLECTING],
    AgentState.PLANNING: [AgentState.IDLE, AgentState.CAPTURING],
    AgentState.REFLECTING: [AgentState.IDLE, AgentState.CAPTURING],
}
```

## Scheduler (scheduler.py)

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler

class SIDScheduler:
    def __init__(self, agent_fsm: AgentFSM, memory: MemoryStore, notify_fn):
        self.scheduler = AsyncIOScheduler()
        self._setup_jobs()
    
    def _setup_jobs(self):
        # Hourly check-in
        self.scheduler.add_job(
            self._hourly_checkin,
            'interval', hours=1,
            id='hourly_checkin'
        )
        
        # Morning brief (configurable time, default 8am)
        self.scheduler.add_job(
            self._morning_brief,
            'cron', hour=settings.morning_hour, minute=0,
            id='morning_brief'
        )
        
        # Evening reflection (configurable time, default 9pm)
        self.scheduler.add_job(
            self._evening_reflection,
            'cron', hour=settings.evening_hour, minute=0,
            id='evening_reflection'
        )
    
    async def _hourly_checkin(self):
        """Fires only if agent can interrupt AND ≥3 new thoughts since last check-in."""
        if not self.fsm.can_interrupt():
            return
        
        last_checkin = await self.memory.get_last_checkin_time()
        new_count = await self.memory.get_unchecked_count(since=last_checkin)
        
        if new_count >= 3:
            self.fsm.transition(AgentState.CHECK_IN)
            checkin_text = await self._generate_checkin(new_count)
            self.notify_fn(checkin_text, type="checkin")
```

## Chat Agent (chat_agent.py)

LangChain tool-calling agent. User talks to SID, SID queries memory.

```python
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain.tools import tool
from langchain_community.chat_models import ChatOllama

@tool
def search_memory(query: str) -> str:
    """
    Search Sudheer's personal memory for thoughts, ideas, and notes.
    Use for: finding past thoughts, checking status of ideas, retrieving context.
    """
    results = asyncio.run(get_store().search(query, limit=5))
    return format_results(results)

@tool
def get_pending_tasks() -> str:
    """
    Get all pending tasks and action items from Sudheer's memory.
    Use for: checking what needs to be done, planning the day.
    """
    tasks = asyncio.run(get_store().get_pending_tasks())
    return format_tasks(tasks)

@tool
def get_today_timeline() -> str:
    """
    Get all thoughts captured today in chronological order.
    Use for: reviewing the day, understanding what was discussed.
    """
    today = date.today().isoformat()
    thoughts = asyncio.run(get_store().get_timeline(today))
    return format_timeline(thoughts)

SYSTEM_PROMPT = """You are SID — Sudheer's personal cognitive companion.
You have access to his complete thought history, tasks, and notes via memory tools.

Your behavior:
- Be concise and direct — Sudheer thinks fast, keep up
- Surface patterns across days when relevant
- Challenge ideas gently when you see contradictions
- Keep him focused when he drifts
- Reference specific past thoughts by date when relevant

Never:
- Make up information not in memory
- Be verbose or add unnecessary preamble
- Say "As an AI..." or similar hedging
"""
```

## Morning Routine (routines/morning.py)

```python
async def generate_morning_brief(memory: MemoryStore, gateway: LLMGateway) -> str:
    """
    Pulls: pending tasks, yesterday's incomplete items, recent ideas worth following up.
    Generates: day plan with time slots + one anchor question.
    """
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    pending = await memory.get_pending_tasks()
    yesterday_thoughts = await memory.get_timeline(yesterday)
    
    prompt = f"""Generate Sudheer's morning brief.

Pending tasks:
{format_tasks(pending)}

Yesterday's thoughts:
{format_timeline(yesterday_thoughts)}

Create:
1. Top 3 priorities for today (with time estimates)
2. One carry-forward idea worth pursuing
3. One focused question to start the day

Be concise. No fluff."""

    return await gateway.chat([{"role": "user", "content": prompt}])
```

## Evening Routine (routines/evening.py)

```python
async def generate_evening_reflection(memory: MemoryStore, gateway: LLMGateway) -> str:
    """
    Reviews today's thoughts, completed tasks, patterns.
    Generates: readable journal entry + tomorrow prep.
    """
    today = date.today().isoformat()
    thoughts = await memory.get_timeline(today)
    
    prompt = f"""Generate Sudheer's evening reflection.

Today's thoughts ({len(thoughts)} captured):
{format_timeline(thoughts)}

Write:
1. A short journal paragraph about today (2-3 sentences, first person)
2. What got done vs. what's still pending
3. One insight or pattern you notice
4. 2 things to carry forward to tomorrow

Be honest and direct."""

    reflection = await gateway.chat([{"role": "user", "content": prompt}])
    
    # Save to daily_records
    await memory.save_daily_reflection(today, reflection)
    return reflection
```

## Check-in Content

When hourly check-in fires, generate:
```
"You've added 4 thoughts in the last hour. 
Quick status check: you mentioned working on [X from most recent task]. 
Still on it? Also noting: [most interesting idea from recent thoughts]."
```

## Dependencies (Internal)

- `services/memory/store.py` → all memory queries
- `services/llm_gateway/gateway.py` → `chat()` for generation
- `shared/schemas/models.py` → shared types
- `config/settings.py` → `AgentConfig` (morning_hour, evening_hour, checkin_threshold)

## Dependencies (External)

```
langgraph>=0.2.0
langchain>=0.3.0
langchain-community>=0.3.0
apscheduler>=3.10.0
```

## Config (in config/settings.py)

```python
class AgentConfig(BaseModel):
    morning_hour: int = 8       # 8 AM
    evening_hour: int = 21      # 9 PM
    checkin_threshold: int = 3  # Min thoughts before hourly check-in fires
    checkin_interval_hours: int = 1
    suppress_duration_hours: int = 2  # "not now" suppression duration
```

## Testing

```python
# Test 1: FSM starts in IDLE
# Test 2: CAPTURING state → can_interrupt() returns False
# Test 3: suppress(2) → can_interrupt() returns False for 2 hours
# Test 4: get_unchecked_count() returns 0 on empty DB
# Test 5: Morning brief with 0 tasks → graceful empty state message
# Test 6: Chat agent calls search_memory tool and returns non-empty result
```
