"""Unit tests for VirtualPortfolio and VirtualPosition."""

import pytest
from sol.agents.base_agent import VirtualPortfolio, VirtualPosition


class TestVirtualPosition:
    def test_long_unrealized_pnl_profit(self):
        pos = VirtualPosition("RELIANCE", "NSE", "BUY", 10, avg_price=2800.0, current_price=2900.0)
        assert abs(pos.unrealized_pnl - 1000.0) < 0.01  # 10 * 100

    def test_long_unrealized_pnl_loss(self):
        pos = VirtualPosition("RELIANCE", "NSE", "BUY", 10, avg_price=2800.0, current_price=2750.0)
        assert abs(pos.unrealized_pnl - (-500.0)) < 0.01  # 10 * -50

    def test_short_unrealized_pnl_profit(self):
        # Short: price fell, profit
        pos = VirtualPosition("INFY", "NSE", "SELL", 5, avg_price=1800.0, current_price=1750.0)
        assert abs(pos.unrealized_pnl - 250.0) < 0.01  # 5 * 50

    def test_short_unrealized_pnl_loss(self):
        # Short: price rose, loss
        pos = VirtualPosition("INFY", "NSE", "SELL", 5, avg_price=1800.0, current_price=1850.0)
        assert abs(pos.unrealized_pnl - (-250.0)) < 0.01

    def test_zero_pnl_at_avg_price(self):
        pos = VirtualPosition("TCS", "NSE", "BUY", 10, avg_price=4200.0, current_price=4200.0)
        assert pos.unrealized_pnl == 0.0

    def test_fractional_pnl(self):
        pos = VirtualPosition("HDFC", "NSE", "BUY", 3, avg_price=1680.50, current_price=1685.75)
        expected = 3 * (1685.75 - 1680.50)
        assert abs(pos.unrealized_pnl - expected) < 0.001


class TestVirtualPortfolio:
    def test_initial_values(self):
        vp = VirtualPortfolio(initial_capital=500_000.0)
        assert vp.cash == 500_000.0
        assert vp.total_value == 500_000.0
        assert vp.total_pnl == 0.0
        assert vp.win_rate == 0.0

    def test_total_value_with_open_position(self):
        vp = VirtualPortfolio(1_000_000.0)
        vp.positions.append(
            VirtualPosition("RELIANCE", "NSE", "BUY", 10, avg_price=2850.0, current_price=2900.0)
        )
        # total_value = cash + invested + unrealized = 1M + 28500 + 500
        expected = 1_000_000.0 + (2850.0 * 10) + (50.0 * 10)
        assert abs(vp.total_value - expected) < 0.01

    def test_total_pnl_reflects_unrealized(self):
        vp = VirtualPortfolio(1_000_000.0)
        vp.positions.append(
            VirtualPosition("RELIANCE", "NSE", "BUY", 10, avg_price=2850.0, current_price=2900.0)
        )
        assert abs(vp.total_pnl - 500.0) < 0.01

    def test_total_pnl_loss(self):
        vp = VirtualPortfolio(1_000_000.0)
        vp.positions.append(
            VirtualPosition("INFY", "NSE", "BUY", 10, avg_price=1800.0, current_price=1750.0)
        )
        assert abs(vp.total_pnl - (-500.0)) < 0.01

    def test_win_rate_all_wins(self):
        vp = VirtualPortfolio(1_000_000.0)
        vp.closed_trades = [{"pnl": 1000}, {"pnl": 500}, {"pnl": 200}]
        assert vp.win_rate == 100.0

    def test_win_rate_all_losses(self):
        vp = VirtualPortfolio(1_000_000.0)
        vp.closed_trades = [{"pnl": -100}, {"pnl": -50}]
        assert vp.win_rate == 0.0

    def test_win_rate_mixed(self):
        vp = VirtualPortfolio(1_000_000.0)
        vp.closed_trades = [{"pnl": 1000}, {"pnl": -200}, {"pnl": 500}, {"pnl": -100}]
        assert abs(vp.win_rate - 50.0) < 0.01

    def test_win_rate_no_trades(self):
        vp = VirtualPortfolio(1_000_000.0)
        assert vp.win_rate == 0.0

    def test_multiple_positions_total_value(self):
        vp = VirtualPortfolio(1_000_000.0)
        vp.positions.append(VirtualPosition("RELIANCE", "NSE", "BUY", 5, 2850.0, 2900.0))
        vp.positions.append(VirtualPosition("INFY", "NSE", "BUY", 10, 1750.0, 1800.0))
        invested = 5 * 2850.0 + 10 * 1750.0
        unrealized = 5 * 50.0 + 10 * 50.0
        expected = 1_000_000.0 + invested + unrealized
        assert abs(vp.total_value - expected) < 0.01

    def test_no_positions_total_value_equals_cash(self):
        vp = VirtualPortfolio(750_000.0)
        assert vp.total_value == vp.cash


class TestBaseAgentPerformanceSummary:
    @pytest.mark.asyncio
    async def test_performance_summary_structure(self):
        from sol.agents.claude_agent import ClaudeAgent
        agent = ClaudeAgent("agent-001", "test", "claude-sonnet-4-6", virtual_capital=1_000_000.0)
        summary = await agent.get_performance_summary()

        assert summary["agent_id"] == "agent-001"
        assert summary["agent_name"] == "test"
        assert summary["model_id"] == "claude-sonnet-4-6"
        assert summary["virtual_capital_initial"] == 1_000_000.0
        assert summary["virtual_capital_current"] == 1_000_000.0
        assert summary["total_pnl"] == 0.0
        assert summary["total_pnl_pct"] == 0.0
        assert summary["win_rate"] == 0.0
        assert summary["open_positions"] == 0
        assert summary["closed_trades"] == 0

    @pytest.mark.asyncio
    async def test_performance_summary_with_pnl(self):
        from sol.agents.claude_agent import ClaudeAgent
        agent = ClaudeAgent("agent-001", "test", "claude-sonnet-4-6", virtual_capital=1_000_000.0)
        agent.virtual_portfolio.positions.append(
            VirtualPosition("RELIANCE", "NSE", "BUY", 10, 2850.0, 2900.0)
        )
        agent.virtual_portfolio.closed_trades = [{"pnl": 1000}, {"pnl": -200}]
        summary = await agent.get_performance_summary()

        assert summary["total_pnl"] == 500.0
        assert summary["open_positions"] == 1
        assert summary["closed_trades"] == 2
        assert summary["win_rate"] == 50.0
