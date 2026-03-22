"""Unit tests for the Risk Engine — the most critical component."""

import pytest
from unittest.mock import MagicMock
from sol.core.risk_engine import RiskEngine
from sol.schemas.trade import TradeProposalCreate


def make_config(
    max_capital_pct=2.0,
    daily_loss_limit_pct=5.0,
    max_open_positions=5,
    max_position_size_pct=10.0,
    require_stop_loss=True,
):
    cfg = MagicMock()
    cfg.max_capital_pct = max_capital_pct
    cfg.daily_loss_limit_pct = daily_loss_limit_pct
    cfg.max_open_positions = max_open_positions
    cfg.max_position_size_pct = max_position_size_pct
    cfg.require_stop_loss = require_stop_loss
    return cfg


def make_proposal(
    symbol="RELIANCE",
    direction="BUY",
    quantity=10,
    entry_price=2850.0,
    stop_loss=2800.0,
    take_profit=2950.0,
):
    return TradeProposalCreate(
        symbol=symbol,
        exchange="NSE",
        direction=direction,
        quantity=quantity,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        rationale="Test trade",
    )


# Patch market hours to always be open
@pytest.fixture(autouse=True)
def mock_market_open(monkeypatch):
    monkeypatch.setattr("sol.core.risk_engine.is_market_open", lambda: True)


class TestRiskEngine:
    def test_valid_trade_passes(self):
        cfg = make_config()
        engine = RiskEngine(cfg, capital=1_000_000.0, daily_pnl=0.0, open_position_count=0)
        proposal = make_proposal()
        report = engine.validate(proposal)
        assert report.approved is True
        assert report.violations == []

    def test_daily_loss_limit_blocks_trade(self):
        cfg = make_config(daily_loss_limit_pct=5.0)
        # daily_pnl of -55000 on 1M capital = 5.5% loss
        engine = RiskEngine(cfg, capital=1_000_000.0, daily_pnl=-55_000.0, open_position_count=0)
        proposal = make_proposal()
        report = engine.validate(proposal)
        assert report.approved is False
        assert any("daily loss limit" in v.lower() for v in report.violations)

    def test_daily_loss_at_limit_blocks(self):
        cfg = make_config(daily_loss_limit_pct=5.0)
        engine = RiskEngine(cfg, capital=1_000_000.0, daily_pnl=-50_000.0, open_position_count=0)
        proposal = make_proposal()
        report = engine.validate(proposal)
        assert report.approved is False

    def test_daily_pnl_positive_allows_trade(self):
        cfg = make_config()
        engine = RiskEngine(cfg, capital=1_000_000.0, daily_pnl=10_000.0, open_position_count=0)
        proposal = make_proposal()
        report = engine.validate(proposal)
        assert report.approved is True

    def test_missing_stop_loss_blocked(self):
        cfg = make_config(require_stop_loss=True)
        engine = RiskEngine(cfg, capital=1_000_000.0, daily_pnl=0.0, open_position_count=0)
        proposal = TradeProposalCreate(
            symbol="INFY", exchange="NSE", direction="BUY",
            quantity=10, entry_price=1750.0, stop_loss=None,
            take_profit=1800.0, rationale="No SL trade"
        )
        report = engine.validate(proposal)
        assert report.approved is False
        assert any("stop-loss" in v.lower() for v in report.violations)

    def test_stop_loss_not_required_passes(self):
        cfg = make_config(require_stop_loss=False)
        engine = RiskEngine(cfg, capital=1_000_000.0, daily_pnl=0.0, open_position_count=0)
        proposal = TradeProposalCreate(
            symbol="INFY", exchange="NSE", direction="BUY",
            quantity=10, entry_price=1750.0, stop_loss=None,
            rationale="No SL trade"
        )
        report = engine.validate(proposal)
        assert report.approved is True

    def test_max_positions_blocks_trade(self):
        cfg = make_config(max_open_positions=3)
        engine = RiskEngine(cfg, capital=1_000_000.0, daily_pnl=0.0, open_position_count=3)
        proposal = make_proposal()
        report = engine.validate(proposal)
        assert report.approved is False
        assert any("max open positions" in v.lower() for v in report.violations)

    def test_quantity_reduced_to_meet_risk_limit(self):
        cfg = make_config(max_capital_pct=1.0)
        # 100 shares * ₹50 SL = ₹5000 risk on ₹1M = 0.5% — within limit
        engine = RiskEngine(cfg, capital=1_000_000.0, daily_pnl=0.0, open_position_count=0)
        proposal = make_proposal(quantity=500, entry_price=2850.0, stop_loss=2800.0)
        # 500 * 50 = 25000 risk = 2.5% > 1% limit
        report = engine.validate(proposal)
        assert report.approved is True
        assert report.modified_quantity is not None
        assert report.modified_quantity < 500
        assert report.risk_pct <= 1.0

    def test_risk_calculation_buy(self):
        cfg = make_config(max_capital_pct=5.0)
        engine = RiskEngine(cfg, capital=1_000_000.0, daily_pnl=0.0, open_position_count=0)
        proposal = make_proposal(quantity=10, entry_price=2850.0, stop_loss=2800.0)
        report = engine.validate(proposal)
        assert report.approved is True
        # Risk = 10 * (2850 - 2800) = 500
        assert abs(report.risk_amount - 500.0) < 0.01
        assert abs(report.risk_pct - 0.05) < 0.01  # 500/1M = 0.05%

    def test_market_closed_blocks_trade(self, monkeypatch):
        monkeypatch.setattr("sol.core.risk_engine.is_market_open", lambda: False)
        cfg = make_config()
        engine = RiskEngine(cfg, capital=1_000_000.0, daily_pnl=0.0, open_position_count=0)
        proposal = make_proposal()
        report = engine.validate(proposal)
        assert report.approved is False
        assert any("market" in v.lower() for v in report.violations)
