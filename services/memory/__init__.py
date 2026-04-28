from typing import Optional
from services.memory.store import MemoryStore

_store: Optional[MemoryStore] = None

def get_store() -> MemoryStore:
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store

__all__ = ["MemoryStore", "get_store"]
