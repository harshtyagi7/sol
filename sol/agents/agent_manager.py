"""
Agent Manager — loads, runs, and manages all sub-agents.
Agents are stored in the DB and hot-loaded each cycle.
"""

import asyncio
import logging
from typing import Optional

from sol.agents.base_agent import BaseAgent, MarketDataSnapshot
from sol.config import get_settings
from sol.schemas.trade import TradeProposalCreate

logger = logging.getLogger(__name__)


def build_agent(agent_record) -> Optional[BaseAgent]:
    """Instantiate an agent from its DB record.

    Each provider gets a distinct default strategy prompt (different trading persona)
    unless a custom prompt is stored in the DB record.
    """
    settings = get_settings()
    provider = agent_record.llm_provider
    custom_prompt = agent_record.strategy_prompt or ""

    # Use provider-specific default persona when no custom prompt is stored
    if not custom_prompt:
        from sol.agents.claude_agent import (
            DEFAULT_STRATEGY_PROMPT,
            GPT_STRATEGY_PROMPT,
            GEMINI_STRATEGY_PROMPT,
        )
        custom_prompt = {
            "anthropic": DEFAULT_STRATEGY_PROMPT,
            "openai":    GPT_STRATEGY_PROMPT,
            "google":    GEMINI_STRATEGY_PROMPT,
        }.get(provider, DEFAULT_STRATEGY_PROMPT)

    # Inject confidence threshold from config_json (default 92%)
    config = agent_record.config_json or {}
    min_confidence = int(config.get("min_confidence", 92))
    custom_prompt = (
        (custom_prompt or "").rstrip()
        + f"\n\nConfidence threshold: Only call propose_strategy if your conviction is "
        f"≥{min_confidence}%. If you are less than {min_confidence}% confident — for any reason "
        f"— set no_opportunity=true. When uncertain, always choose no_opportunity=true.\n"
    )

    kwargs = dict(
        agent_id=agent_record.id,
        name=agent_record.name,
        model_id=agent_record.model_id,
        strategy_prompt=custom_prompt,
        virtual_capital=agent_record.virtual_capital,
    )

    try:
        if provider == "anthropic":
            from sol.agents.claude_agent import ClaudeAgent
            return ClaudeAgent(**kwargs, api_key=settings.ANTHROPIC_API_KEY)
        elif provider == "openai":
            from sol.agents.gpt_agent import GPTAgent
            return GPTAgent(**kwargs, api_key=settings.OPENAI_API_KEY)
        elif provider == "google":
            from sol.agents.gemini_agent import GeminiAgent
            return GeminiAgent(**kwargs, api_key=settings.GOOGLE_API_KEY)
        else:
            logger.error(f"Unknown LLM provider: {provider}")
            return None
    except Exception as e:
        logger.error(f"Failed to build agent {agent_record.name}: {e}")
        return None


class AgentManager:
    def __init__(self):
        self._agents: dict[str, BaseAgent] = {}

    async def reload_agents(self, db_session):
        """Reload active agents from DB. Called at startup and on config change."""
        from sol.models.agent import Agent
        from sqlalchemy import select

        result = await db_session.execute(select(Agent).where(Agent.is_active == True))
        agent_records = result.scalars().all()

        new_agents = {}
        for record in agent_records:
            if record.id in self._agents:
                # Keep existing instance (preserves virtual portfolio state)
                new_agents[record.id] = self._agents[record.id]
            else:
                agent = build_agent(record)
                if agent:
                    new_agents[record.id] = agent
                    logger.info(f"Loaded agent: {record.name} ({record.model_id})")

        self._agents = new_agents
        logger.info(f"Agent manager: {len(self._agents)} active agents")

    def get_agents(self) -> list[BaseAgent]:
        return list(self._agents.values())

    def get_agent(self, agent_id: str) -> Optional[BaseAgent]:
        return self._agents.get(agent_id)

    async def run_analysis_cycle(
        self,
        market_snapshots: list[MarketDataSnapshot],
        open_positions: list[dict],
    ) -> dict[str, list[TradeProposalCreate]]:
        """
        Run all agents concurrently. Returns {agent_id: [proposals]}.
        """
        if not self._agents:
            logger.warning("No active agents to run")
            return {}

        async def run_agent(agent: BaseAgent):
            try:
                proposals = await agent.analyze_and_propose(market_snapshots, open_positions)
                logger.info(f"[{agent.name}] Proposed {len(proposals)} trades")
                return agent.agent_id, proposals
            except Exception as e:
                logger.error(f"[{agent.name}] Analysis cycle error: {e}")
                return agent.agent_id, []

        results = await asyncio.gather(*[run_agent(a) for a in self._agents.values()])
        return {agent_id: proposals for agent_id, proposals in results}

    async def get_all_performance(self) -> list[dict]:
        results = []
        for agent in self._agents.values():
            perf = await agent.get_performance_summary()
            results.append(perf)
        return results


# Singleton
_manager: Optional[AgentManager] = None


def get_agent_manager() -> AgentManager:
    global _manager
    if _manager is None:
        _manager = AgentManager()
    return _manager
