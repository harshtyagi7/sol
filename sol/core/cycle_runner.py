"""
Main analysis cycle runner.
Called by the scheduler every 15 minutes during market hours.
"""

import logging
from datetime import datetime

import pytz

from sol.config import get_settings

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


async def run_analysis_cycle():
    """
    Full cycle:
    1. Fetch market data for watchlist
    2. Run all agents concurrently
    3. Save each strategy proposal to DB (status: PENDING_APPROVAL)
    4. Notify user via event bus
    5. Ask Sol to generate a summary
    """
    from sol.agents.agent_manager import get_agent_manager
    from sol.core.orchestrator import get_orchestrator
    from sol.core.event_bus import publish_event
    from sol.services.market_data_service import get_market_snapshots
    from sol.services.strategy_service import get_strategy_service

    settings = get_settings()
    agent_manager = get_agent_manager()

    logger.info(f"Analysis cycle starting at {datetime.now(IST).strftime('%H:%M IST')}")

    # Reload agents from DB (picks up any config changes)
    from sol.database import get_session
    async with get_session() as db:
        await agent_manager.reload_agents(db)

    # Fetch market data first (shared between position monitor and agents)
    snapshots = await get_market_snapshots()
    if not snapshots:
        logger.warning("No market data available. Skipping cycle.")
        return

    # Monitor open positions before proposing new strategies
    from sol.core.position_monitor import run_position_monitor
    await run_position_monitor(snapshots)

    agents = agent_manager.get_agents()
    if not agents:
        logger.info("No active agents. Skipping cycle.")
        return

    # Get current open positions for agent context
    open_positions = await _get_open_positions_context()

    # Run all agents — each returns list[StrategyProposal]
    proposals_by_agent = await agent_manager.run_analysis_cycle(snapshots, open_positions)

    if not any(proposals_by_agent.values()):
        logger.info("No strategy proposals from any agent this cycle")
        return

    # Build shared market context string for peer review (use Claude agent's formatter)
    from sol.agents.claude_agent import ClaudeAgent as _ClaudeAgent
    _dummy = _ClaudeAgent.__new__(_ClaudeAgent)
    _dummy.name = "reviewer"
    market_context_for_review = _dummy._build_market_context(snapshots, open_positions)

    # Peer review: each proposal is reviewed by a DIFFERENT agent before saving.
    # Round-robin assignment: agent[i]'s proposals are reviewed by agent[(i+1) % n].
    agents = agent_manager.get_agents()
    agent_list = list(agents)
    n = len(agent_list)
    # Build agent_id → reviewer mapping
    reviewer_map: dict[str, object] = {}
    if n >= 2:
        for i, a in enumerate(agent_list):
            reviewer_map[a.agent_id] = agent_list[(i + 1) % n]

    # Save strategies and collect summaries for Sol
    strategy_service = get_strategy_service()
    saved_strategies = []

    for agent_id, strategy_proposals in proposals_by_agent.items():
        agent = agent_manager.get_agent(agent_id)
        if not agent:
            continue

        # Lookup agent DB record to get is_virtual flag
        from sol.database import get_session
        from sol.models.agent import Agent
        from sqlalchemy import select
        async with get_session() as db:
            result = await db.execute(select(Agent).where(Agent.id == agent_id))
            agent_record = result.scalar_one_or_none()
        if not agent_record:
            continue

        is_virtual = settings.PAPER_TRADING_MODE or agent_record.is_virtual
        reviewer = reviewer_map.get(agent_id)

        for proposal in strategy_proposals:
            # --- Peer review gate ---
            if reviewer is not None:
                approved, feedback = await reviewer.review_strategy(
                    proposal, market_context_for_review, agent.name
                )
                if not approved:
                    logger.info(
                        f"[{reviewer.name}] REJECTED '{proposal.name}' from {agent.name}: {feedback}"
                    )
                    await publish_event("strategy_peer_rejected", {
                        "agent": agent.name,
                        "reviewer": reviewer.name,
                        "name": proposal.name,
                        "reason": feedback,
                    })
                    continue  # do not save — strategy filtered out
                logger.info(
                    f"[{reviewer.name}] APPROVED '{proposal.name}' from {agent.name}: {feedback}"
                )
            # --- End peer review gate ---

            strategy_id = await strategy_service.save_strategy(
                proposal, agent_id, agent.name, is_virtual
            )
            saved_strategies.append({
                "id": strategy_id,
                "agent_name": agent.name,
                "name": proposal.name,
                "trade_count": len(proposal.trades),
                "max_loss_possible": proposal.max_loss_possible,
                "rationale": proposal.rationale[:200],  # type: ignore[index]
            })
            await publish_event("new_strategy_proposal", {
                "strategy_id": strategy_id,
                "agent": agent.name,
                "name": proposal.name,
                "trade_count": len(proposal.trades),
                "max_loss_possible": proposal.max_loss_possible,
            })
            logger.info(
                f"[{agent.name}] Strategy '{proposal.name}' saved ({len(proposal.trades)} trades, "
                f"max possible loss ₹{proposal.max_loss_possible:.2f}) — awaiting approval"
            )

    if saved_strategies:
        orchestrator = get_orchestrator()
        summary = await orchestrator.generate_strategy_summary(saved_strategies)
        await publish_event("cycle_summary", {
            "summary": summary,
            "strategy_count": len(saved_strategies),
            "timestamp": datetime.now(IST).isoformat(),
        })
        logger.info(f"Cycle complete: {len(saved_strategies)} strategies pending approval")


async def _get_open_positions_context() -> list[dict]:
    """Fetch open positions formatted for agent context."""
    try:
        from sol.database import get_session
        from sol.models.position import Position
        from sqlalchemy import select

        async with get_session() as db:
            result = await db.execute(
                select(Position).where(Position.status == "OPEN")
            )
            positions = result.scalars().all()
            return [
                {
                    "symbol": p.symbol,
                    "exchange": p.exchange,
                    "direction": p.direction,
                    "quantity": p.quantity,
                    "avg_price": p.avg_price,
                    "stop_loss": p.stop_loss,
                    "unrealized_pnl": p.unrealized_pnl,
                }
                for p in positions
            ]
    except Exception as e:
        logger.error(f"Could not fetch open positions: {e}")
        return []
