"""GPT-4 based trading sub-agent."""

import json
import logging

from sol.agents.base_agent import BaseAgent, MarketDataSnapshot
from sol.agents.claude_agent import DEFAULT_STRATEGY_PROMPT
from sol.schemas.strategy import StrategyProposal, StrategyTradeIn

logger = logging.getLogger(__name__)

GPT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "propose_strategy",
            "description": "Submit a complete trading strategy with all planned trades.",
            "parameters": {
                "type": "object",
                "properties": {
                    "strategy": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                            "rationale": {"type": "string"},
                            "duration_days": {"type": "integer", "minimum": 1},
                            "trades": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "sequence": {"type": "integer"},
                                        "symbol": {"type": "string"},
                                        "exchange": {"type": "string", "enum": ["NSE", "BSE", "NFO"]},
                                        "direction": {"type": "string", "enum": ["BUY", "SELL"]},
                                        "order_type": {"type": "string", "enum": ["MARKET", "LIMIT"]},
                                        "product_type": {"type": "string", "enum": ["MIS", "CNC", "NRML"]},
                                        "option_type": {"type": "string", "enum": ["CE", "PE", "FUT"], "description": "Required for NFO trades"},
                                        "quantity": {"type": "integer"},
                                        "entry_price": {"type": "number"},
                                        "stop_loss": {"type": "number"},
                                        "take_profit": {"type": "number"},
                                        "rationale": {"type": "string"},
                                    },
                                    "required": ["sequence", "symbol", "exchange", "direction", "quantity", "stop_loss", "rationale"],
                                },
                            },
                        },
                        "required": ["name", "description", "rationale", "duration_days", "trades"],
                    },
                    "no_opportunity": {"type": "boolean"},
                    "reason": {"type": "string", "description": "Required when no_opportunity=true: why you are passing this cycle"},
                },
            },
        },
    }
]


