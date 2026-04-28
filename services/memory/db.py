import aiosqlite
import asyncio
from pathlib import Path
from typing import AsyncGenerator
from contextlib import asynccontextmanager

from config.settings import get_settings

class DatabaseManager:
    def __init__(self):
        self.settings = get_settings()
        self.db_path = self.settings.db_path
        self.schema_path = Path(__file__).parent / "schema.sql"

    async def init_db(self):
        """Initializes the database, ensures directories exist, executes schema."""
        self.settings.ensure_data_dir()
        
        # Read the schema file
        with open(self.schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()
            
        async with aiosqlite.connect(self.db_path) as db:
            # Enable WAL mode for concurrent write resilience and read speeds
            await db.execute("PRAGMA journal_mode=WAL;")
            # Synchronous PRAGMA is generally NORMAL in WAL mode
            await db.execute("PRAGMA synchronous=NORMAL;")
            await db.executescript(schema_sql)
            
            # P0 Migration: Add extended columns to extractions (idempotently)
            try:
                await db.execute("ALTER TABLE extractions ADD COLUMN milestone_parent_id TEXT;")
                await db.execute("ALTER TABLE extractions ADD COLUMN percentage_complete REAL DEFAULT 0;")
                await db.execute("ALTER TABLE extractions ADD COLUMN time_estimate_hours REAL;")
                await db.execute("ALTER TABLE extractions ADD COLUMN next_step TEXT;")
                await db.execute("ALTER TABLE extractions ADD COLUMN closure_note TEXT;")
            except aiosqlite.OperationalError as e:
                # OperationalError: duplicate column name
                if "duplicate column name" not in str(e).lower():
                    print(f"Migration warning: {e}")
            
            await db.commit()

    @asynccontextmanager
    async def get_connection(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """Provides an isolated connection per query or transaction block."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row # Dict-like access
            yield db

# Singleton
_db_manager = None

def get_db_manager() -> DatabaseManager:
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager
