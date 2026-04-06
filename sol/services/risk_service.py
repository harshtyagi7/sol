"""Risk service — builds RiskEngine with live context and validates proposals."""

import logging
from typing import Optional

from sol.config import get_settings
from sol.schemas.risk import RiskExposureReport
from sol.schemas.trade import RiskReport, TradeProposalCreate

logger = logging.getLogger(__name__)


class RiskService:
    async def _get_risk_config(self):
        from sol.database import get_session
        from sol.models.risk_config import RiskConfig
        from sqlalchemy import select

        async with get_session() as db:
            result = await db.execute(
                select(RiskConfig).where(RiskConfig.is_active == True).limit(1)
            )
            cfg = result.scalar_one_or_none()
            if cfg is None:
                # Create default config
                settings = get_settings()
                cfg = RiskConfig(
                    max_capital_pct=settings.MAX_CAPITAL_PCT,
                    daily_loss_limit_pct=settings.DAILY_LOSS_LIMIT_PCT,
                    max_open_positions=settings.MAX_OPEN_POSITIONS,
                    max_position_size_pct=settings.MAX_POSITION_SIZE_PCT,
                )
                db.add(cfg)
                await db.flush()
            return cfg

    async def _get_daily_pnl(self) -> float:
        from sol.database import get_session
        from sol.models.position import Position
        from sol.core.trading_mode import get_paper_mode
        from sqlalchemy import select, func
        from datetime import datetime
        import pytz
        IST = pytz.timezone("Asia/Kolkata")
        today = datetime.now(IST).date()
        is_virtual = get_paper_mode()

        async with get_session() as db:
            result = await db.execute(
                select(func.sum(Position.realized_pnl)).where(
                    func.date(Position.closed_at) == today,
                    Position.status != "OPEN",
                    Position.is_virtual == is_virtual,
                )
            )
            realized = result.scalar() or 0.0

            result2 = await db.execute(
                select(Position).where(Position.status == "OPEN", Position.is_virtual == is_virtual)
            )
            open_positions = result2.scalars().all()
            unrealized = sum(p.unrealized_pnl for p in open_positions)

            return float(realized or 0) + unrealized

    async def _get_open_position_count(self) -> int:
        from sol.database import get_session
        from sol.models.position import Position
        from sol.core.trading_mode import get_paper_mode
        from sqlalchemy import select, func
        is_virtual = get_paper_mode()

        async with get_session() as db:
            result = await db.execute(
                select(func.count()).select_from(Position).where(
                    Position.status == "OPEN",
                    Position.is_virtual == is_virtual,
                )
            )
            return result.scalar() or 0

    async def validate_proposal(self, proposal: TradeProposalCreate) -> RiskReport:
        from sol.core.risk_engine import RiskEngine
        from sol.broker.order_manager import get_order_manager

        cfg = await self._get_risk_config()
        om = get_order_manager()
        capital = om.get_available_capital()
        daily_pnl = await self._get_daily_pnl()
        open_count = await self._get_open_position_count()

        engine = RiskEngine(cfg, capital, daily_pnl, open_count)
        return engine.validate(proposal)

    async def get_exposure_report(self) -> dict:
        from sol.core.risk_engine import RiskEngine
        from sol.broker.order_manager import get_order_manager

        cfg = await self._get_risk_config()
        om = get_order_manager()
        capital = om.get_available_capital()
        daily_pnl = await self._get_daily_pnl()
        open_count = await self._get_open_position_count()

        engine = RiskEngine(cfg, capital, daily_pnl, open_count)
        return engine.check_exposure_summary()


_risk_service: Optional[RiskService] = None


def get_risk_service() -> RiskService:
    global _risk_service
    if _risk_service is None:
        _risk_service = RiskService()
    return _risk_service
