from typing import Optional
from services.llm_gateway.gateway import LLMGateway, GatewayError

_gateway: Optional[LLMGateway] = None

def get_gateway() -> LLMGateway:
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway

__all__ = ["LLMGateway", "get_gateway", "GatewayError"]
