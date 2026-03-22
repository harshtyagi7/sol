"""
Claude-based trading sub-agent.
Proposes full strategies (with all planned trades) via tool-use.
User approves the strategy once with a loss cap — trades execute autonomously.
"""

import json
import logging

from sol.agents.base_agent import BaseAgent, MarketDataSnapshot
from sol.schemas.strategy import StrategyProposal, StrategyTradeIn

logger = logging.getLogger(__name__)

STRATEGY_TOOL = {
    "name": "propose_strategy",
    "description": (
        "Submit a complete trading strategy. A strategy has a name, thesis, expected duration, "
        "and all planned trades in execution order. The user approves the strategy once with a "
        "max-loss cap — individual trades then execute automatically. Return null if no clear "
        "opportunity exists."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "strategy": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Short strategy name, e.g. 'RELIANCE Breakout Play'"},
                    "description": {"type": "string", "description": "Full strategy description and market thesis"},
                    "rationale": {"type": "string", "description": "Why this strategy makes sense right now — technical + macro"},
                    "duration_days": {"type": "integer", "minimum": 1, "maximum": 30, "description": "Expected trading days to complete"},
                    "trades": {
                        "type": "array",
                        "description": "All planned trades in execution order",
                        "items": {
                            "type": "object",
                            "properties": {
                                "sequence": {"type": "integer", "minimum": 1, "description": "Execution order"},
                                "symbol": {"type": "string", "description": "NSE/BSE ticker"},
                                "exchange": {"type": "string", "enum": ["NSE", "BSE", "NFO"], "description": "NSE/BSE for equity, NFO for F&O"},
                                "direction": {"type": "string", "enum": ["BUY", "SELL"]},
                                "order_type": {"type": "string", "enum": ["MARKET", "LIMIT"]},
                                "product_type": {"type": "string", "enum": ["MIS", "CNC", "NRML"], "description": "MIS=intraday equity, CNC=delivery, NRML=F&O overnight"},
                                "option_type": {"type": "string", "enum": ["CE", "PE", "FUT"], "description": "Required for NFO trades: CE=call, PE=put, FUT=futures"},
                                "quantity": {"type": "integer", "minimum": 1, "description": "Number of shares for equity, number of lots for F&O"},
                                "entry_price": {"type": "number", "description": "Entry price for LIMIT orders"},
                                "stop_loss": {"type": "number", "description": "Stop-loss — REQUIRED"},
                                "take_profit": {"type": "number", "description": "Profit target"},
                                "rationale": {"type": "string", "description": "Why this specific trade fits the strategy"},
                            },
                            "required": ["sequence", "symbol", "exchange", "direction", "quantity", "stop_loss", "rationale"],
                        },
                    },
                },
                "required": ["name", "description", "rationale", "duration_days", "trades"],
            },
            "no_opportunity": {
                "type": "boolean",
                "description": "Set to true if no clear strategy exists right now",
            },
        },
        "required": [],
    },
}

_BASE_RULES = """
Strategy design rules:
- Every trade MUST have a stop-loss. No exceptions.
- Risk:reward minimum 1:1.5 per trade (target at least 1:2)
- Only liquid large-cap / mid-cap stocks (NIFTY 50 / NIFTY 100 constituents)
- Maximum 3 trades per strategy — quality over quantity
- Intraday equity → product_type=MIS, exchange=NSE/BSE
- Positional equity → product_type=CNC, exchange=NSE/BSE (2–5 days)
- F&O → product_type=NRML, exchange=NFO

Position sizing — HARD LIMITS (strictly enforced):
- Equity: max ₹75,000 notional per trade (entry_price × quantity ≤ 75,000)
- F&O options: max 2 lots per trade (NIFTY lot=50, BANKNIFTY lot=15)
- F&O futures: max 1 lot per trade
- Max risk per trade = (entry − stop_loss) × quantity ≤ ₹4,000
- If a stock price is high (e.g. ₹2,000+), use SMALL quantity (e.g. 10–30 shares) to stay within notional cap

F&O rules:
- PCR > 1.2 = bullish index sentiment; PCR < 0.8 = bearish
- High OI at a strike = strong support/resistance — anchor your SL there
- Buy options when IV is low; avoid when IV is extremely elevated
- Construct option symbols as: NIFTY + expiry + strike + CE/PE (e.g. NIFTY2560024500CE)
  For current month use format like NIFTY25APR24500CE; for weekly: NIFTY2519024500CE
- Even without live option chain data, you CAN propose NIFTY/BANKNIFTY option strategies:
  Round the index price to nearest 50 (NIFTY) or 100 (BANKNIFTY) for ATM strike
  Estimate realistic premiums: ATM CE/PE ≈ 0.5–1% of index price

News & sentiment:
- Read all provided headlines before deciding
- Positive news → supports BUY, can tighten SL
- Negative news → avoid long or widen SL significantly
- Always mention news impact in rationale when relevant headlines exist
"""

