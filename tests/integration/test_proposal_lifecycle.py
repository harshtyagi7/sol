"""
Integration tests for the full trade proposal lifecycle.
Uses SQLite in-memory DB — no external services required.
"""

import pytest
import pytest_asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import pytz

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select

from sol.models.base import Base
from sol.models.trade import TradeProposal
from sol.models.position import Position
from sol.models.risk_config import RiskConfig

IST = pytz.timezone("Asia/Kolkata")

# Use in-memory SQLite for integration tests (no Docker needed)
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def engine():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def risk_config(db_session):
    cfg = RiskConfig(
        max_capital_pct=2.0,
        daily_loss_limit_pct=5.0,
        max_open_positions=5,
        max_position_size_pct=10.0,
        require_stop_loss=True,
        is_active=True,
    )
    db_session.add(cfg)
    await db_session.flush()
    return cfg


@pytest_asyncio.fixture
async def pending_proposal(db_session):
    proposal = TradeProposal(
        agent_id="agent-001",
        agent_name="test-claude",
        symbol="RELIANCE",
        exchange="NSE",
        direction="BUY",
        order_type="MARKET",
        product_type="MIS",
        quantity=10,
        entry_price=2850.0,
        stop_loss=2800.0,
        take_profit=2950.0,
        rationale="Strong breakout above 2850 resistance with volume confirmation",
        risk_amount=500.0,
        risk_pct=0.05,
        status="PENDING",
        proposed_at=datetime.now(IST),
        is_virtual=True,
    )
    db_session.add(proposal)
    await db_session.flush()
    return proposal


class TestProposalCreation:
    @pytest.mark.asyncio
    async def test_proposal_saved_to_db(self, db_session, pending_proposal):
        result = await db_session.execute(
            select(TradeProposal).where(TradeProposal.id == pending_proposal.id)
        )
        retrieved = result.scalar_one_or_none()
        assert retrieved is not None
        assert retrieved.symbol == "RELIANCE"
        assert retrieved.status == "PENDING"

    @pytest.mark.asyncio
    async def test_proposal_fields_correct(self, db_session, pending_proposal):
        result = await db_session.execute(select(TradeProposal))
        proposals = result.scalars().all()
        assert len(proposals) == 1
        p = proposals[0]
        assert p.direction == "BUY"
        assert p.quantity == 10
        assert p.entry_price == 2850.0
        assert p.stop_loss == 2800.0
        assert p.is_virtual is True


class TestProposalRejection:
    @pytest.mark.asyncio
    async def test_reject_sets_status(self, db_session, pending_proposal):
        pending_proposal.status = "REJECTED"
        pending_proposal.user_note = "Not the right entry point"
        pending_proposal.reviewed_at = datetime.now(IST)
        await db_session.flush()

        result = await db_session.execute(
            select(TradeProposal).where(TradeProposal.id == pending_proposal.id)
        )
        p = result.scalar_one()
        assert p.status == "REJECTED"
        assert p.user_note == "Not the right entry point"
        assert p.reviewed_at is not None

    @pytest.mark.asyncio
    async def test_rejected_proposal_not_in_pending_query(self, db_session, pending_proposal):
        pending_proposal.status = "REJECTED"
        await db_session.flush()

        result = await db_session.execute(
            select(TradeProposal).where(TradeProposal.status == "PENDING")
        )
        assert result.scalars().all() == []


