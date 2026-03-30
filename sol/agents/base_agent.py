"""Abstract base class for all trading sub-agents."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from sol.schemas.strategy import StrategyProposal

logger = logging.getLogger(__name__)


@dataclass
class MarketDataSnapshot:
    """Data provided to agents for analysis."""
    symbol: str
    exchange: str
    current_price: float
    ohlcv_daily: list[dict]  # list of {date, open, high, low, close, volume}
    ohlcv_15min: list[dict]
    indicators: dict = field(default_factory=dict)  # RSI, MACD, etc.
    news_headlines: list[str] = field(default_factory=list)
    sector_performance: dict = field(default_factory=dict)
    # F&O data (populated for index underlyings like NIFTY 50, NIFTY BANK)
    option_chain: list[dict] = field(default_factory=list)  # ATM ± strikes with OI, LTP, IV
    futures_price: Optional[float] = None  # nearest-month futures LTP
    pcr: Optional[float] = None  # put-call ratio (OI-based)


@dataclass
class VirtualPosition:
    symbol: str
    exchange: str
    direction: str
    quantity: int
    avg_price: float
    current_price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None

    @property
    def unrealized_pnl(self) -> float:
        mult = 1 if self.direction == "BUY" else -1
        return mult * (self.current_price - self.avg_price) * self.quantity


class VirtualPortfolio:
    """Tracks virtual performance of an agent."""

    def __init__(self, initial_capital: float = 1_000_000.0):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: list[VirtualPosition] = []
        self.closed_trades: list[dict] = []

    @property
    def total_value(self) -> float:
        invested = sum(p.avg_price * p.quantity for p in self.positions)
        unrealized = sum(p.unrealized_pnl for p in self.positions)
        return self.cash + invested + unrealized

    @property
    def total_pnl(self) -> float:
        return self.total_value - self.initial_capital

    @property
    def win_rate(self) -> float:
        if not self.closed_trades:
            return 0.0
        wins = sum(1 for t in self.closed_trades if t.get("pnl", 0) > 0)
        return wins / len(self.closed_trades) * 100


class BaseAgent(ABC):
    """All trading sub-agents implement this interface."""

    def __init__(self, agent_id: str, name: str, model_id: str, virtual_capital: float = 1_000_000.0):
        self.agent_id = agent_id
        self.name = name
        self.model_id = model_id
        self.virtual_portfolio = VirtualPortfolio(virtual_capital)
        self.logger = logging.getLogger(f"agent.{name}")

    @abstractmethod
    async def analyze_and_propose(
        self,
        market_snapshots: list[MarketDataSnapshot],
        open_positions: list[dict],
        performance_context: str = "",
    ) -> "list[StrategyProposal]":  # noqa: F821
        """
        Analyze market data and return strategy proposals.
        Each strategy contains all planned trades and worst-case max loss.
        User approves the strategy once with a loss cap — individual trades execute autonomously.
        """

    async def review_strategy(
        self,
        proposal: "StrategyProposal",
        market_context: str,
        proposing_agent_name: str,
    ) -> "tuple[bool, str]":
        """
        Peer-review another agent's strategy proposal.
        Returns (approved, feedback_reason).
        Subclasses override for real LLM-backed review.
        """
        return True, "No review implemented — auto-approved."

    async def should_exit(
        self,
        position: dict,
        symbol_context: str,
    ) -> "tuple[bool, str]":
        """
        Decide whether to exit an open position this cycle.
        Returns (exit, reason).
        Subclasses override for real LLM-backed decision.
        Default: always HOLD — mechanical SL/TP in position_monitor handles exits.
        """
        return False, "HOLD — no exit logic implemented."

    async def get_performance_summary(self) -> dict:
        """Return this agent's performance metrics from the DB."""
        try:
            from sol.database import get_session  # type: ignore[import]
            from sol.models.position import Position  # type: ignore[import]
            from sqlalchemy import select

            async with get_session() as db:
                result = await db.execute(
                    select(Position).where(
                        Position.agent_id == self.agent_id,
                        Position.status != "OPEN",
                    )
                )
                closed = result.scalars().all()

            total_pnl = sum(float(p.realized_pnl or 0) for p in closed)
            wins = sum(1 for p in closed if float(p.realized_pnl or 0) > 0)
            win_rate = round(wins / len(closed) * 100, 1) if closed else 0.0
            open_result = await self._count_open_positions()
        except Exception:
            total_pnl = 0.0
            closed = []
            win_rate = 0.0
            open_result = 0

        vp = self.virtual_portfolio
        return {
            "agent_id": self.agent_id,
            "agent_name": self.name,
            "model_id": self.model_id,
            "virtual_capital_initial": vp.initial_capital,
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl / vp.initial_capital * 100, 2),
            "open_positions": open_result,
            "closed_trades": len(closed),
            "win_rate": win_rate,
        }

    async def _count_open_positions(self) -> int:
        try:
            from sol.database import get_session  # type: ignore[import]
            from sol.models.position import Position  # type: ignore[import]
            from sqlalchemy import select, func

            async with get_session() as db:
                result = await db.execute(
                    select(func.count(Position.id)).where(
                        Position.agent_id == self.agent_id,
                        Position.status == "OPEN",
                    )
                )
                return result.scalar() or 0
        except Exception:
            return 0

    def __repr__(self) -> str:
        return f"<Agent name={self.name} model={self.model_id}>"
