"""Agent management endpoints."""

from fastapi import APIRouter, HTTPException

from sol.schemas.agent import AgentCreate, AgentOut, AgentUpdate

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("")
async def list_agents():
    from sol.database import get_session
    from sol.models.agent import Agent
    from sqlalchemy import select

    async with get_session() as db:
        result = await db.execute(select(Agent))
        agents = result.scalars().all()
        return [AgentOut.model_validate(a) for a in agents]


@router.post("")
async def create_agent(data: AgentCreate):
    from sol.database import get_session
    from sol.models.agent import Agent

    async with get_session() as db:
        agent = Agent(
            name=data.name,
            llm_provider=data.llm_provider,
            model_id=data.model_id,
            strategy_prompt=data.strategy_prompt,
            paper_only=data.paper_only,
            virtual_capital=data.virtual_capital,
            config_json=data.config_json,
        )
        db.add(agent)
        await db.flush()
        return AgentOut.model_validate(agent)


@router.put("/{agent_id}")
async def update_agent(agent_id: str, data: AgentUpdate):
    from sol.database import get_session
    from sol.models.agent import Agent
    from sqlalchemy import select

    async with get_session() as db:
        result = await db.execute(select(Agent).where(Agent.id == agent_id))
        agent = result.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        if data.strategy_prompt is not None:
            agent.strategy_prompt = data.strategy_prompt
        if data.is_active is not None:
            agent.is_active = data.is_active
        if data.paper_only is not None:
            agent.paper_only = data.paper_only
        if data.config_json is not None:
            agent.config_json = data.config_json

        await db.flush()
        return AgentOut.model_validate(agent)


@router.delete("/{agent_id}")
async def deactivate_agent(agent_id: str):
    from sol.database import get_session
    from sol.models.agent import Agent
    from sqlalchemy import select

    async with get_session() as db:
        result = await db.execute(select(Agent).where(Agent.id == agent_id))
        agent = result.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        agent.is_active = False
        await db.flush()
    return {"success": True}


@router.get("/{agent_id}/performance")
async def agent_performance(agent_id: str):
    from sol.agents.agent_manager import get_agent_manager

    mgr = get_agent_manager()
    agent = mgr.get_agent(agent_id)
    if not agent:
        # Fall back to DB-based stats
        return await _db_performance(agent_id)
    return await agent.get_performance_summary()


@router.post("/{agent_id}/trigger")
async def trigger_agent(agent_id: str):
    """Manually trigger a single agent's analysis cycle."""
    from sol.agents.agent_manager import get_agent_manager
    from sol.services.market_data_service import get_market_snapshots
    from sol.core.cycle_runner import _get_open_positions_context

    mgr = get_agent_manager()
    agent = mgr.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not loaded. Ensure it is active.")

    snapshots = await get_market_snapshots()
    open_positions = await _get_open_positions_context()
    proposals = await agent.analyze_and_propose(snapshots, open_positions)

    return {"agent": agent.name, "proposals_count": len(proposals)}


async def _db_performance(agent_id: str) -> dict:
    from sol.database import get_session
    from sol.models.position import Position
    from sqlalchemy import select, func

    async with get_session() as db:
        result = await db.execute(
            select(
                func.count(Position.id).label("total"),
                func.sum(Position.realized_pnl).label("total_pnl"),
            ).where(
                Position.agent_id == agent_id,
                Position.status != "OPEN",
            )
        )
        row = result.one()
        return {
            "agent_id": agent_id,
            "total_closed_trades": row.total or 0,
            "total_realized_pnl": float(row.total_pnl or 0),
        }
