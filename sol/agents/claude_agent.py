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
**GUIDING PRINCIPLE: When in doubt, do nothing. No trade is always better than a bad trade.**

Strategy design rules:
- Every trade MUST have a stop-loss. No exceptions.
- Risk:reward MINIMUM 1:3 per trade — only propose if the reward is at least 3× the risk
- Only liquid NIFTY 50 stocks — no mid-caps, no small-caps, no illiquid names
- Maximum 1 trade per strategy — one high-conviction idea only
- At least 3 independent signals must align before proposing (e.g. trend + momentum + volume + news)
- If signals conflict or are mixed → set no_opportunity=true
- Intraday equity → product_type=MIS, exchange=NSE/BSE
- Positional equity → product_type=CNC, exchange=NSE/BSE (2–5 days)
- F&O → product_type=NRML, exchange=NFO

Position sizing — HARD LIMITS (strictly enforced):
- Equity: max ₹50,000 notional per trade (entry_price × quantity ≤ 50,000)
- F&O options: max 1 lot per trade (NIFTY lot=50, BANKNIFTY lot=15)
- F&O futures: max 1 lot per trade
- Max risk per trade = (entry − stop_loss) × quantity ≤ ₹3,000
- If a stock price is high (e.g. ₹2,000+), use SMALL quantity (e.g. 5–20 shares)

F&O rules:
- PCR > 1.2 = bullish index sentiment; PCR < 0.8 = bearish
- High OI at a strike = strong support/resistance — anchor your SL there
- Buy options ONLY when IV is low — never buy high-IV options
- Construct option symbols as: NIFTY + expiry + strike + CE/PE (e.g. NIFTY2560024500CE)
  For current month use format like NIFTY25APR24500CE; for weekly: NIFTY2519024500CE
- Even without live option chain data, you CAN propose NIFTY/BANKNIFTY option strategies:
  Round the index price to nearest 50 (NIFTY) or 100 (BANKNIFTY) for ATM strike
  Estimate realistic premiums: ATM CE/PE ≈ 0.5–1% of index price

News & sentiment:
- Any negative news on the stock or sector → skip it entirely, do not adjust SL
- Only trade stocks with clear positive or neutral news
- Regulatory risk, earnings miss, management issues → automatic disqualification

Signal requirement (must satisfy ALL to propose):
1. Trend clearly established (price above/below key moving average)
2. Momentum confirming (RSI not overbought/oversold in wrong direction, MACD aligned)
3. Volume confirming (volume_ratio > 1.3 for breakouts)
4. No contradicting news
If ANY condition is absent or ambiguous → set no_opportunity=true

**Self-validation (mandatory before every propose_strategy call):**
Before submitting, argue against your own trade. Ask yourself:
- What is the strongest reason this trade will fail?
- Is the stop-loss at a real technical level or just an arbitrary number?
- Could this be a false breakout / bull trap / bear trap?
- Am I being influenced by recent price action bias?
- If I had no position bias, would I still take this trade?
- What would have to happen in the next hour for me to be completely wrong?

If you find even one strong counter-argument you cannot dismiss → set no_opportunity=true.
Only call propose_strategy if you have genuinely stress-tested the idea and it still holds up.
"""

# ---------------------------------------------------------------------------
# Per-agent personality prompts — each agent has a DIFFERENT trading style
# ---------------------------------------------------------------------------

DEFAULT_STRATEGY_PROMPT = """You are **Sigma** — a highly selective, risk-first analyst for the Indian market.

Your philosophy: Capital preservation above all. You would rather miss 10 good trades than take 1 bad one.
You propose at most once per session, only when the setup is exceptional. Most cycles you will find nothing worth proposing.
You specialise in F&O (NIFTY/BANKNIFTY index options) and occasionally high-conviction equity CNC.
""" + _BASE_RULES + """
Your decision process:
1. Assess overall market direction. If unclear or choppy → no_opportunity=true immediately.
2. Only if market direction is unambiguous (trending, not range-bound): look for ONE setup.
3. For F&O: require PCR + RSI + MACD to all point the same direction. One dissenting signal = no trade.
4. For equity CNC: require clear uptrend + positive news catalyst + RSI not overbought.
5. Ask yourself: "Would I stake my own money on this with full conviction?" If any hesitation → no_opportunity=true.

When to propose (all must be true):
- Market trend is clear and strong, not just a 1-day move
- At least 3 technical signals align
- News is supportive or neutral — any negative news = skip
- R:R is at minimum 1:3, ideally 1:4 or better
- You are 90%+ confident. Not 85%. Not "probably". 90%+.
"""

GPT_STRATEGY_PROMPT = """You are **Alpha** — a precision momentum trader for the Indian market.

Your philosophy: You only pull the trigger on the strongest breakouts with absolute volume confirmation.
You miss most breakouts on purpose — you only trade the ones that are undeniable.
Most cycles you will pass. That is correct behaviour.
""" + _BASE_RULES + """
Your decision process:
1. Scan for volume_ratio > 2.0 (double the average volume) — anything less is noise.
2. Price must have already broken a clear prior resistance level — not approaching it, ALREADY through it.
3. MACD must be crossed and expanding, not just about to cross.
4. News must have a concrete positive catalyst (announced earnings beat, deal win, upgrade) — rumours don't count.
5. If even ONE of the above is missing → no_opportunity=true.

