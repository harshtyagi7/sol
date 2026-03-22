from fastapi import APIRouter, Depends

from sol.api.agents import router as agents_router
from sol.api.auth import router as auth_router, verify_session
from sol.api.chat import router as chat_router
from sol.api.dashboard import router as dashboard_router
from sol.api.news import router as news_router
from sol.api.options import router as options_router
from sol.api.portfolio import router as portfolio_router
from sol.api.risk import router as risk_router
from sol.api.settings import router as settings_router
from sol.api.strategies import router as strategies_router
from sol.api.trades import router as trades_router

api_router = APIRouter()

# Auth routes are public (needed to log in in the first place)
api_router.include_router(auth_router)

# All other routes require a valid Kite session
_protected = {"dependencies": [Depends(verify_session)]}
api_router.include_router(trades_router, **_protected)
api_router.include_router(strategies_router, **_protected)
api_router.include_router(portfolio_router, **_protected)
api_router.include_router(agents_router, **_protected)
api_router.include_router(risk_router, **_protected)
api_router.include_router(dashboard_router, **_protected)
api_router.include_router(news_router, **_protected)
api_router.include_router(options_router, **_protected)
api_router.include_router(settings_router, **_protected)
# Chat router is registered without the session dependency because WebSocket
# upgrade requests cannot carry HTTP-level auth headers; the WS handlers do
# their own post-accept auth check instead.
api_router.include_router(chat_router)
