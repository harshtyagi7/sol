"""
Backtest service — simulates strategy trades against historical OHLCV data.

For each trade: walks through the last 90 days of daily candles and counts
how many times the setup would have hit TP, SL, or expired at close.
Uses daily OHLCV only (no intraday paths), so results are approximate.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _simulate_trade(
    candles: list[dict],
    entry_price: float,
    stop_loss: Optional[float],
    take_profit: Optional[float],
    direction: str,
    duration_days: int,
) -> dict:
    """
    Walk through candles and find all days where the entry was reachable.
    For each such day, simulate forward up to duration_days.
    Returns aggregate stats.
    """
    wins, losses, expired = [], [], []

    for i, candle in enumerate(candles):
        # Entry is achievable only if price passed THROUGH the entry level on this candle
        # (candle range must include entry_price, not just be below/above it)
        if not (candle["low"] <= entry_price <= candle["high"]):
            continue

        # Simulate forward from next candle
        forward = candles[i + 1 : i + 1 + duration_days]
        if not forward:
            continue

        outcome = "EXPIRED"
        exit_price = forward[-1]["close"]

        for future in forward:
            if direction == "BUY":
                # Check TP before SL within same candle (optimistic: assume TP hits first if both)
                if take_profit and future["high"] >= take_profit:
                    outcome = "WIN"
                    exit_price = take_profit
                    break
                if stop_loss and future["low"] <= stop_loss:
                    outcome = "LOSS"
                    exit_price = stop_loss
                    break
            else:  # SELL
                if take_profit and future["low"] <= take_profit:
                    outcome = "WIN"
                    exit_price = take_profit
                    break
                if stop_loss and future["high"] >= stop_loss:
                    outcome = "LOSS"
                    exit_price = stop_loss
                    break

        if outcome == "EXPIRED":
            exit_price = forward[-1]["close"]

        result = {
            "entry_date": candle["date"],
            "outcome": outcome,
            "exit_price": round(exit_price, 2),
        }
        if outcome == "WIN":
            wins.append(result)
        elif outcome == "LOSS":
            losses.append(result)
        else:
            expired.append(result)

    total = len(wins) + len(losses) + len(expired)
    if total == 0:
        return {
            "total_scenarios": 0,
            "wins": 0, "losses": 0, "expired": 0,
            "win_rate_pct": None,
            "note": "Entry price never reached in historical data",
        }

    win_rate = round(len(wins) / total * 100, 1)
    return {
        "total_scenarios": total,
        "wins": len(wins),
        "losses": len(losses),
        "expired": len(expired),
        "win_rate_pct": win_rate,
        "recent_outcomes": [r["outcome"] for r in (wins + losses + expired)[:10]],
    }


async def backtest_strategy(strategy_id: str) -> dict:
    """
    Fetch the strategy's trades from DB, pull historical OHLCV for each symbol,
    run the simulation, and return a per-trade + overall summary.
    """
    from sol.database import get_session
    from sol.models.strategy import Strategy, StrategyTrade
    from sol.services.market_data_service import get_market_snapshots
    from sqlalchemy import select

    async with get_session() as db:
        s_result = await db.execute(select(Strategy).where(Strategy.id == strategy_id))
        strategy = s_result.scalar_one_or_none()
        if not strategy:
            return {"error": "Strategy not found"}

        t_result = await db.execute(
            select(StrategyTrade)
            .where(StrategyTrade.strategy_id == strategy_id)
            .order_by(StrategyTrade.sequence)
        )
        trades = t_result.scalars().all()

    if not trades:
        return {"error": "No trades in strategy"}

    # Fetch historical data for all unique symbols
    symbols = list({(t.symbol, t.exchange) for t in trades})
    try:
        snapshots = await get_market_snapshots(watchlist=symbols)
    except Exception as e:
        return {"error": f"Could not fetch market data: {e}"}

    candles_by_symbol = {s.symbol: s.ohlcv_daily for s in snapshots}

    trade_results = []
    all_wins = all_losses = all_expired = 0

    for trade in trades:
        candles = candles_by_symbol.get(trade.symbol, [])
        if not candles:
            trade_results.append({
                "symbol": trade.symbol,
                "direction": trade.direction,
                "entry_price": trade.entry_price,
                "stop_loss": float(trade.stop_loss) if trade.stop_loss else None,
                "take_profit": float(trade.take_profit) if trade.take_profit else None,
                "quantity": trade.quantity,
                "error": "No historical data available",
            })
            continue

        sim = _simulate_trade(
            candles=candles,
            entry_price=float(trade.entry_price or candles[-1]["close"]),
            stop_loss=float(trade.stop_loss) if trade.stop_loss else None,
            take_profit=float(trade.take_profit) if trade.take_profit else None,
            direction=trade.direction,
            duration_days=strategy.duration_days,
        )

        # Expected P&L per scenario
        entry = float(trade.entry_price or candles[-1]["close"])
        sl = float(trade.stop_loss) if trade.stop_loss else None
        tp = float(trade.take_profit) if trade.take_profit else None
        qty = trade.quantity

        if tp and sl:
            win_pnl = round(abs(tp - entry) * qty, 0)
            loss_pnl = round(abs(entry - sl) * qty, 0)
            rr = round(abs(tp - entry) / abs(entry - sl), 2) if abs(entry - sl) > 0 else None
        else:
            win_pnl = loss_pnl = rr = None

        trade_results.append({
            "symbol": trade.symbol,
            "direction": trade.direction,
            "entry_price": entry,
            "stop_loss": sl,
            "take_profit": tp,
            "quantity": qty,
            "risk_reward": rr,
            "potential_win_inr": win_pnl,
            "potential_loss_inr": loss_pnl,
            **sim,
        })

        all_wins += sim.get("wins", 0)
        all_losses += sim.get("losses", 0)
        all_expired += sim.get("expired", 0)

    all_total = all_wins + all_losses + all_expired
    overall_win_rate = round(all_wins / all_total * 100, 1) if all_total > 0 else None

    return {
        "strategy_id": strategy_id,
        "strategy_name": strategy.name,
        "duration_days": strategy.duration_days,
        "candles_used": len(candles_by_symbol.get(trades[0].symbol, [])),
        "data_note": "Daily OHLCV only. Results are indicative — no slippage, gaps, or liquidity modelled.",
        "overall": {
            "total_scenarios": all_total,
            "wins": all_wins,
            "losses": all_losses,
            "expired": all_expired,
            "win_rate_pct": overall_win_rate,
        },
        "trades": trade_results,
    }