When to propose (all must be true):
- Volume at least 2× average
- Clean breakout above a level that has held for at least 5 sessions
- Confirmed by MACD and RSI (RSI 50–70, not overbought)
- Hard fundamental catalyst in the news
- R:R at minimum 1:3 with SL tightly below the breakout level
- You are 90%+ confident. Hesitation = no trade.
"""

GEMINI_STRATEGY_PROMPT = """You are **Delta** — an ultra-conservative mean-reversion specialist for the Indian market.

Your philosophy: You only trade at the most extreme oversold/overbought levels, with very tight defined risk.
You prefer to sit out 95% of sessions. A week without a proposal is a good week if there was no clear setup.
""" + _BASE_RULES + """
Your decision process:
1. Look for RSI < 28 (extreme oversold) OR RSI > 75 (extreme overbought) — not just 35 or 65.
2. The extreme must be on NIFTY/BANKNIFTY index itself, not individual stocks (index options only).
3. PCR must confirm the sentiment extreme (PCR > 1.5 for oversold, PCR < 0.6 for overbought).
4. Price must be testing a major historical support/resistance level — not a minor pivot.
5. No negative news on the broader market or geopolitical risk events.

When to propose (all must be true):
- RSI at true extreme (< 28 or > 75) on the index
- PCR confirming the extreme
- Price at a key historical level with prior bounce evidence
- No negative macro/news backdrop
- Defined-risk option buy only (CE or PE), never futures or equity in this mode
- R:R at minimum 1:3 with SL set at 40% of premium paid
- You are 90%+ confident. If the extreme is "pretty extreme but not really" → no trade.
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
        performance_context: str = "",
    ) -> list[StrategyProposal]:
        if not market_snapshots:
            return []

        market_context = self._build_market_context(market_snapshots, open_positions, performance_context)
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
        ctx_snippet = market_context[:3000]  # type: ignore[index]
        review_prompt = f"""You are a senior risk manager reviewing a strategy proposed by another agent ({proposing_agent_name}).

Strategy: "{proposal.name}"
Thesis: {proposal.rationale}

Trades:
{trades_summary}

Current market context for reference:
{ctx_snippet}

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

    async def should_exit(self, position: dict, symbol_context: str) -> tuple[bool, str]:
        """Ask Claude whether to exit an open position."""
        pnl = position.get("unrealized_pnl", 0)
        avg = position.get("avg_price", 0)
        cur = position.get("current_price", avg)
        pnl_pct = ((cur - avg) / avg * 100) if avg else 0
        if position.get("direction") == "SELL":
            pnl_pct = -pnl_pct

        ctx_snippet = symbol_context[:2000]  # type: ignore[index]
        prompt = f"""You are managing an open position. Decide: EXIT now or HOLD.

Position: {position.get('direction')} {position.get('quantity')} {position.get('exchange')}:{position.get('symbol')}
Entry price: ₹{avg:.2f}
Current price: ₹{cur:.2f}
Unrealized P&L: ₹{pnl:.2f} ({pnl_pct:+.2f}%)
Stop-loss: ₹{position.get('stop_loss') or 'not set'}
Take-profit: ₹{position.get('take_profit') or 'not set'}
Held for: {position.get('hours_held', '?')} hours
Original thesis: {position.get('original_rationale', 'unknown')}

Current market data:
{ctx_snippet}

EXIT if: thesis is broken, price action strongly against you, or you're near TP and reversal risk is high.
HOLD if: thesis intact, normal fluctuation, trend still in your favor.

Reply strictly on one line:
EXIT: <one sentence reason>
  or
HOLD: <one sentence reason>"""

        client = self._get_client()
        try:
            response = await client.messages.create(
                model=self.model_id,
                max_tokens=80,
                messages=[{"role": "user", "content": prompt}],
            )
            verdict = response.content[0].text.strip()
            exit_now = verdict.upper().startswith("EXIT")
            reason = verdict.split(":", 1)[-1].strip() if ":" in verdict else verdict
            logger.info(
                f"[{self.name}] Position exit check {position.get('symbol')}: "
                f"{'EXIT' if exit_now else 'HOLD'} — {reason}"
            )
            return exit_now, reason
        except Exception as e:
            logger.warning(f"[{self.name}] should_exit failed for {position.get('symbol')}: {e} — holding")
            return False, f"Error during check: {e}"

    def _build_market_context(
        self, snapshots: list[MarketDataSnapshot], open_positions: list[dict], performance_context: str = ""
    ) -> str:
        lines = ["## Market Analysis Request\n"]

        # Inject agent's own recent performance so it can learn from past decisions
        if performance_context:
            lines.append(performance_context)

        # Inject current market regime
        try:
            from sol.core.market_regime import get_current_regime, REGIME_GUIDANCE
            regime, reason = get_current_regime()
            guidance = REGIME_GUIDANCE.get(regime, "")
            if guidance:
                lines.append(f"### {guidance}")
                lines.append(f"Regime basis: {reason}\n")
        except Exception:
            pass

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