class GPTAgent(BaseAgent):
    def __init__(
        self,
        agent_id: str,
        name: str,
        model_id: str = "gpt-4o",
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
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(api_key=self.api_key or None)
        return self._client

    async def analyze_and_propose(
        self,
        market_snapshots: list[MarketDataSnapshot],
        open_positions: list[dict],
        performance_context: str = "",
    ) -> list[StrategyProposal]:
        if not market_snapshots:
            return []

        from sol.agents.claude_agent import ClaudeAgent
        dummy = ClaudeAgent.__new__(ClaudeAgent)
        dummy.name = self.name
        market_context = dummy._build_market_context(market_snapshots, open_positions, performance_context)
        client = self._get_client()

        try:
            response = await client.chat.completions.create(
                model=self.model_id,
                messages=[
                    {"role": "system", "content": self.strategy_prompt},
                    {"role": "user", "content": market_context},
                ],
                tools=GPT_TOOLS,
                tool_choice={"type": "function", "function": {"name": "propose_strategy"}},
                max_tokens=4096,
            )
            msg = response.choices[0].message
            if msg.tool_calls:
                args = json.loads(msg.tool_calls[0].function.arguments)
                if args.get("no_opportunity"):
                    reason = args.get("reason") or args.get("rationale") or ""
                    logger.info(f"[{self.name}] NO_OPPORTUNITY — {reason or '(no reason given)'}")
                    logger.debug(f"[{self.name}] Full args: {args}")
                    return []
                strategy_data = args.get("strategy")
                if strategy_data:
                    parsed = self._parse_strategy(strategy_data)
                    return [parsed] if parsed else []
        except Exception as e:
            logger.error(f"[{self.name}] GPT analysis failed: {e}")

        return []

    async def review_strategy(
        self,
        proposal,
        market_context: str,
        proposing_agent_name: str,
    ) -> tuple[bool, str]:
        import json as _json
        trades_summary = _json.dumps(
            [
                {
                    "symbol": t.symbol,
                    "direction": t.direction,
                    "quantity": t.quantity,
                    "stop_loss": t.stop_loss,
                    "take_profit": t.take_profit,
                    "rationale": t.rationale,
                }
                for t in proposal.trades
            ],
            indent=2,
        )
        review_prompt = f"""You are a senior risk manager reviewing a strategy from {proposing_agent_name}.

Strategy: "{proposal.name}"
Thesis: {proposal.rationale}
Trades: {trades_summary}

Market context (excerpt):
{market_context[:2000]}

Reply with exactly one line:
APPROVED: <one sentence reason>
or
REJECTED: <one sentence reason>

APPROVE only if: stop-loss is set, R:R >= 1:1.5, thesis has concrete supporting data, sizing within limits.
REJECT if: vague thesis, missing SL, poor R:R, or generic bounce play with no edge."""

        client = self._get_client()
        try:
            response = await client.chat.completions.create(
                model=self.model_id,
                messages=[{"role": "user", "content": review_prompt}],
                max_tokens=100,
                temperature=0.2,
            )
            verdict = response.choices[0].message.content.strip()
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

    async def validate_entry(self, trade: dict, current_price: float, minutes_since_proposal: float) -> tuple[bool, str]:
        """Re-validate entry at execution time. See claude_agent for full logic."""
        proposed_entry = float(trade.get("entry_price") or current_price)
        price_drift_pct = abs(current_price - proposed_entry) / proposed_entry * 100 if proposed_entry else 0
        sl = trade.get("stop_loss")
        tp = trade.get("take_profit")
        direction = trade.get("direction", "BUY")
        if sl:
            sl_f = float(sl)
            if direction == "BUY" and current_price <= sl_f:
                return False, f"Price ₹{current_price:.2f} already breached SL ₹{sl_f:.2f}"
            if direction == "SELL" and current_price >= sl_f:
                return False, f"Price ₹{current_price:.2f} already breached SL ₹{sl_f:.2f}"
        if tp:
            tp_f = float(tp)
            if direction == "BUY" and current_price >= tp_f:
                return False, f"Price ₹{current_price:.2f} already hit TP ₹{tp_f:.2f}"
            if direction == "SELL" and current_price <= tp_f:
                return False, f"Price ₹{current_price:.2f} already hit TP ₹{tp_f:.2f}"
        if price_drift_pct > 1.5 or minutes_since_proposal > 10:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=self._api_key)
            prompt = f"A {direction} trade on {trade.get('symbol')} was proposed {minutes_since_proposal:.0f}m ago. Proposed entry ₹{proposed_entry:.2f}, now ₹{current_price:.2f} ({price_drift_pct:+.2f}% drift). SL ₹{sl}, TP ₹{tp}. Thesis: {trade.get('rationale','unknown')}. Is entry still valid? Reply: VALID: <reason> or INVALID: <reason>"
            try:
                resp = await client.chat.completions.create(model=self.model_id, max_tokens=80, messages=[{"role": "user", "content": prompt}])
                verdict = resp.choices[0].message.content.strip()
                valid = verdict.upper().startswith("VALID")
                reason = verdict.split(":", 1)[-1].strip() if ":" in verdict else verdict
                return valid, reason
            except Exception as e:
                return True, f"Validation failed ({e}), proceeding"
        return True, f"Price within tolerance ({price_drift_pct:.2f}% drift)"

    async def should_exit(self, position: dict, symbol_context: str) -> tuple[bool, str]:
        """Ask GPT whether to exit an open position."""
        pnl = position.get("unrealized_pnl", 0)
        avg = position.get("avg_price", 0)
        cur = position.get("current_price", avg)
        pnl_pct = ((cur - avg) / avg * 100) if avg else 0
        if position.get("direction") == "SELL":
            pnl_pct = -pnl_pct
        ctx_snippet = symbol_context[:2000]  # type: ignore[index]

        prompt = f"""Manage this open position. Should you EXIT or HOLD?

{position.get('direction')} {position.get('quantity')} {position.get('exchange')}:{position.get('symbol')}
Entry: ₹{avg:.2f} | Current: ₹{cur:.2f} | P&L: ₹{pnl:.2f} ({pnl_pct:+.2f}%)
SL: ₹{position.get('stop_loss') or 'not set'} | TP: ₹{position.get('take_profit') or 'not set'}
Held: {position.get('hours_held', '?')}h | Thesis: {position.get('original_rationale', 'unknown')}

Market data:
{ctx_snippet}

Reply on one line only:
EXIT: <reason>  or  HOLD: <reason>"""

        client = self._get_client()
        try:
            response = await client.chat.completions.create(
                model=self.model_id,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=80,
                temperature=0.1,
            )
            verdict = response.choices[0].message.content.strip()
            exit_now = verdict.upper().startswith("EXIT")
            reason = verdict.split(":", 1)[-1].strip() if ":" in verdict else verdict
            logger.info(f"[{self.name}] Exit check {position.get('symbol')}: {'EXIT' if exit_now else 'HOLD'} — {reason}")
            return exit_now, reason
        except Exception as e:
            logger.warning(f"[{self.name}] should_exit failed: {e} — holding")
            return False, f"Error: {e}"

    def _parse_strategy(self, data: dict) -> StrategyProposal | None:
        try:
            trades = [
                StrategyTradeIn(
                    sequence=int(t.get("sequence", 1)),
                    symbol=t["symbol"].upper().split(":")[-1],  # strip "NSE:" prefix if GPT includes it
                    exchange=t.get("exchange", "NSE").upper().split(":")[0],
                    direction=t["direction"],
                    order_type=t.get("order_type", "MARKET"),
                    product_type=t.get("product_type", "MIS"),
                    option_type=t.get("option_type"),
                    quantity=int(t["quantity"]),
                    entry_price=t.get("entry_price"),
                    stop_loss=t.get("stop_loss"),
                    take_profit=t.get("take_profit"),
                    rationale=t["rationale"],
                )
                for t in data.get("trades", [])
            ]
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
