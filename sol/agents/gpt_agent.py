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
    ) -> list[StrategyProposal]:
        if not market_snapshots:
            return []

        from sol.agents.claude_agent import ClaudeAgent
        dummy = ClaudeAgent.__new__(ClaudeAgent)
        dummy.name = self.name
        market_context = dummy._build_market_context(market_snapshots, open_positions)
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
