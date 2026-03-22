"""Extended risk engine tests — edge cases and SELL direction."""

import pytest
from unittest.mock import MagicMock
from sol.core.risk_engine import RiskEngine
from sol.schemas.trade import TradeProposalCreate

# Patch market always open
@pytest.fixture(autouse=True)
def market_open(monkeypatch):
    monkeypatch.setattr("sol.core.risk_engine.is_market_open", lambda: True)


def make_config(**kwargs):
    defaults = dict(
        max_capital_pct=2.0, daily_loss_limit_pct=5.0,
        max_open_positions=5, max_position_size_pct=10.0,
        require_stop_loss=True,
    )
    defaults.update(kwargs)
    cfg = MagicMock()
    for k, v in defaults.items():
        setattr(cfg, k, v)
    return cfg


def make_proposal(**kwargs):
    defaults = dict(
        symbol="RELIANCE", exchange="NSE", direction="BUY",
        order_type="MARKET", product_type="MIS",
        quantity=10, entry_price=2850.0, stop_loss=2800.0,
        take_profit=2950.0, rationale="test"
    )
    defaults.update(kwargs)
    return TradeProposalCreate(**defaults)


class TestSellDirection:
    def test_sell_risk_calculated_correctly(self):
        """For SELL, risk = (stop_loss - entry) * qty."""
        cfg = make_config(max_capital_pct=5.0)
        engine = RiskEngine(cfg, capital=1_000_000.0, daily_pnl=0.0, open_position_count=0)
        # Sell INFY @ 1800, SL @ 1850 → risk = 50 * 10 = 500
        proposal = make_proposal(
            symbol="INFY", direction="SELL",
            entry_price=1800.0, stop_loss=1850.0, take_profit=1750.0, quantity=10
        )
        report = engine.validate(proposal)
        assert report.approved is True
        assert abs(report.risk_amount - 500.0) < 0.01

    def test_sell_quantity_reduced_if_over_limit(self):
        cfg = make_config(max_capital_pct=0.5)
        engine = RiskEngine(cfg, capital=1_000_000.0, daily_pnl=0.0, open_position_count=0)
        proposal = make_proposal(
            direction="SELL", entry_price=1800.0, stop_loss=1850.0,
            quantity=200, symbol="INFY"
        )
        report = engine.validate(proposal)
        assert report.approved is True
        assert report.modified_quantity is not None
        assert report.modified_quantity < 200


class TestPositionSizeLimit:
    def test_large_position_size_quantity_reduced(self):
        """Single stock allocation exceeds max_position_size_pct → quantity reduced."""
        cfg = make_config(max_position_size_pct=5.0, max_capital_pct=100.0)
        # Capital 1M, max pos size 5% = 50000. 100 shares @ 2850 = 285000 → too big
        engine = RiskEngine(cfg, capital=1_000_000.0, daily_pnl=0.0, open_position_count=0)
        proposal = make_proposal(quantity=100, entry_price=2850.0)
        report = engine.validate(proposal)
        assert report.approved is True
        # Max qty = 1M * 5% / 2850 ≈ 17
        assert report.modified_quantity is not None
        assert report.modified_quantity * 2850.0 <= 1_000_000.0 * 0.05 + 1  # allow rounding

    def test_position_within_size_limit_passes(self):
        cfg = make_config(max_position_size_pct=10.0, max_capital_pct=100.0)
        engine = RiskEngine(cfg, capital=1_000_000.0, daily_pnl=0.0, open_position_count=0)
        # 10 shares @ 2850 = 28500 = 2.85% of 1M → within 10%
        proposal = make_proposal(quantity=10, entry_price=2850.0)
        report = engine.validate(proposal)
        assert report.approved is True
        assert report.modified_quantity is None or report.modified_quantity == 10


class TestDailyPnLBoundary:
    def test_daily_pnl_exactly_at_limit_blocks(self):
        cfg = make_config(daily_loss_limit_pct=5.0)
        engine = RiskEngine(cfg, capital=1_000_000.0, daily_pnl=-50_000.0, open_position_count=0)
        report = engine.validate(make_proposal())
        assert report.approved is False

    def test_daily_pnl_one_rupee_below_limit_blocks(self):
        cfg = make_config(daily_loss_limit_pct=5.0)
        engine = RiskEngine(cfg, capital=1_000_000.0, daily_pnl=-50_001.0, open_position_count=0)
        report = engine.validate(make_proposal())
        assert report.approved is False

    def test_daily_pnl_one_rupee_above_limit_passes(self):
        cfg = make_config(daily_loss_limit_pct=5.0)
        # -49999 / 1M = 4.9999% < 5% → OK
        engine = RiskEngine(cfg, capital=1_000_000.0, daily_pnl=-49_999.0, open_position_count=0)
        report = engine.validate(make_proposal())
        assert report.approved is True

    def test_zero_capital_skips_loss_check(self):
        cfg = make_config(daily_loss_limit_pct=5.0)
        engine = RiskEngine(cfg, capital=0.0, daily_pnl=-99999.0, open_position_count=0)
        report = engine.validate(make_proposal())
        # With zero capital we can't compute %, so loss check is skipped
        assert report.approved is True


class TestRiskReport:
    def test_risk_report_fields_populated(self):
        cfg = make_config(max_capital_pct=10.0)
        engine = RiskEngine(cfg, capital=1_000_000.0, daily_pnl=0.0, open_position_count=0)
        report = engine.validate(make_proposal(quantity=10, entry_price=2850.0, stop_loss=2800.0))
        assert report.risk_amount == 500.0
        assert abs(report.risk_pct - 0.05) < 0.01
        assert report.approved is True
        assert report.message != ""

    def test_multiple_violations_all_listed(self):
        cfg = make_config(require_stop_loss=True, max_open_positions=0)
        engine = RiskEngine(cfg, capital=1_000_000.0, daily_pnl=0.0, open_position_count=0)
        proposal = TradeProposalCreate(
            symbol="TCS", exchange="NSE", direction="BUY",
            quantity=1, stop_loss=None, rationale="test"
        )
        report = engine.validate(proposal)
        assert report.approved is False
        assert len(report.violations) >= 2  # stop loss + max positions

    def test_exposure_summary_not_halted(self):
        cfg = make_config(daily_loss_limit_pct=5.0)
        engine = RiskEngine(cfg, capital=1_000_000.0, daily_pnl=0.0, open_position_count=2)
        summary = engine.check_exposure_summary()
        assert summary["trading_halted"] is False
        assert summary["open_positions"] == 2
        assert summary["daily_loss_pct"] == 0.0

    def test_exposure_summary_halted(self):
        cfg = make_config(daily_loss_limit_pct=5.0)
        engine = RiskEngine(cfg, capital=1_000_000.0, daily_pnl=-55_000.0, open_position_count=0)
        summary = engine.check_exposure_summary()
        assert summary["trading_halted"] is True
        assert summary["daily_loss_pct"] >= 5.0
