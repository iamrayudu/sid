from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Ollama
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    fast_model: str = Field(default="qwen2.5:3b", alias="SID_FAST_MODEL")
    deep_model: str = Field(default="qwen2.5:14b", alias="SID_DEEP_MODEL")

    # Data
    data_dir: Path = Field(default=Path.home() / ".sid", alias="SID_DATA_DIR")

    # Scheduler
    morning_hour: int = Field(default=8, alias="SID_MORNING_HOUR")
    evening_hour: int = Field(default=21, alias="SID_EVENING_HOUR")

    # Agent
    checkin_threshold: int = Field(default=1, alias="SID_CHECKIN_THRESHOLD")
    checkin_interval_hours: int = Field(default=4, alias="SID_CHECKIN_INTERVAL_HOURS")

    # Voice
    whisper_model: str = Field(default="base.en", alias="SID_WHISPER_MODEL")
    sample_rate: int = Field(default=16000, alias="SID_SAMPLE_RATE")
    max_recording_seconds: int = Field(default=60, alias="SID_MAX_RECORDING_SECONDS")
    vad_threshold: float = Field(default=0.5, alias="SID_VAD_THRESHOLD")

    # API
    api_port: int = Field(default=8765, alias="SID_API_PORT")
    api_host: str = Field(default="127.0.0.1", alias="SID_API_HOST")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "sid.db"

    @property
    def vector_path(self) -> Path:
        return self.data_dir / "vectors"

    def ensure_data_dir(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.vector_path.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
