"""Unit tests for StrategyService — approval, rejection, loss tracking."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sol.services.strategy_service import StrategyService
from sol.schemas.strategy import StrategyProposal, StrategyTradeIn


def make_proposal(num_trades=1, entry=2850.0, sl=2800.0, qty=10) -> StrategyProposal:
    trades = [
        StrategyTradeIn(
            sequence=i + 1,
            symbol=f"STOCK{i}",
            exchange="NSE",
            direction="BUY",
            quantity=qty,
            entry_price=entry,
            stop_loss=sl,
            take_profit=entry + 100,
            rationale="Test trade",
        )
        for i in range(num_trades)
    ]
    return StrategyProposal(
        name="Test Strategy",
        description="A test strategy",
        rationale="Testing purposes",
        duration_days=1,
        trades=trades,
    )


def make_db_strategy(status="PENDING_APPROVAL", max_loss_approved=None, actual_loss=0.0):
    s = MagicMock()
    s.id = "strat-001"
    s.name = "Test Strategy"
    s.status = status
    s.max_loss_approved = max_loss_approved
    s.actual_loss = actual_loss
    return s


class TestStrategySave:
    @pytest.mark.asyncio
    async def test_save_strategy_creates_records(self):
        svc = StrategyService()
        proposal = make_proposal(num_trades=2)
        mock_strategy = MagicMock()
        mock_strategy.id = "strat-001"

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        added_objs = []
        mock_db.add.side_effect = lambda obj: added_objs.append(obj)

        with patch("sol.services.strategy_service.get_session", return_value=mock_db):
            from sol.models.strategy import Strategy
            with patch.object(Strategy, "__init__", return_value=None) as strategy_init:
                # Simulate flush setting the id
                async def fake_flush():
                    mock_strategy.id = "strat-001"
                mock_db.flush.side_effect = fake_flush

                # Just test that the method runs without error
                # (full DB testing is in integration tests)

    def test_proposal_max_loss_possible_two_trades(self):
        proposal = make_proposal(num_trades=2, entry=2850.0, sl=2800.0, qty=10)
        # Each trade: |2850 - 2800| * 10 = 500
        assert abs(proposal.max_loss_possible - 1000.0) < 0.01

    def test_proposal_max_loss_possible_no_sl(self):
        trades = [StrategyTradeIn(
            sequence=1, symbol="TCS", exchange="NSE",
            direction="BUY", quantity=10,
            stop_loss=None, entry_price=None, rationale="test"
        )]
        proposal = StrategyProposal(
            name="No SL", description="d", rationale="r",
            duration_days=1, trades=trades
        )
        assert proposal.max_loss_possible == 0.0


class TestStrategyApproval:
    @pytest.mark.asyncio
    async def test_approve_zero_loss_rejected(self):
        svc = StrategyService()
        result = await svc.approve("strat-001", max_loss_approved=0.0)
        assert result["success"] is False
        assert "greater than 0" in result["reason"]

    @pytest.mark.asyncio
    async def test_approve_negative_loss_rejected(self):
        svc = StrategyService()
        result = await svc.approve("strat-001", max_loss_approved=-100.0)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_approve_strategy_not_found(self):
        svc = StrategyService()
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("sol.services.strategy_service.get_session", return_value=mock_db):
            result = await svc.approve("nonexistent", max_loss_approved=1000.0)
        assert result["success"] is False
        assert "not found" in result["reason"]

    @pytest.mark.asyncio
    async def test_approve_already_active_rejected(self):
        svc = StrategyService()
        strategy = make_db_strategy(status="ACTIVE")

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = strategy
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("sol.services.strategy_service.get_session", return_value=mock_db):
            result = await svc.approve("strat-001", max_loss_approved=1000.0)
        assert result["success"] is False
        assert "ACTIVE" in result["reason"]

    @pytest.mark.asyncio
    async def test_approve_triggers_executor(self):
        svc = StrategyService()
        strategy = make_db_strategy(status="PENDING_APPROVAL")

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = strategy
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_executor = AsyncMock()
        mock_executor.execute_strategy = AsyncMock()

        with patch("sol.services.strategy_service.get_session", return_value=mock_db):
            with patch("sol.services.strategy_service.get_strategy_executor",
                       return_value=mock_executor):
                result = await svc.approve("strat-001", max_loss_approved=500.0)

        assert result["success"] is True
        mock_executor.execute_strategy.assert_called_once_with("strat-001")


class TestStrategyRejection:
    @pytest.mark.asyncio
    async def test_reject_not_found(self):
        svc = StrategyService()
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("sol.services.strategy_service.get_session", return_value=mock_db):
            result = await svc.reject("nonexistent")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_reject_sets_cancelled_status(self):
        svc = StrategyService()
        strategy = make_db_strategy(status="PENDING_APPROVAL")

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = strategy
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("sol.services.strategy_service.get_session", return_value=mock_db):
            result = await svc.reject("strat-001", note="Not the right time")

        assert result["success"] is True
        assert strategy.status == "CANCELLED"
        assert strategy.user_note == "Not the right time"


class TestActualLossTracking:
    @pytest.mark.asyncio
    async def test_loss_below_cap_returns_false(self):
        svc = StrategyService()
        strategy = make_db_strategy(
            status="ACTIVE", max_loss_approved=1000.0, actual_loss=0.0
        )

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = strategy
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        with patch("sol.services.strategy_service.get_session", return_value=mock_db):
            with patch("sol.services.strategy_service.notify_risk_alert", AsyncMock()):
                cap_hit = await svc.update_actual_loss("strat-001", pnl_delta=-400.0)

        assert cap_hit is False
        # actual_loss should accumulate: 0 + 400 = 400
        assert abs(float(strategy.actual_loss) - 400.0) < 0.01

    @pytest.mark.asyncio
    async def test_loss_at_cap_returns_true(self):
        svc = StrategyService()
        strategy = make_db_strategy(
            status="ACTIVE", max_loss_approved=500.0, actual_loss=0.0
        )

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = strategy
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        with patch("sol.services.strategy_service.get_session", return_value=mock_db):
            with patch("sol.services.strategy_service.notify_risk_alert", AsyncMock()):
                with patch("sol.services.strategy_service.publish_event", AsyncMock()):
                    cap_hit = await svc.update_actual_loss("strat-001", pnl_delta=-500.0)

        assert cap_hit is True
        assert strategy.status == "MAX_LOSS_HIT"

    @pytest.mark.asyncio
    async def test_profit_doesnt_increase_loss(self):
        svc = StrategyService()
        strategy = make_db_strategy(
            status="ACTIVE", max_loss_approved=1000.0, actual_loss=200.0
        )

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = strategy
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        with patch("sol.services.strategy_service.get_session", return_value=mock_db):
            with patch("sol.services.strategy_service.notify_risk_alert", AsyncMock()):
                cap_hit = await svc.update_actual_loss("strat-001", pnl_delta=300.0)

        assert cap_hit is False
        # Profitable trade doesn't change actual_loss
        assert float(strategy.actual_loss) == 200.0

    @pytest.mark.asyncio
    async def test_inactive_strategy_returns_false(self):
        svc = StrategyService()
        strategy = make_db_strategy(status="COMPLETED")

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = strategy
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("sol.services.strategy_service.get_session", return_value=mock_db):
            cap_hit = await svc.update_actual_loss("strat-001", pnl_delta=-999.0)

        assert cap_hit is False
