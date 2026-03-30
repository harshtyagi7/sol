"""
Agent learning from past decisions.

1. get_performance_context(agent_id) — formats recent trade history into a
   prompt section so the agent can see what worked and what didn't.

2. recalibrate_agent_threshold(agent_id) — adjusts min_confidence in the
   agent's config_json based on win rate over the last 10 closed trades:
     - win rate < 40%  → raise threshold by 5% (max 98%)
     - win rate > 65%  → lower threshold by 2% (min 85%)
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

LOOKBACK = 10  # trades used for recalibration
MIN_THRESHOLD = 85
MAX_THRESHOLD = 98


async def get_performance_context(agent_id: str) -> str:
    """
    Return a formatted string describing this agent's recent closed trades.
    Empty string if fewer than 2 closed trades (not enough signal yet).
    """
    try:
        from sol.database import get_session
        from sol.models.position import Position
        from sqlalchemy import select

        async with get_session() as db:
            result = await db.execute(
                select(Position)
                .where(Position.agent_id == agent_id, Position.status != "OPEN")
                .order_by(Position.closed_at.desc())
                .limit(LOOKBACK)
            )
            trades = result.scalars().all()

        if len(trades) < 2:
            return ""

        wins = sum(1 for t in trades if float(t.realized_pnl or 0) > 0)
        losses = len(trades) - wins
        total_pnl = sum(float(t.realized_pnl or 0) for t in trades)
        win_rate = round(wins / len(trades) * 100, 1)

        lines = [
            f"\n### Your Recent Performance (last {len(trades)} closed trades)",
            f"Win rate: {win_rate}% ({wins}W / {losses}L) | Net P&L: ₹{total_pnl:.2f}",
            "",
            "Trade history (newest first):",
        ]
        for t in trades:
            pnl = float(t.realized_pnl or 0)
            outcome = "WIN" if pnl > 0 else "LOSS"
            close_reason = t.status  # SL_HIT / TP_HIT / SQUAREDOFF / etc.
            lines.append(
                f"  [{outcome}] {t.symbol} {t.direction} qty={t.quantity} "
                f"entry=₹{float(t.avg_price or 0):.2f} exit=₹{float(t.close_price or 0):.2f} "
                f"P&L=₹{pnl:.2f} [{close_reason}]"
            )

        # Derive a brief self-reflection hint
        if win_rate < 40:
            lines.append(
                "\nCaution: Your recent win rate is below 40%. "
                "Be even more selective — only propose when conviction is extremely high."
            )
        elif win_rate > 65:
            lines.append(
                "\nNote: Your recent win rate is above 65%. "
                "Your edge is working — stay disciplined and keep the same quality bar."
            )
        lines.append("")

        return "\n".join(lines)

    except Exception as e:
        logger.warning(f"[AgentFeedback] Could not build performance context for {agent_id}: {e}")
        return ""


async def recalibrate_agent_threshold(agent_id: str) -> Optional[int]:
    """
    Recalibrate an agent's min_confidence based on recent win rate.
    Returns the new threshold if changed, None otherwise.
    """
    try:
        from sol.database import get_session
        from sol.models.agent import Agent
        from sol.models.position import Position
        from sqlalchemy import select

        async with get_session() as db:
            result = await db.execute(
                select(Position)
                .where(Position.agent_id == agent_id, Position.status != "OPEN")
                .order_by(Position.closed_at.desc())
                .limit(LOOKBACK)
            )
            trades = result.scalars().all()

        if len(trades) < LOOKBACK:
            return None  # Not enough data yet

        wins = sum(1 for t in trades if float(t.realized_pnl or 0) > 0)
        win_rate = wins / len(trades) * 100

        async with get_session() as db:
            result = await db.execute(select(Agent).where(Agent.id == agent_id))
            agent_record = result.scalar_one_or_none()
            if not agent_record:
                return None

            config = dict(agent_record.config_json or {})
            current = int(config.get("min_confidence", 92))

            if win_rate < 40:
                new_threshold = min(current + 5, MAX_THRESHOLD)
            elif win_rate > 65:
                new_threshold = max(current - 2, MIN_THRESHOLD)
            else:
                return None  # Within acceptable range — no change

            if new_threshold == current:
                return None

            config["min_confidence"] = new_threshold
            agent_record.config_json = config
            await db.flush()

        direction = "raised" if new_threshold > current else "lowered"
        logger.info(
            f"[AgentFeedback] {agent_id} threshold {direction} "
            f"{current}% → {new_threshold}% (win rate {win_rate:.1f}% over last {LOOKBACK} trades)"
        )
        return new_threshold

    except Exception as e:
        logger.warning(f"[AgentFeedback] Recalibration failed for {agent_id}: {e}")
        return None
