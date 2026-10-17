"""Settings, read from environment variables (see .env.example)."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    mongo_url: str = os.getenv("MONGO_URL", "mongodb://localhost:27017")
    mongo_db: str = os.getenv("MONGO_DB", "call_insights")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    queue_key: str = "jobs:analyse"
    cache_ttl_seconds: int = int(os.getenv("CACHE_TTL_SECONDS", "600"))
    # LLM provider: "rules" (offline baseline, no key needed) or "gemini" (needs GEMINI_API_KEY)
    llm_provider: str = os.getenv("LLM_PROVIDER", "rules")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
    llm_timeout_seconds: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "45"))
    max_llm_attempts: int = 3
    # Run the queue worker inside the API process (for single-service free hosting such as Render)
    run_worker: bool = os.getenv("RUN_WORKER", "false").lower() == "true"


settings = Settings()
