import uuid
import datetime

from shared.schemas.models import LLMCallRecord

class MetricsTracker:
    @staticmethod
    def create_record(
        model: str,
        purpose: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int,
        success: bool,
        cost_per_1k: float = 0.0
    ) -> LLMCallRecord:
        
        # Calculate cost
        total_tokens = prompt_tokens + completion_tokens
        cost = (total_tokens / 1000.0) * cost_per_1k

        return LLMCallRecord(
            id=str(uuid.uuid4()),
            timestamp=datetime.datetime.utcnow().isoformat() + "Z",
            model=model,
            purpose=purpose,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            estimated_cost_usd=cost,
            success=1 if success else 0
        )
