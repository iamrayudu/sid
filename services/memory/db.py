import aiosqlite
import asyncio
from pathlib import Path
from typing import AsyncGenerator
from contextlib import asynccontextmanager

from config.settings import get_settings

class DatabaseManager:
    # Columns to add to existing tables; each gets its own try/except for idempotency
    _MIGRATIONS = [
        "ALTER TABLE extractions ADD COLUMN milestone_parent_id TEXT",
        "ALTER TABLE extractions ADD COLUMN percentage_complete REAL DEFAULT 0",
        "ALTER TABLE extractions ADD COLUMN time_estimate_hours REAL",
        "ALTER TABLE extractions ADD COLUMN next_step TEXT",
        "ALTER TABLE extractions ADD COLUMN closure_note TEXT",
    ]

    def __init__(self):
        self.settings = get_settings()
        self.db_path = self.settings.db_path
        self.schema_path = Path(__file__).parent / "schema.sql"

    async def init_db(self):
        """Initializes the database, ensures directories exist, executes schema."""
        self.settings.ensure_data_dir()

        with open(self.schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL;")
            await db.execute("PRAGMA synchronous=NORMAL;")
            await db.executescript(schema_sql)
            for sql in self._MIGRATIONS:
                try:
                    await db.execute(sql)
                except aiosqlite.OperationalError:
                    pass  # column already exists
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
