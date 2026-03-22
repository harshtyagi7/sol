"""App-level settings endpoints — trading mode toggle."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/mode")
async def get_mode():
    from sol.core.trading_mode import get_paper_mode
    paper = get_paper_mode()
    return {"mode": "PAPER" if paper else "LIVE", "paper_trading": paper}


@router.post("/mode")
async def set_mode(paper_trading: bool):
    """Switch between PAPER and LIVE trading at runtime."""
    from sol.core.trading_mode import set_paper_mode, get_paper_mode
    import logging
    logger = logging.getLogger(__name__)

    previous = get_paper_mode()
    set_paper_mode(paper_trading)

    mode = "PAPER" if paper_trading else "LIVE"
    logger.warning(f"Trading mode changed: {'PAPER' if previous else 'LIVE'} → {mode}")
    return {"mode": mode, "paper_trading": paper_trading}
