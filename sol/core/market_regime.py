"""
Market regime detection — classifies the current market condition
so agents can adapt their strategy type accordingly.

Regimes:
  TRENDING_UP   — clear uptrend, momentum/breakout setups have edge
  TRENDING_DOWN — clear downtrend, short momentum has edge
  RANGING       — sideways/choppy, momentum fails, mean-reversion works
  VOLATILE      — abnormally high ATR, risk is elevated, prefer to sit out
  UNKNOWN       — insufficient data
"""

import logging

logger = logging.getLogger(__name__)

# Module-level state — updated each cycle, read by agents
_regime: str = "UNKNOWN"
_reason: str = "No data yet"


def get_current_regime() -> tuple[str, str]:
    return _regime, _reason


def set_regime(regime: str, reason: str) -> None:
    global _regime, _reason
    _regime = regime
    _reason = reason
    logger.info(f"[Regime] {regime} — {reason}")


def detect_regime(nifty_snapshot) -> tuple[str, str]:
    """
    Classify market regime from NIFTY 50 snapshot.
    Uses daily OHLCV + pre-computed indicators.
    Returns (regime, reason).
    """
    try:
        ohlcv = nifty_snapshot.ohlcv_daily or []
        indicators = nifty_snapshot.indicators or {}

        if len(ohlcv) < 20:
            return "UNKNOWN", "Insufficient OHLCV history"

        closes = [float(c["close"]) for c in ohlcv[-25:]]
        current = closes[-1]

        # --- ATR (14-day true range average) ---
        highs = [float(c["high"]) for c in ohlcv[-15:]]
        lows  = [float(c["low"])  for c in ohlcv[-15:]]
        true_ranges = []
        for i in range(1, len(ohlcv[-15:])):
            prev_close = float(ohlcv[-15 + i - 1]["close"])
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - prev_close),
                abs(lows[i] - prev_close),
            )
            true_ranges.append(tr)
        atr = sum(true_ranges) / len(true_ranges) if true_ranges else 0
        atr_pct = atr / current if current > 0 else 0

        # --- Trend: SMA-20 vs SMA-50 position ---
        sma20 = indicators.get("sma_20") or (sum(closes[-20:]) / 20)
        sma50 = indicators.get("sma_50") or (sum(closes[-min(50, len(closes)):]) / min(50, len(closes)))
        price_vs_sma20 = (current - sma20) / sma20
        sma20_vs_sma50 = (sma20 - sma50) / sma50 if sma50 else 0

        # --- Recent momentum: 5-day change ---
        momentum_5d = (closes[-1] - closes[-6]) / closes[-6] if len(closes) >= 6 else 0

        # --- Range tightness: how much has price moved in last 5 days vs ATR ---
        recent_high = max(float(c["high"]) for c in ohlcv[-5:])
        recent_low  = min(float(c["low"])  for c in ohlcv[-5:])
        recent_range_pct = (recent_high - recent_low) / current if current > 0 else 0

        # --- Classify ---

        # VOLATILE: ATR > 1.5% of index (NIFTY normally 0.7-1.1%)
        if atr_pct > 0.015:
            return (
                "VOLATILE",
                f"ATR is {atr_pct*100:.1f}% of index — abnormally high. Risk elevated.",
            )

        # TRENDING_UP: price above both SMAs, positive momentum, SMA-20 above SMA-50
        if (
            price_vs_sma20 > 0.005
            and sma20_vs_sma50 > 0.002
            and momentum_5d > 0.008
        ):
            return (
                "TRENDING_UP",
                f"Price {price_vs_sma20*100:.1f}% above SMA-20, SMA-20 above SMA-50, "
                f"5d momentum +{momentum_5d*100:.1f}%.",
            )

        # TRENDING_DOWN: price below both SMAs, negative momentum
        if (
            price_vs_sma20 < -0.005
            and sma20_vs_sma50 < -0.002
            and momentum_5d < -0.008
        ):
            return (
                "TRENDING_DOWN",
                f"Price {price_vs_sma20*100:.1f}% below SMA-20, SMA-20 below SMA-50, "
                f"5d momentum {momentum_5d*100:.1f}%.",
            )

        # RANGING: tight recent range, price hugging SMA-20, weak momentum
        if recent_range_pct < 0.025 and abs(price_vs_sma20) < 0.008:
            return (
                "RANGING",
                f"5-day range only {recent_range_pct*100:.1f}% — choppy/sideways market. "
                f"Momentum strategies have poor edge.",
            )

        # Default: mild trend or mixed signals
        direction = "up" if momentum_5d > 0 else "down"
        return (
            "RANGING",
            f"Mixed signals — no clear trend. 5d momentum {momentum_5d*100:.1f}% ({direction}), "
            f"price {price_vs_sma20*100:.1f}% vs SMA-20. Treat as ranging.",
        )

    except Exception as e:
        logger.warning(f"[Regime] Detection failed: {e}")
        return "UNKNOWN", f"Detection error: {e}"


# Guidance injected into agent prompts per regime
REGIME_GUIDANCE: dict[str, str] = {
    "TRENDING_UP": (
        "MARKET REGIME: TRENDING UP ✅\n"
        "Momentum and breakout setups on the long side have statistical edge right now.\n"
        "Avoid short setups and mean-reversion fades unless at a very extreme RSI level."
    ),
    "TRENDING_DOWN": (
        "MARKET REGIME: TRENDING DOWN ✅\n"
        "Momentum on the short side has edge. Long breakouts are fighting the trend.\n"
        "Only consider longs at severely oversold extremes (RSI < 28) with strong support."
    ),
    "RANGING": (
        "MARKET REGIME: RANGING / CHOPPY ⚠️\n"
        "The market is moving sideways. Breakout and momentum strategies will fail repeatedly.\n"
        "ONLY consider mean-reversion setups at clear extremes (RSI < 28 or RSI > 75).\n"
        "If you were going to propose a momentum/breakout trade — set no_opportunity=true instead."
    ),
    "VOLATILE": (
        "MARKET REGIME: HIGH VOLATILITY ⚠️\n"
        "ATR is elevated — use tighter stops than usual.\n"
        "PREFER defined-risk option buys (CE or PE). Equity MIS trades are ALLOWED but use stops of 1–1.5% max.\n"
        "Do NOT default to no_opportunity just because of volatility — look for equity setups with clear signals."
    ),
    "UNKNOWN": (
        "MARKET REGIME: UNKNOWN (insufficient data)\n"
        "Exercise extra caution. Default to no_opportunity=true if uncertain."
    ),
}
