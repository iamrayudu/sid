"""SID startup entrypoint.

Starts the FastAPI server (which initialises all services via lifespan).
Run: python main.py
"""
import uvicorn
from config.settings import get_settings


def main():
    settings = get_settings()
    settings.ensure_data_dir()

    print(f"Starting SID on http://{settings.api_host}:{settings.api_port}")
    print(f"Data directory: {settings.data_dir}")
    print(f"Docs watch dir: ~/Documents/SID/")

    uvicorn.run(
        "interface.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
