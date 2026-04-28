import lancedb
import pyarrow as pa
from typing import List, Dict, Any, Optional

from config.settings import get_settings

SCHEMA = pa.schema([
    pa.field("thought_id", pa.string()),
    pa.field("text", pa.string()),
    pa.field("vector", pa.list_(pa.float32(), 384)),
    pa.field("type", pa.string()),
    pa.field("date", pa.string()),
    pa.field("session_id", pa.string()),
])

class VectorStore:
    def __init__(self):
        self.settings = get_settings()
        self.db = None
        self.table = None

    def _ensure_table(self):
        if self.db is None:
            self.settings.ensure_data_dir()
            # connect handles the path natively
            self.db = lancedb.connect(str(self.settings.vector_path))
            
        if self.table is None:
            tbl_names = self.db.table_names()
            if "thought_vectors" not in tbl_names:
                self.table = self.db.create_table("thought_vectors", schema=SCHEMA)
            else:
                self.table = self.db.open_table("thought_vectors")

    def upsert(self, data: List[Dict[str, Any]]):
        """
        Upsert vectors. Data must exactly match the pyarrow schema dict shapes.
        """
        self._ensure_table()
        # lancedb replaces matching keys implicitly utilizing the index if configured,
        # but in LanceDB merge_insert is more explicit. For simplicity we use add() which appends.
        # However, to simulate upsert without complex primary key definitions in pa schema,
        # we can delete the old vector and add the new one.
        thought_ids = [row["thought_id"] for row in data]
        if thought_ids:
            ids_str = ", ".join(f"'{id}'" for id in thought_ids)
            # Delete old rows to prevent duplication
            self.table.delete(f"thought_id IN ({ids_str})")
        
        # Add new rows
        self.table.add(data)

    def search(self, vector: List[float], limit: int = 10, filter_expr: Optional[str] = None):
        """
        Semantic search. Returns the raw arrow table records cast to dictionaries.
        """
        self._ensure_table()
        query = self.table.search(vector).limit(limit)
        if filter_expr:
            query = query.where(filter_expr, prefilter=True)
            
        # Convert to list of dictionaries
        return query.to_list()

# Singleton
_vector_store = None

def get_vector_store() -> VectorStore:
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store
