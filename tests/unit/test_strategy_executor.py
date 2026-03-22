"""Unit tests for StrategyExecutor — cap checks, trade cancellation."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sol.core.strategy_executor import StrategyExecutor


def make_strategy(status="ACTIVE", max_loss=1000.0, actual_loss=0.0):
    s = MagicMock()
    s.id = "strat-001"
    s.name = "Test Strategy"
    s.status = status
    s.max_loss_approved = max_loss
    s.actual_loss = actual_loss
    s.agent_name = "agent-alpha"
    s.is_virtual = True
    return s


def make_trade(status="PENDING", symbol="RELIANCE"):
    t = MagicMock()
    t.id = "trade-001"
    t.strategy_id = "strat-001"
    t.sequence = 1
    t.status = status
    t.symbol = symbol
    t.exchange = "NSE"
    t.direction = "BUY"
    t.order_type = "MARKET"
    t.product_type = "MIS"
    t.quantity = 10
    t.entry_price = 2850.0
    t.stop_loss = 2800.0
    t.take_profit = 2950.0
    t.rationale = "Test"
    t.agent_id = "agent-001"
    return t


class TestCapCheck:
    @pytest.mark.asyncio
    async def test_cap_not_hit_when_below_limit(self):
        executor = StrategyExecutor()
        strategy = make_strategy(max_loss=1000.0, actual_loss=400.0)

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = strategy
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("sol.core.strategy_executor.get_session", return_value=mock_db):
            hit = await executor._is_cap_hit("strat-001")
        assert hit is False

    @pytest.mark.asyncio
    async def test_cap_hit_when_at_limit(self):
        executor = StrategyExecutor()
        strategy = make_strategy(max_loss=500.0, actual_loss=500.0)

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = strategy
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("sol.core.strategy_executor.get_session", return_value=mock_db):
            hit = await executor._is_cap_hit("strat-001")
        assert hit is True

    @pytest.mark.asyncio
    async def test_cap_hit_when_exceeds_limit(self):
        executor = StrategyExecutor()
        strategy = make_strategy(max_loss=500.0, actual_loss=600.0)

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = strategy
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("sol.core.strategy_executor.get_session", return_value=mock_db):
            hit = await executor._is_cap_hit("strat-001")
        assert hit is True

    @pytest.mark.asyncio
    async def test_cap_not_hit_when_no_cap_set(self):
        executor = StrategyExecutor()
        strategy = make_strategy(max_loss=0.0, actual_loss=999.0)

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = strategy
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("sol.core.strategy_executor.get_session", return_value=mock_db):
            hit = await executor._is_cap_hit("strat-001")
        assert hit is False

    @pytest.mark.asyncio
    async def test_cap_hit_when_strategy_not_found(self):
        executor = StrategyExecutor()

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("sol.core.strategy_executor.get_session", return_value=mock_db):
            hit = await executor._is_cap_hit("nonexistent")
        assert hit is True

    @pytest.mark.asyncio
    async def test_cap_hit_when_strategy_cancelled(self):
        executor = StrategyExecutor()
        strategy = make_strategy(status="CANCELLED", max_loss=1000.0, actual_loss=0.0)

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = strategy
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("sol.core.strategy_executor.get_session", return_value=mock_db):
            hit = await executor._is_cap_hit("strat-001")
        assert hit is True


class TestOnTradeClosed:
    @pytest.mark.asyncio
    async def test_on_trade_closed_delegates_to_service(self):
        executor = StrategyExecutor()
        mock_service = AsyncMock()
        mock_service.update_actual_loss = AsyncMock(return_value=False)

        with patch("sol.core.strategy_executor.get_strategy_service",
                   return_value=mock_service):
            await executor.on_trade_closed("strat-001", realized_pnl=-300.0)

        mock_service.update_actual_loss.assert_called_once_with("strat-001", -300.0)

    @pytest.mark.asyncio
    async def test_on_trade_closed_cancels_remaining_when_cap_hit(self):
        executor = StrategyExecutor()
        mock_service = AsyncMock()
        mock_service.update_actual_loss = AsyncMock(return_value=True)  # cap hit

        with patch("sol.core.strategy_executor.get_strategy_service",
                   return_value=mock_service):
            with patch.object(executor, "_cancel_remaining", new_callable=AsyncMock) as mock_cancel:
                await executor.on_trade_closed("strat-001", realized_pnl=-1000.0)

        mock_cancel.assert_called_once_with("strat-001", "Max loss cap reached")

    @pytest.mark.asyncio
    async def test_on_trade_closed_no_cancel_when_cap_not_hit(self):
        executor = StrategyExecutor()
        mock_service = AsyncMock()
        mock_service.update_actual_loss = AsyncMock(return_value=False)

        with patch("sol.core.strategy_executor.get_strategy_service",
                   return_value=mock_service):
            with patch.object(executor, "_cancel_remaining", new_callable=AsyncMock) as mock_cancel:
                await executor.on_trade_closed("strat-001", realized_pnl=-200.0)

        mock_cancel.assert_not_called()


class TestStrategyExecutorSingleton:
    def test_get_strategy_executor_returns_same_instance(self):
        from sol.core.strategy_executor import get_strategy_executor
        e1 = get_strategy_executor()
        e2 = get_strategy_executor()
        assert e1 is e2

    def test_executor_is_strategy_executor_type(self):
        from sol.core.strategy_executor import get_strategy_executor
        assert isinstance(get_strategy_executor(), StrategyExecutor)
