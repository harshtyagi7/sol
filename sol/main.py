"""
Sol Trading System — FastAPI Application Entry Point
"""

import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from sol.config import get_settings

# Configure structured logging
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
)
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    settings = get_settings()
    logger.info("Sol starting up...", mode="PAPER" if settings.PAPER_TRADING_MODE else "LIVE")

    # Initialize database
    from sol.database import init_db, dispose_engine
    await init_db()
    logger.info("Database initialized")

    # Seed default risk config if needed
    await _seed_defaults()

    # Restore Kite session from DB if available
    await _restore_kite_session()

    # Start scheduler
    from sol.core.scheduler import setup_scheduler, get_scheduler
    scheduler = setup_scheduler()
    scheduler.start()
    logger.info("Scheduler started")

    yield  # Application runs here

    # Shutdown
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
    await dispose_engine()
    logger.info("Sol shutdown complete")


async def _seed_defaults():
    """Seed default risk config and example agents if DB is empty."""
    from sol.database import get_session
    from sol.models.risk_config import RiskConfig
    from sol.models.agent import Agent
    from sol.config import get_settings
    from sqlalchemy import select, func

    settings = get_settings()

    async with get_session() as db:
        # Seed risk config
        count = await db.execute(select(func.count()).select_from(RiskConfig))
        if count.scalar() == 0:
            db.add(RiskConfig(
                max_capital_pct=settings.MAX_CAPITAL_PCT,
                daily_loss_limit_pct=settings.DAILY_LOSS_LIMIT_PCT,
                max_open_positions=settings.MAX_OPEN_POSITIONS,
                max_position_size_pct=settings.MAX_POSITION_SIZE_PCT,
            ))
            logger.info("Default risk config seeded")

        # Seed default agents per provider — runs on every startup so adding
        # a new API key later will insert the missing agent automatically.
        existing = await db.execute(select(Agent.llm_provider))
        existing_providers = {row[0] for row in existing.fetchall()}

        defaults = [
            ("anthropic", "sol-alpha",     "claude-sonnet-4-6", settings.ANTHROPIC_API_KEY),
            ("openai",    "gpt-beta",      "gpt-4o",            settings.OPENAI_API_KEY),
            ("google",    "gemini-gamma",  "gemini-2.0-flash",  settings.GOOGLE_API_KEY),
        ]
        for provider, name, model, key in defaults:
            if key and provider not in existing_providers:
                db.add(Agent(
                    name=name,
                    llm_provider=provider,
                    model_id=model,
                    strategy_prompt="",
                    is_active=True,
                    paper_only=False,
                    virtual_capital=1_000_000.0,
                ))
                logger.info(f"Default {provider} agent seeded", name=name)

        await db.flush()


async def _restore_kite_session():
    """Restore valid Kite access token from DB on startup."""
    from sol.database import get_session
    from sol.models.session import KiteSession
    from sol.broker.kite_client import get_kite_client
    from sol.config import get_settings
    from sol.utils.encryption import decrypt
    from sqlalchemy import select
    from datetime import datetime
    import pytz
    IST = pytz.timezone("Asia/Kolkata")

    settings = get_settings()
    if not settings.KITE_API_KEY:
        return

    async with get_session() as db:
        result = await db.execute(
            select(KiteSession)
            .where(KiteSession.is_valid == True)
            .order_by(KiteSession.created_at.desc())
            .limit(1)
        )
        session = result.scalar_one_or_none()

    if session and session.token_expiry:
        now = datetime.now(IST)
        if now < session.token_expiry:
            try:
                token = decrypt(session.access_token_encrypted, settings.SECRET_KEY)
                client = get_kite_client()
                client.set_access_token(token)
                logger.info("Kite session restored from DB", user=session.user_name)
            except Exception as e:
                logger.warning(f"Could not restore Kite session: {e}")
        else:
            logger.warning("Stored Kite session has expired. Please re-login at /api/auth/login")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Sol Trading System",
        description="AI-powered trading orchestrator for Indian stock market",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routes
    from sol.api.router import api_router
    app.include_router(api_router)

    # Health check
    @app.get("/health")
    async def health():
        from sol.utils.market_hours import market_status_str
        return {
            "status": "ok",
            "mode": "PAPER" if settings.PAPER_TRADING_MODE else "LIVE",
            "market": market_status_str(),
        }

    # Serve built React frontend (production only — dev uses Vite on port 5173)
    import os
    frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
    if os.path.isdir(frontend_dist):
        from fastapi.responses import FileResponse
        app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dist, "assets")), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_spa(full_path: str):
            """Catch-all: serve index.html for React SPA routing."""
            return FileResponse(os.path.join(frontend_dist, "index.html"))

    return app


app = create_app()
