"""
Sol — The main orchestrator bot.
Coordinates sub-agents, validates risk, and presents proposals to the user.
Uses Claude with tool-use for natural language chat and trade management.
"""

import json
import logging
from datetime import datetime, date
from decimal import Decimal
from typing import Any, Optional


class _SafeEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal and datetime objects from DB results."""
    def default(self, o: Any) -> Any:
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        return super().default(o)

import pytz

from sol.config import get_settings

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

_SOL_BASE_PROMPT = """You are Sol, an AI trading orchestrator for the Indian stock market (NSE/BSE).
You are connected to Zerodha Kite for live market data and order execution.

Your role:
- You coordinate multiple AI trading agents (each using a different LLM) that independently analyze the market
- Each agent proposes multi-trade strategies; you review them for risk and present them to Harsh for approval
- Once Harsh approves a strategy with a max-loss cap, trades execute automatically until the cap is hit
- You NEVER execute a trade without prior strategy approval from Harsh
- Capital preservation first, profit second

Your personality:
- Concise and precise — no filler words
- Risk-aware: always lead with risk before reward
- Transparent: cite which agent proposed what and why
- Protective: flag anything unusual immediately

You can reach Harsh directly on WhatsApp using the send_whatsapp tool.
Use it proactively when something needs his attention and he may not be watching the dashboard:
- A strategy needs urgent approval before the market window closes
- A position is at serious risk and he should be aware
- When Harsh explicitly asks you to notify him about something via WhatsApp

When presenting strategies or proposals:
1. Group by symbol to avoid redundant coverage
2. Show risk:reward prominently
3. Note agent consensus (multiple agents on same trade = stronger signal)
4. Highlight any contradictions between agents

You have tools to check portfolio status, risk, agent performance, and market state.
Always answer in the context of the current Indian market session.
"""


async def _build_system_prompt() -> str:
    """Build a dynamic system prompt that includes live agent and session state."""
    try:
        from sol.agents.agent_manager import get_agent_manager
        from sol.broker.kite_client import get_kite_client
        from sol.core.trading_mode import get_paper_mode
        from sol.database import get_session
        from sol.models.session import KiteSession
        from sqlalchemy import select
        import pytz
        from datetime import datetime

        IST = pytz.timezone("Asia/Kolkata")

        # Active agents — query DB directly (in-memory agents only loaded during analysis cycles)
        from sol.database import get_session as _get_session
        from sol.models.agent import Agent
        from sqlalchemy import select as _select

        async with _get_session() as _db:
            _result = await _db.execute(_select(Agent))
            _agent_records = _result.scalars().all()

        agent_lines = []
        for a in _agent_records:
            status = "active" if a.is_active else "inactive"
            agent_lines.append(
                f"  - {a.name} ({a.model_id}, {a.llm_provider}) — {status}"
            )
        agents_section = "\n".join(agent_lines) if agent_lines else "  - No agents configured"

        # Kite session
        client = get_kite_client()
        async with get_session() as db:
            result = await db.execute(
                select(KiteSession)
                .where(KiteSession.is_valid == True)
                .order_by(KiteSession.created_at.desc())
                .limit(1)
            )
            session = result.scalar_one_or_none()

        if session:
            expiry = session.token_expiry.strftime("%d %b %Y %I:%M %p IST") if session.token_expiry else "unknown"
            kite_section = (
                f"  Connected as: {session.user_name} (ID: {session.user_id})\n"
                f"  Token valid until: {expiry}\n"
                f"  Authenticated: {'yes' if client.is_authenticated() else 'token loaded but not set'}"
            )
        else:
            kite_section = "  Not connected — no valid Kite session"

        mode = "PAPER (simulated trades, no real orders)" if get_paper_mode() else "LIVE (real orders on Zerodha)"
        now = datetime.now(IST).strftime("%A, %d %b %Y %H:%M IST")

        context = f"""
--- Live System Context (as of {now}) ---
Trading mode: {mode}

Zerodha Kite connection:
{kite_section}

Active trading agents:
{agents_section}