# ---------------------------------------------------------------------------
# Per-agent personality prompts — each agent has a DIFFERENT trading style
# ---------------------------------------------------------------------------

DEFAULT_STRATEGY_PROMPT = """You are **Sigma** — a disciplined multi-factor analyst specializing in the Indian market.

Your style: High-conviction positional trades (CNC) backed by technical + news confluence.
You prefer 1–2 carefully chosen trades with strong R:R over a basket of mediocre ones.
You are the ONLY agent who actively looks for F&O (NIFTY/BANKNIFTY index options) opportunities.
""" + _BASE_RULES + """
Your strategy focus TODAY:
1. First, assess the NIFTY 50 / NIFTY BANK overall market direction using indicators + PCR
2. If market direction is clear → propose a NIFTY CE or PE option play (1–2 lots)
3. Then find 1 quality equity CNC trade confirmed by both technicals and news
4. Do NOT propose oversold-bounce setups unless RSI < 30 AND the stock has positive news

Examples:
- "NIFTY weekly CE play" — PCR 0.75 (bearish) reversed, RSI bouncing from 38, buy ATM CE 1 lot, SL=50% premium
- "TCS positional long" — CNC 20 shares, SL below last week's low, TP at prior resistance, confirmed by earnings beat news
"""

GPT_STRATEGY_PROMPT = """You are **Alpha** — an aggressive momentum breakout trader in the Indian market.

Your style: Intraday MIS trades on stocks breaking out with volume. You hunt breakouts, not bounces.
You NEVER trade oversold stocks hoping for a bounce — you trade stocks that are already moving UP with volume.
""" + _BASE_RULES + """
Your strategy focus TODAY:
1. Find stocks where today's (or recent) volume_ratio > 1.5 (above-average volume)
2. Look for MACD crossovers or price breaking above SMA-20 with momentum
3. Check news — positive catalyst (earnings, deal win, upgrade) + breakout = ideal entry
4. Propose 2–3 MIS intraday trades on the strongest momentum setups
5. Use NIFTY/BANKNIFTY FUTURES (FUT) only if the broad index shows strong directional breakout

Examples:
- "INFY volume breakout" — MIS 30 shares, SL below breakout candle, TP at next resistance
- "NIFTY futures momentum" — NFO FUT 1 lot, breakout above 24,500 resistance, SL at 24,350
- "RELIANCE news-driven gap up" — MIS 15 shares, buying the gap continuation
"""

GEMINI_STRATEGY_PROMPT = """You are **Delta** — a contrarian mean-reversion options specialist in the Indian market.

Your style: You trade extremes. You BUY when others panic and SELL when others are euphoric.
You prefer defined-risk option trades (CE/PE buys) over naked equity positions.
You NEVER chase momentum — you fade it when RSI hits extremes.
""" + _BASE_RULES + """
Your strategy focus TODAY:
1. Find NIFTY or BANKNIFTY at an extreme (RSI < 35 = buy CE, RSI > 70 = buy PE)
2. Find 1–2 individual stocks also at RSI extremes with high OI support nearby
3. For equity, use CNC with entries near SMA-50 support/resistance levels
4. Avoid stocks with negative news even if they look technically oversold
5. Maximum 1 NIFTY/BANKNIFTY option + 1 equity trade per strategy

Examples:
- "NIFTY oversold bounce play" — RSI 32, buy ATM CE 1 lot, SL = 40% of premium, 1-day expiry
- "SBIN mean reversion CNC" — RSI 28, near SMA-50 support, 50 shares CNC, SL below support
- "BANKNIFTY PCR reversal" — PCR > 1.5 (excess put buying), buy ATM CE when selling stops
"""


