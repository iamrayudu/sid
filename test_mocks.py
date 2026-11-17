import asyncio
import logging
from config.settings import get_settings
from services.llm_gateway import get_gateway
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)

class DummyClassification(BaseModel):
    intent: str = Field(description="The primary intent: Task, Goal, Journal, or Question")
    confidence: float = Field(description="Confidence from 0.0 to 1.0")

async def test_brain():
    print("========================================")
    print("SID MOCK & BRAIN DIAGNOSTIC SEQUENCE")
    print("========================================")

    gateway = get_gateway()
    
    print("\n[1] Testing Reflex Engine (stage1 -> qwen2.5:3b)...")
    try:
        result = await gateway.generate(
            purpose="stage1",
            prompt="Remind me to call the accountant tomorrow at 9am about the LLC filing.",
            schema=DummyClassification
        )
        print(f"✅ SUCCESS: {result}")
    except Exception as e:
        print(f"❌ FAILED stage1: {e}")

    print("\n[2] Testing Deep Cortex (agent_chat -> qwen2.5:14b) with Interrogation Mode...")
    try:
        response = await gateway.chat_for(
            purpose="agent_chat",
            messages=[
                {"role": "system", "content": "You are SID. Ask 2 clarifying questions before answering a vague request."},
                {"role": "user", "content": "How do I make my project better?"}
            ]
        )
        print(f"✅ SUCCESS: \n{response}")
    except Exception as e:
        print(f"❌ FAILED agent_chat: {e}")

    print("\n[3] Testing Analytical Judge (critique -> phi4)...")
    try:
        response = await gateway.chat_for(
            purpose="critique",
            messages=[
                {"role": "system", "content": "You are a harsh behavioral critic. Evaluate this journal entry."},
                {"role": "user", "content": "I scrolled Twitter for 4 hours instead of coding Phase 4."}
            ]
        )
        print(f"✅ SUCCESS: \n{response}")
    except Exception as e:
        print(f"❌ FAILED critique: {e}")

if __name__ == "__main__":
    asyncio.run(test_brain())