Scheduled jobs (all times IST, Mon-Fri):
  - 8:45 AM — Kite session check (internal alert if not authenticated)
  - 9:00 AM — WhatsApp reminder to Harsh: login link + dashboard URL if not authenticated, else ready message
  - 9:15 AM onward — Agent analysis cycle every 15 min until 3:15 PM
  - Every minute 9:15–3:30 PM — Position monitor (SL/TP checks)
  - 3:20 PM — EOD square-off of intraday positions
  - 3:35 PM — EOD report generation
--- End Context ---
"""
        return _SOL_BASE_PROMPT + context

    except Exception:
        return _SOL_BASE_PROMPT


class SolOrchestrator:
    def __init__(self):
        self.settings = get_settings()
        self._client = None
        self._conversation_history: list[dict] = []

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=self.settings.ANTHROPIC_API_KEY)
        return self._client

    def _get_tools(self) -> list[dict]:
        return [
            {
                "name": "get_market_status",
                "description": "Check if the Indian stock market (NSE) is currently open, and get the current IST time.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "get_portfolio_status",
                "description": "Get full portfolio status: available capital, all open positions with unrealised P&L, today's realised P&L, and trading mode.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "get_pending_strategies",
                "description": "Get all strategy proposals waiting for Harsh's approval, including each strategy's trades, worst-case loss, and which agent proposed it.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "get_active_strategies",
                "description": "Get all currently active (approved and running) strategies, showing loss incurred vs cap approved.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "get_risk_report",
                "description": "Get current risk exposure: daily loss used vs limit, open position count, capital utilisation.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "get_agent_status",
                "description": "Get status and performance of all trading agents (name, model, provider, active/inactive, win rate, total proposals).",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "get_trade_history",
                "description": "Get recent executed trades.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "description": "Number of trades to return (default 10)"}
                    },
                },
            },
            {
                "name": "get_live_prices",
                "description": (
                    "Fetch live last-traded prices from Zerodha Kite for one or more symbols. "
                    "Supports equity (NSE), index, and F&O instruments. "
                    "For F&O use the full tradingsymbol e.g. 'NIFTY25MAR23100CE', 'BANKNIFTY25MAR53400PE', 'NIFTY26MARFUT'. "
                    "For equity/index use the NSE symbol e.g. 'RELIANCE', 'NIFTY 50'."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "symbols": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "List of symbols. Equity/index: 'RELIANCE', 'NIFTY 50'. "
                                "F&O: 'NIFTY25MAR23100CE', 'NIFTY26MARFUT'. "
                                "Or pre-qualified: 'NFO:NIFTY25MAR23100CE'."
                            )
                        }
                    },
                    "required": ["symbols"],
                },
            },
            {
                "name": "trigger_agent_analysis",
                "description": "Manually trigger all active trading agents to run a fresh market analysis cycle right now and propose strategies. Use when Harsh asks agents to analyse or find opportunities.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "send_whatsapp",
                "description": "Send Harsh a WhatsApp message. Use proactively when something urgent needs his attention (e.g. strategy approval window closing, position at serious risk) or when he explicitly asks to be notified via WhatsApp.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "The message to send to Harsh on WhatsApp."}
                    },
                    "required": ["message"],
                },
            },
        ]

    async def _execute_tool(self, tool_name: str, tool_input: dict) -> Any:
        """Execute Sol's internal tools."""
        from sol.utils.market_hours import is_market_open, market_status_str

        if tool_name == "get_market_status":
            return {
                "status": market_status_str(),
                "is_open": is_market_open(),
                "time_ist": datetime.now(IST).strftime("%H:%M:%S IST"),
            }

        elif tool_name == "get_portfolio_status":
            try:
                from sol.broker.order_manager import get_order_manager
                from sol.core.trading_mode import get_paper_mode
                from sol.database import get_session
                from sol.models.position import Position
                from sqlalchemy import select, func

                om = get_order_manager()
                capital = om.get_available_capital()

                IST_tz = pytz.timezone("Asia/Kolkata")
                today = datetime.now(IST_tz).date()

                async with get_session() as db:
                    # Open positions
                    pos_result = await db.execute(
                        select(Position).where(Position.status == "OPEN")
                    )
                    open_positions = pos_result.scalars().all()

                    # Today's realised P&L
                    pnl_result = await db.execute(
                        select(func.sum(Position.realized_pnl)).where(
                            func.date(Position.closed_at) == today
                        )
                    )
                    realised_pnl = float(pnl_result.scalar() or 0)

                positions_out = []
                for p in open_positions:
                    positions_out.append({
                        "symbol": p.symbol,
                        "exchange": p.exchange,
                        "direction": p.direction,
                        "quantity": p.quantity,
                        "avg_price": float(p.avg_price),
                        "current_price": float(p.current_price or p.avg_price),
                        "unrealised_pnl": round(float(p.unrealized_pnl or 0), 2),
                        "stop_loss": float(p.stop_loss) if p.stop_loss else None,
                    })

                return {
                    "mode": "PAPER" if get_paper_mode() else "LIVE",
                    "available_capital": capital,
                    "open_positions_count": len(open_positions),
                    "open_positions": positions_out,
                    "unrealised_pnl_total": round(sum(p["unrealised_pnl"] for p in positions_out), 2),
                    "realised_pnl_today": round(realised_pnl, 2),
                }
            except Exception as e:
                return {"error": str(e)}

        elif tool_name == "get_pending_strategies":
            try:
                from sol.database import get_session
                from sol.models.strategy import Strategy, StrategyTrade
                from sqlalchemy import select

                async with get_session() as db:
                    result = await db.execute(
                        select(Strategy)
                        .where(Strategy.status == "PENDING_APPROVAL")
                        .order_by(Strategy.proposed_at.desc())
                    )
                    strategies = result.scalars().all()

                    out = []
                    for s in strategies:
                        trades_result = await db.execute(
                            select(StrategyTrade).where(StrategyTrade.strategy_id == s.id)
                        )
                        trades = trades_result.scalars().all()
                        out.append({
                            "id": s.id,
                            "name": s.name,
                            "agent_id": s.agent_id,
                            "description": s.description,
                            "rationale": s.rationale,
                            "max_loss_possible": float(s.max_loss_possible or 0),
                            "duration_days": s.duration_days,
                            "created_at": s.created_at.isoformat(),
                            "trades": [
                                {
                                    "symbol": t.symbol,
                                    "direction": t.direction,
                                    "quantity": t.quantity,
                                    "stop_loss": float(t.stop_loss),
                                    "take_profit": float(t.take_profit) if t.take_profit else None,
                                    "rationale": t.rationale,
                                }
                                for t in trades
                            ],
                        })
                return {"count": len(out), "strategies": out}
            except Exception as e:
                return {"error": str(e)}

        elif tool_name == "get_active_strategies":
            try:
                from sol.database import get_session
                from sol.models.strategy import Strategy
                from sqlalchemy import select

                async with get_session() as db:
                    result = await db.execute(
                        select(Strategy)
                        .where(Strategy.status == "ACTIVE")
                        .order_by(Strategy.proposed_at.desc())
                    )
                    strategies = result.scalars().all()

                return {
                    "count": len(strategies),
                    "strategies": [
                        {
                            "id": s.id,
                            "name": s.name,
                            "agent_id": s.agent_id,
                            "max_loss_approved": float(s.max_loss_approved or 0),
                            "actual_loss": float(s.actual_loss or 0),
                            "loss_remaining": round(float(s.max_loss_approved or 0) - float(s.actual_loss or 0), 2),
                        }
                        for s in strategies
                    ],
                }
            except Exception as e:
                return {"error": str(e)}

        elif tool_name == "get_risk_report":
            try:
                from sol.services.risk_service import get_risk_service
                svc = get_risk_service()
                return await svc.get_exposure_report()
            except Exception as e:
                return {"error": str(e)}

        elif tool_name == "get_agent_status":
            try:
                from sol.database import get_session
                from sol.models.agent import Agent
                from sqlalchemy import select

                async with get_session() as db:
                    result = await db.execute(select(Agent))
                    agent_records = result.scalars().all()

                return {
                    "architecture_note": (
                        "Agents are NOT separate running processes. They are loaded on-demand "
                        "each analysis cycle (every 15 min during market hours, or when manually triggered). "
                        "Between cycles the in-memory list is empty — this is normal."
                    ),
                    "agents": [
                        {
                            "name": a.name,
                            "provider": a.llm_provider,
                            "model": a.model_id,
                            "active": a.is_active,
                            "virtual_capital": float(a.virtual_capital),
                            "status": "ready" if a.is_active else "disabled",
                        }
                        for a in agent_records
                    ],
                    "total": len(agent_records),
                    "active": sum(1 for a in agent_records if a.is_active),
                }
            except Exception as e:
                return {"error": str(e)}

        elif tool_name == "get_trade_history":
            try:
                from sol.database import get_session
                from sol.models.trade import TradeProposal
                from sqlalchemy import select

                limit = tool_input.get("limit", 10)
                async with get_session() as db:
                    result = await db.execute(
                        select(TradeProposal)
                        .where(TradeProposal.status == "EXECUTED")
                        .order_by(TradeProposal.executed_at.desc())
                        .limit(limit)
                    )
                    trades = result.scalars().all()

                return {
                    "count": len(trades),
                    "trades": [
                        {
                            "symbol": t.symbol,
                            "direction": t.direction,
                            "quantity": t.quantity,
                            "executed_at": t.executed_at.isoformat() if t.executed_at else None,
                            "agent_id": t.agent_id,
                        }
                        for t in trades
                    ],
                }
            except Exception as e:
                return {"error": str(e)}

        elif tool_name == "get_live_prices":
            try:
                from sol.broker.kite_client import get_kite_client
                symbols = tool_input.get("symbols", [])
                if not symbols:
                    return {"error": "No symbols provided"}
                client = get_kite_client()
                if not client.is_authenticated():
                    return {"error": "Kite not authenticated"}

                def _resolve_key(sym: str) -> str:
                    """Return exchange:tradingsymbol for any symbol format."""
                    if ":" in sym:
                        return sym  # already qualified e.g. "NFO:NIFTY25MAR23100CE"
                    s = sym.upper()
                    # F&O instruments end in CE, PE, or FUT
                    if s.endswith("CE") or s.endswith("PE") or s.endswith("FUT"):
                        return f"NFO:{s}"
                    return f"NSE:{s}"

                key_map = {s: _resolve_key(s) for s in symbols}
                quotes = client.get_ltp(list(key_map.values()))
                return {
                    s: quotes.get(key, {}).get("last_price", "N/A")
                    for s, key in key_map.items()
                }
            except Exception as e:
                return {"error": str(e)}

        elif tool_name == "trigger_agent_analysis":
            try:
                from sol.core.cycle_runner import run_analysis_cycle
                import asyncio
                asyncio.create_task(run_analysis_cycle())
                return {
                    "status": "Analysis cycle triggered",
                    "message": "All active agents are now analysing the market. New strategy proposals will appear in the Strategies tab within a minute.",
                }
            except Exception as e:
                return {"error": str(e)}

        elif tool_name == "send_whatsapp":
            try:
                from sol.notifications.whatsapp import send_whatsapp
                message = tool_input.get("message", "")
                success = await send_whatsapp(message)
                return {"sent": success}
            except Exception as e:
                return {"error": str(e)}

        return {"error": f"Unknown tool: {tool_name}"}

    async def chat(self, user_message: str, db_session=None) -> str:
        """
        Process a user message and return Sol's response.
        Handles multi-turn conversation with tool use.
        """
        import anthropic
        client = self._get_client()

        # Load recent history from DB if session provided
        if db_session:
            history = await self._load_history(db_session)
        else:
            history = list(self._conversation_history[-20:])  # Last 20 turns

        history.append({"role": "user", "content": user_message})

        messages = history.copy()
        max_iterations = 5  # Prevent infinite tool loops
        system_prompt = await _build_system_prompt()

        for _ in range(max_iterations):
            response = await client.messages.create(
                model=self.settings.SOL_MODEL,
                max_tokens=2048,
                system=system_prompt,
                tools=self._get_tools(),
                messages=messages,
            )

            if response.stop_reason == "end_turn":
                # Extract text response
                text = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        text += block.text
                self._conversation_history.append({"role": "user", "content": user_message})
                self._conversation_history.append({"role": "assistant", "content": text})
                if db_session:
                    await self._save_messages(db_session, user_message, text)
                return text

            elif response.stop_reason == "tool_use":
                # Process tool calls
                messages.append({"role": "assistant", "content": response.content})
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result = await self._execute_tool(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result, cls=_SafeEncoder),
                        })
                messages.append({"role": "user", "content": tool_results})

            else:
                break

        return "I encountered an issue processing your request. Please try again."

    async def generate_proposal_summary(self, proposals_by_agent: dict) -> str:
        """
        Generate a human-readable summary of agent proposals for the user.
        Called after each analysis cycle.
        """
        client = self._get_client()

        total_proposals = sum(len(v) for v in proposals_by_agent.values())
        if total_proposals == 0:
            return "No trade proposals from any agent in this cycle."

        summary_data = json.dumps(proposals_by_agent, indent=2, default=str)
        prompt = f"""
The trading agents have completed their analysis. Here are their proposals:

{summary_data}

Provide a concise briefing for Harsh:
1. How many proposals total, from which agents
2. Any consensus trades (multiple agents agree)
3. Key risks to highlight
4. Overall market read from the proposals

Keep it under 200 words. Be direct.
"""
        response = await client.messages.create(
            model=self.settings.SOL_MODEL,
            max_tokens=512,
            system=_SOL_BASE_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text if response.content else ""

    async def generate_strategy_summary(self, strategies: list[dict]) -> str:
        """
        Generate a human-readable briefing about new strategy proposals.
        Called after each analysis cycle.
        """
        client = self._get_client()
        if not strategies:
            return "No strategy proposals from any agent in this cycle."

        summary_data = json.dumps(strategies, indent=2, default=str)
        prompt = f"""
The trading agents have proposed the following strategies awaiting your approval:

{summary_data}

Provide a concise briefing for Harsh:
1. How many strategies, from which agents
2. Total trades and maximum possible loss across all strategies
3. Any key risks to highlight
4. What to approve vs skip

Keep it under 200 words. Be direct.
"""
        response = await client.messages.create(
            model=self.settings.SOL_MODEL,
            max_tokens=512,
            system=_SOL_BASE_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text if response.content else ""

    async def generate_eod_report(self, trades_today: list, positions_closed: list) -> str:
        """Generate end-of-day performance report."""
        client = self._get_client()

        data = {
            "date": datetime.now(IST).strftime("%d %B %Y"),
            "trades_executed": trades_today,
            "positions_closed": positions_closed,
        }

        response = await client.messages.create(
            model=self.settings.SOL_MODEL,
            max_tokens=1024,
            system=_SOL_BASE_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Generate today's trading summary:\n{json.dumps(data, indent=2, default=str)}"
            }],
        )
        return response.content[0].text if response.content else "No activity today."

    async def _load_history(self, db_session) -> list[dict]:
        from sol.models.session import ChatMessage
        from sqlalchemy import select
        result = await db_session.execute(
            select(ChatMessage).order_by(ChatMessage.created_at.desc()).limit(21)
        )
        messages = list(reversed(result.scalars().all()))
        # The API endpoint saves the current user message to DB before calling chat(),
        # so _load_history would include it. Strip it here — the orchestrator appends it.
        if messages and messages[-1].role == "user":
            messages = messages[:-1]
        return [{"role": m.role, "content": m.content} for m in messages[-20:]]

    async def _save_messages(self, db_session, user_msg: str, assistant_msg: str):
        from sol.models.session import ChatMessage
        # User message is saved immediately in the API endpoint; only save assistant response here
        db_session.add(ChatMessage(role="assistant", content=assistant_msg))
        await db_session.flush()


# Singleton
_orchestrator: Optional[SolOrchestrator] = None


def get_orchestrator() -> SolOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = SolOrchestrator()
    return _orchestrator
