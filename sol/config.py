from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Zerodha Kite Connect ---
    KITE_API_KEY: str = ""
    KITE_API_SECRET: str = ""
    KITE_REDIRECT_URL: str = "http://localhost:8000/api/auth/callback"

    # --- LLM API Keys ---
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    GOOGLE_API_KEY: str = ""

    # --- News ---
    FINNHUB_API_KEY: str = ""  # Optional: https://finnhub.io — free tier available

    # --- Database ---
    DATABASE_URL: str = "postgresql+asyncpg://sol:solpass@localhost:5432/soldb"
    REDIS_URL: str = "redis://localhost:6379"

    # --- Security ---
    SECRET_KEY: str = "change-me-in-production-minimum-32-chars"
    # Zerodha client ID allowed to log in. Any other account is rejected at the OAuth callback.
    ALLOWED_KITE_USER_ID: str = "YU5831"

    # --- Trading Mode ---
    PAPER_TRADING_MODE: bool = True  # Default SAFE

    # --- Risk Defaults ---
    MAX_CAPITAL_PCT: float = 2.0
    DAILY_LOSS_LIMIT_PCT: float = 5.0
    MAX_OPEN_POSITIONS: int = 5
    MAX_POSITION_SIZE_PCT: float = 10.0

    # --- App Settings ---
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    CORS_ORIGINS: str = "http://localhost:3001,http://localhost:5173"

    # --- Sol Model (Orchestrator) ---
    SOL_MODEL: str = "claude-opus-4-6"

    # --- Agent Analysis Interval (minutes) ---
    AGENT_INTERVAL_MINUTES: int = 15

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]


@lru_cache
def get_settings() -> Settings:
    return Settings()
