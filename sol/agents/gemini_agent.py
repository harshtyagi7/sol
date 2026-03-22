"""Gemini-based trading sub-agent."""

import json
import logging

from sol.agents.base_agent import BaseAgent, MarketDataSnapshot
from sol.agents.claude_agent import DEFAULT_STRATEGY_PROMPT
from sol.schemas.strategy import StrategyProposal, StrategyTradeIn

logger = logging.getLogger(__name__)


class GeminiAgent(BaseAgent):
    def __init__(
        self,
        agent_id: str,
        name: str,
        model_id: str = "gemini-1.5-pro",
        strategy_prompt: str = "",
        virtual_capital: float = 1_000_000.0,
        api_key: str = "",
    ):
        super().__init__(agent_id, name, model_id, virtual_capital)
        self.strategy_prompt = strategy_prompt or DEFAULT_STRATEGY_PROMPT
        self.api_key = api_key
        self._model = None

    def _get_model(self):
        if self._model is None:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key or None)
            self._model = genai.GenerativeModel(
                model_name=self.model_id,
                system_instruction=self.strategy_prompt,
            )
        return self._model

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
        model = self._get_model()

        prompt = (
            market_context
            + "\n\nRespond ONLY with a JSON object. "
            "If there is a clear strategy, use this format:\n"
            '{"strategy": {"name": "...", "description": "...", "rationale": "...", '
            '"duration_days": 1, "trades": [{"sequence": 1, "symbol": "...", '
            '"exchange": "NSE|BSE|NFO", "direction": "BUY|SELL", "order_type": "MARKET|LIMIT", '
            '"product_type": "MIS|CNC|NRML", "option_type": "CE|PE|FUT or omit for equity", '
            '"quantity": 10, "stop_loss": 100.0, '
            '"take_profit": 110.0, "rationale": "..."}]}}\n'
            'For NFO trades: exchange=NFO, product_type=NRML, include option_type (CE/PE/FUT), '
            'symbol=exact tradingsymbol (e.g. NIFTY2560024500CE), quantity=number of lots.\n'
            'If no clear opportunity, respond: {"no_opportunity": true}'
        )

        try:
            response = await model.generate_content_async(prompt)
            text = response.text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            data = json.loads(text)
            if data.get("no_opportunity"):
                return []
            strategy_data = data.get("strategy")
            if strategy_data:
                parsed = self._parse_strategy(strategy_data)
                return [parsed] if parsed else []
        except Exception as e:
            err_str = str(e)
            if "quota" in err_str.lower() or "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                logger.warning(
                    f"[{self.name}] Gemini free-tier quota exhausted — "
                    "enable billing at console.cloud.google.com or wait for daily reset."
                )
            else:
                logger.error(f"[{self.name}] Gemini analysis failed: {e}")

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
        prompt = f"""Review this strategy from {proposing_agent_name}.

Strategy: "{proposal.name}"
Thesis: {proposal.rationale}
Trades: {trades_summary}

Market context (excerpt):
{market_context[:2000]}

Reply with exactly one line:
APPROVED: <one sentence reason>
or
REJECTED: <one sentence reason>

APPROVE only if: stop-loss set, R:R >= 1:1.5, thesis has concrete data support, sizing within limits.
REJECT if: vague thesis, missing SL, poor R:R, or generic idea with no edge."""

        model = self._get_model()
        try:
            response = await model.generate_content_async(prompt)
            verdict = response.text.strip()
            if verdict.startswith("```"):
                verdict = verdict.split("```")[1].strip()
            approved = verdict.upper().startswith("APPROVED")
            reason = verdict.split(":", 1)[-1].strip() if ":" in verdict else verdict
            logger.info(
                f"[{self.name}] Peer review of '{proposal.name}' by {proposing_agent_name}: "
                f"{'✅' if approved else '❌'} {reason}"
            )
            return approved, reason
        except Exception as e:
            err_str = str(e)
            if "quota" in err_str.lower() or "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                logger.warning(f"[{self.name}] Gemini quota hit during review — auto-approving")
            else:
                logger.warning(f"[{self.name}] Review failed for '{proposal.name}': {e} — auto-approving")
            return True, f"Review error: {e}"

    def _parse_strategy(self, data: dict) -> StrategyProposal | None:
        try:
            trades = [
                StrategyTradeIn(
                    sequence=int(t.get("sequence", 1)),
                    symbol=t["symbol"].upper(),
                    exchange=t.get("exchange", "NSE"),
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