class TestProposalApproval:
    @pytest.mark.asyncio
    async def test_approve_creates_position(self, db_session, pending_proposal):
        """Simulate the approval flow: update proposal + create position."""
        pending_proposal.status = "EXECUTED"
        pending_proposal.kite_order_id = "PAPER-TEST001"
        pending_proposal.reviewed_at = datetime.now(IST)
        pending_proposal.executed_at = datetime.now(IST)

        position = Position(
            proposal_id=pending_proposal.id,
            agent_id=pending_proposal.agent_id,
            agent_name=pending_proposal.agent_name,
            is_virtual=True,
            symbol=pending_proposal.symbol,
            exchange=pending_proposal.exchange,
            direction=pending_proposal.direction,
            product_type=pending_proposal.product_type,
            quantity=pending_proposal.quantity,
            avg_price=pending_proposal.entry_price,
            stop_loss=pending_proposal.stop_loss,
            take_profit=pending_proposal.take_profit,
            opened_at=datetime.now(IST),
            status="OPEN",
        )
        db_session.add(position)
        await db_session.flush()

        result = await db_session.execute(
            select(Position).where(Position.proposal_id == pending_proposal.id)
        )
        pos = result.scalar_one_or_none()
        assert pos is not None
        assert pos.status == "OPEN"
        assert pos.quantity == 10
        assert pos.avg_price == 2850.0

    @pytest.mark.asyncio
    async def test_approved_proposal_status_executed(self, db_session, pending_proposal):
        pending_proposal.status = "EXECUTED"
        pending_proposal.kite_order_id = "PAPER-XYZ"
        await db_session.flush()

        result = await db_session.execute(
            select(TradeProposal).where(TradeProposal.id == pending_proposal.id)
        )
        p = result.scalar_one()
        assert p.status == "EXECUTED"
        assert p.kite_order_id == "PAPER-XYZ"


class TestPositionPnL:
    @pytest.mark.asyncio
    async def test_unrealized_pnl_long_profit(self, db_session, pending_proposal):
        position = Position(
            proposal_id=pending_proposal.id,
            agent_id="agent-001",
            agent_name="test",
            is_virtual=True,
            symbol="RELIANCE",
            exchange="NSE",
            direction="BUY",
            product_type="MIS",
            quantity=10,
            avg_price=2850.0,
            current_price=2900.0,
            opened_at=datetime.now(IST),
            status="OPEN",
        )
        db_session.add(position)
        await db_session.flush()
        assert abs(position.unrealized_pnl - 500.0) < 0.01

    @pytest.mark.asyncio
    async def test_unrealized_pnl_long_loss(self, db_session, pending_proposal):
        position = Position(
            proposal_id=pending_proposal.id,
            agent_id="agent-001", agent_name="test",
            is_virtual=True, symbol="INFY", exchange="NSE",
            direction="BUY", product_type="MIS",
            quantity=10, avg_price=1800.0, current_price=1750.0,
            opened_at=datetime.now(IST), status="OPEN",
        )
        db_session.add(position)
        await db_session.flush()
        assert abs(position.unrealized_pnl - (-500.0)) < 0.01

    @pytest.mark.asyncio
    async def test_position_close_updates_status(self, db_session, pending_proposal):
        position = Position(
            proposal_id=pending_proposal.id,
            agent_id="agent-001", agent_name="test",
            is_virtual=True, symbol="TCS", exchange="NSE",
            direction="BUY", product_type="MIS",
            quantity=5, avg_price=4200.0, current_price=4200.0,
            opened_at=datetime.now(IST), status="OPEN",
        )
        db_session.add(position)
        await db_session.flush()

        position.status = "SL_HIT"
        position.close_price = 4150.0
        position.realized_pnl = -250.0
        position.closed_at = datetime.now(IST)
        await db_session.flush()

        result = await db_session.execute(select(Position).where(Position.id == position.id))
        closed = result.scalar_one()
        assert closed.status == "SL_HIT"
        assert closed.realized_pnl == -250.0

    @pytest.mark.asyncio
    async def test_open_positions_query(self, db_session, pending_proposal):
        for symbol in ["RELIANCE", "INFY", "TCS"]:
            db_session.add(Position(
                proposal_id=pending_proposal.id,
                agent_id="agent-001", agent_name="test",
                is_virtual=True, symbol=symbol, exchange="NSE",
                direction="BUY", product_type="MIS",
                quantity=5, avg_price=1000.0,
                opened_at=datetime.now(IST), status="OPEN",
            ))
        # Add one closed position
        db_session.add(Position(
            proposal_id=pending_proposal.id,
            agent_id="agent-001", agent_name="test",
            is_virtual=True, symbol="HDFC", exchange="NSE",
            direction="BUY", product_type="MIS",
            quantity=5, avg_price=1680.0,
            opened_at=datetime.now(IST), status="SL_HIT",
        ))
        await db_session.flush()

        result = await db_session.execute(
            select(Position).where(Position.status == "OPEN")
        )
        open_positions = result.scalars().all()
        assert len(open_positions) == 3