class ClaudeAgent(BaseAgent):
    def __init__(
        self,
        agent_id: str,
        name: str,
        model_id: str = "claude-sonnet-4-6",
        strategy_prompt: str = "",
        virtual_capital: float = 1_000_000.0,
        api_key: str = "",
    ):
        super().__init__(agent_id, name, model_id, virtual_capital)
        self.strategy_prompt = strategy_prompt or DEFAULT_STRATEGY_PROMPT
        self.api_key = api_key
        self._client = None

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=self.api_key or None)
        return self._client

    async def analyze_and_propose(
        self,
        market_snapshots: list[MarketDataSnapshot],
        open_positions: list[dict],
    ) -> list[StrategyProposal]:
        if not market_snapshots:
            return []

        market_context = self._build_market_context(market_snapshots, open_positions)
        client = self._get_client()

        try:
            response = await client.messages.create(
                model=self.model_id,
                max_tokens=4096,
                system=self.strategy_prompt,
                tools=[STRATEGY_TOOL],
                tool_choice={"type": "any"},
                messages=[{"role": "user", "content": market_context}],
            )

            for block in response.content:
                if block.type == "tool_use" and block.name == "propose_strategy":
                    if block.input.get("no_opportunity"):
                        return []
                    strategy_data = block.input.get("strategy")
                    if strategy_data:
                        parsed = self._parse_strategy(strategy_data)
                        return [parsed] if parsed else []

        except Exception as e:
            logger.error(f"[{self.name}] Analysis failed: {e}")

        return []

    async def review_strategy(
        self,
        proposal,
        market_context: str,
        proposing_agent_name: str,
    ) -> tuple[bool, str]:
        """
        Critically review a peer agent's strategy proposal.
        Returns (approved, reason). Only approve if genuinely high-probability.
        """
        import json as _json
        trades_summary = _json.dumps(
            [
                {
                    "symbol": t.symbol,
                    "exchange": t.exchange,
                    "direction": t.direction,
                    "quantity": t.quantity,
                    "entry_price": t.entry_price,
                    "stop_loss": t.stop_loss,
                    "take_profit": t.take_profit,
                    "rationale": t.rationale,
                }
                for t in proposal.trades
            ],
            indent=2,
        )
        review_prompt = f"""You are a senior risk manager reviewing a strategy proposed by another agent ({proposing_agent_name}).

Strategy: "{proposal.name}"
Thesis: {proposal.rationale}

Trades:
{trades_summary}

Current market context for reference:
{market_context[:3000]}

Evaluate this strategy critically. Answer APPROVED or REJECTED, then one sentence of reasoning.

Criteria for APPROVAL (ALL must hold):
- Stop-loss is realistic and not too wide
- Risk:reward ratio is at least 1:1.5
- The thesis is supported by at least one concrete data point from the market context
- Position sizing is within limits (equity ≤ ₹75k notional, F&O ≤ 2 lots)

Criteria for REJECTION (ANY of these → REJECT):
- Vague thesis with no supporting data ("oversold" alone is not enough)
- Stop-loss missing or unrealistically tight/wide
- Risk:reward below 1:1.5
- Duplicate of what any other agent would propose (generic bounce play)
- Position too large

Reply format (strictly one line):
APPROVED: <one sentence reason>
  or
REJECTED: <one sentence reason>"""

        client = self._get_client()
        try:
            response = await client.messages.create(
                model=self.model_id,
                max_tokens=128,
                messages=[{"role": "user", "content": review_prompt}],
            )
            verdict = response.content[0].text.strip()
            approved = verdict.upper().startswith("APPROVED")
            reason = verdict.split(":", 1)[-1].strip() if ":" in verdict else verdict
            logger.info(
                f"[{self.name}] Peer review of '{proposal.name}' by {proposing_agent_name}: "
                f"{'✅' if approved else '❌'} {reason}"
            )
            return approved, reason
        except Exception as e:
            logger.warning(f"[{self.name}] Review failed for '{proposal.name}': {e} — auto-approving")
            return True, f"Review error: {e}"

    def _build_market_context(
        self, snapshots: list[MarketDataSnapshot], open_positions: list[dict]
    ) -> str:
        lines = ["## Market Analysis Request\n"]

        if open_positions:
            lines.append("### Active Positions (already in market)")
            for p in open_positions:
                lines.append(
                    f"- {p.get('symbol')} {p.get('direction')} {p.get('quantity')} "
                    f"@ ₹{p.get('avg_price', 0):.2f} | SL: {p.get('stop_loss')} | "
                    f"Unrealized P&L: ₹{p.get('unrealized_pnl', 0):.2f}"
                )
            lines.append("")

        lines.append("### Market Data")
        for snap in snapshots:
            lines.append(f"\n#### {snap.exchange}:{snap.symbol} — LTP: ₹{snap.current_price:.2f}")
            if snap.ohlcv_daily:
                recent = snap.ohlcv_daily[-5:]
                lines.append("Daily OHLCV (last 5 days):")
                for candle in recent:
                    lines.append(
                        f"  {candle.get('date', '')}: O={candle.get('open', 0):.2f} "
                        f"H={candle.get('high', 0):.2f} L={candle.get('low', 0):.2f} "
                        f"C={candle.get('close', 0):.2f} V={candle.get('volume', 0)}"
                    )
            if snap.indicators:
                lines.append(f"Indicators: {json.dumps(snap.indicators)}")
            if snap.futures_price:
                lines.append(f"Futures (nearest): ₹{snap.futures_price:.2f} "
                             f"({'premium' if snap.futures_price > snap.current_price else 'discount'} "
                             f"of {abs(snap.futures_price - snap.current_price):.2f})")
            if snap.pcr is not None:
                sentiment = "bullish" if snap.pcr > 1.2 else ("bearish" if snap.pcr < 0.8 else "neutral")
                lines.append(f"PCR (OI-based): {snap.pcr} → {sentiment} sentiment")
            if snap.option_chain:
                # Show ATM ± 3 strikes to keep context concise
                mid = len(snap.option_chain) // 2
                visible = snap.option_chain[max(0, mid - 3): mid + 4]
                lines.append("Option chain (ATM ±3 strikes, CE | Strike | PE):")
                for s in visible:
                    ce = s.get("ce", {})
                    pe = s.get("pe", {})
                    ce_str = f"LTP={ce.get('ltp', 0)} OI={ce.get('oi', 0):,} IV={ce.get('iv', 0)}%"
                    pe_str = f"LTP={pe.get('ltp', 0)} OI={pe.get('oi', 0):,} IV={pe.get('iv', 0)}%"
                    lines.append(f"  CE [{ce_str}] | {s['strike']} | [{pe_str}] PE")
            if snap.news_headlines:
                lines.append("Recent news:")
                for headline in snap.news_headlines[:5]:
                    lines.append(f"  - {headline}")

        lines.append(
            "\nPropose a strategy using the propose_strategy tool. "
            "If no clear opportunity, set no_opportunity=true."
        )
        return "\n".join(lines)

    def _parse_strategy(self, data: dict) -> StrategyProposal | None:
        try:
            trades = []
            for t in data.get("trades", []):
                trades.append(StrategyTradeIn(
                    sequence=int(t.get("sequence", 1)),
                    symbol=t["symbol"].upper(),
                    exchange=t.get("exchange", "NSE"),
                    direction=t["direction"],
                    order_type=t.get("order_type", "MARKET"),
                    product_type=t.get("product_type", "MIS"),
                    quantity=int(t["quantity"]),
                    entry_price=t.get("entry_price"),
                    stop_loss=t.get("stop_loss"),
                    take_profit=t.get("take_profit"),
                    rationale=t["rationale"],
                ))
            if not trades:
                return None
            return StrategyProposal(
                name=data["name"],
                description=data["description"],
                rationale=data["rationale"],
                duration_days=int(data.get("duration_days", 1)),
                trades=trades,
            )
        except Exception as e:
            logger.warning(f"[{self.name}] Invalid strategy skipped: {e}")
            return None
