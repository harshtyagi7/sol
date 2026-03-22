"""Unit tests for Pydantic schema validation."""

import pytest
from pydantic import ValidationError
from sol.schemas.trade import TradeProposalCreate, TradeReviewAction, RiskReport
from sol.schemas.risk import RiskConfigUpdate
from sol.schemas.agent import AgentCreate
from sol.schemas.strategy import StrategyProposal, StrategyTradeIn, StrategyApproval


class TestTradeProposalCreate:
    def test_valid_buy_proposal(self):
        p = TradeProposalCreate(
            symbol="RELIANCE",
            exchange="NSE",
            direction="BUY",
            quantity=10,
            entry_price=2850.0,
            stop_loss=2800.0,
            take_profit=2950.0,
            rationale="Strong breakout",
        )
        assert p.symbol == "RELIANCE"
        assert p.direction == "BUY"
        assert p.quantity == 10

    def test_valid_sell_proposal(self):
        p = TradeProposalCreate(
            symbol="INFY",
            exchange="NSE",
            direction="SELL",
            quantity=5,
            stop_loss=1800.0,
            rationale="Breakdown below support",
        )
        assert p.direction == "SELL"

    def test_invalid_direction_rejected(self):
        with pytest.raises(ValidationError):
            TradeProposalCreate(
                symbol="RELIANCE",
                exchange="NSE",
                direction="HOLD",  # invalid
                quantity=10,
                rationale="test",
            )

    def test_invalid_exchange_rejected(self):
        with pytest.raises(ValidationError):
            TradeProposalCreate(
                symbol="RELIANCE",
                exchange="MCX",  # invalid
                direction="BUY",
                quantity=10,
                rationale="test",
            )

    def test_zero_quantity_rejected(self):
        with pytest.raises(ValidationError):
            TradeProposalCreate(
                symbol="RELIANCE",
                exchange="NSE",
                direction="BUY",
                quantity=0,  # invalid: must be > 0
                rationale="test",
            )

    def test_negative_quantity_rejected(self):
        with pytest.raises(ValidationError):
            TradeProposalCreate(
                symbol="RELIANCE",
                exchange="NSE",
                direction="BUY",
                quantity=-5,
                rationale="test",
            )

    def test_optional_fields_default_to_none(self):
        p = TradeProposalCreate(
            symbol="TCS",
            exchange="NSE",
            direction="BUY",
            quantity=1,
            rationale="test",
        )
        assert p.entry_price is None
        assert p.stop_loss is None
        assert p.take_profit is None

    def test_default_order_type_is_market(self):
        p = TradeProposalCreate(
            symbol="TCS", exchange="NSE", direction="BUY", quantity=1, rationale="test"
        )
        assert p.order_type == "MARKET"

    def test_default_product_type_is_mis(self):
        p = TradeProposalCreate(
            symbol="TCS", exchange="NSE", direction="BUY", quantity=1, rationale="test"
        )
        assert p.product_type == "MIS"

    def test_cnc_product_type_allowed(self):
        p = TradeProposalCreate(
            symbol="TCS", exchange="NSE", direction="BUY",
            quantity=1, product_type="CNC", rationale="test"
        )
        assert p.product_type == "CNC"


class TestTradeReviewAction:
    def test_approve_action(self):
        a = TradeReviewAction(action="approve")
        assert a.action == "approve"
        assert a.note is None

    def test_reject_with_note(self):
        a = TradeReviewAction(action="reject", note="Not the right time")
        assert a.action == "reject"
        assert a.note == "Not the right time"

    def test_modify_with_fields(self):
        a = TradeReviewAction(action="modify", quantity=5, stop_loss=2790.0)
        assert a.action == "modify"
        assert a.quantity == 5
        assert a.stop_loss == 2790.0

    def test_invalid_action_rejected(self):
        with pytest.raises(ValidationError):
            TradeReviewAction(action="execute")  # invalid


class TestRiskReport:
    def test_approved_report(self):
        r = RiskReport(approved=True, risk_amount=500.0, risk_pct=0.05, message="OK")
        assert r.approved is True
        assert r.violations == []

    def test_rejected_report_with_violations(self):
        r = RiskReport(
            approved=False,
            violations=["Daily loss limit reached", "No stop loss"],
            message="Blocked",
        )
        assert r.approved is False
        assert len(r.violations) == 2

    def test_defaults(self):
        r = RiskReport(approved=True)
        assert r.risk_amount == 0.0
        assert r.risk_pct == 0.0
        assert r.modified_quantity is None
        assert r.message == ""


class TestRiskConfigUpdate:
    def test_valid_config(self):
        c = RiskConfigUpdate(
            max_capital_pct=3.0,
            daily_loss_limit_pct=8.0,
            max_open_positions=7,
            max_position_size_pct=15.0,
        )
        assert c.max_capital_pct == 3.0

    def test_max_capital_pct_below_minimum_rejected(self):
        with pytest.raises(ValidationError):
            RiskConfigUpdate(max_capital_pct=0.0)  # must be >= 0.1

    def test_max_capital_pct_above_maximum_rejected(self):
        with pytest.raises(ValidationError):
            RiskConfigUpdate(max_capital_pct=101.0)  # must be <= 100

    def test_max_open_positions_below_minimum_rejected(self):
        with pytest.raises(ValidationError):
            RiskConfigUpdate(max_open_positions=0)  # must be >= 1


class TestAgentCreate:
    def test_valid_anthropic_agent(self):
        a = AgentCreate(
            name="alpha",
            llm_provider="anthropic",
            model_id="claude-sonnet-4-6",
        )
        assert a.llm_provider == "anthropic"
        assert a.paper_only is False
        assert a.virtual_capital == 1_000_000.0

    def test_invalid_provider_rejected(self):
        with pytest.raises(ValidationError):
            AgentCreate(
                name="alpha",
                llm_provider="mistral",  # not allowed
                model_id="some-model",
            )

    def test_paper_only_flag(self):
        a = AgentCreate(
            name="safe-agent",
            llm_provider="openai",
            model_id="gpt-4o",
            paper_only=True,
        )
        assert a.paper_only is True


def make_trade_in(**kwargs):
    defaults = dict(
        sequence=1, symbol="RELIANCE", exchange="NSE",
        direction="BUY", quantity=10,
        entry_price=2850.0, stop_loss=2800.0, take_profit=2950.0,
        rationale="Test rationale",
    )
    defaults.update(kwargs)
    return StrategyTradeIn(**defaults)


class TestStrategyTradeIn:
    def test_valid_trade_in(self):
        t = make_trade_in()
        assert t.symbol == "RELIANCE"
        assert t.sequence == 1

    def test_sequence_must_be_positive(self):
        with pytest.raises(ValidationError):
            make_trade_in(sequence=0)

    def test_invalid_direction_rejected(self):
        with pytest.raises(ValidationError):
            make_trade_in(direction="HOLD")

    def test_zero_quantity_rejected(self):
        with pytest.raises(ValidationError):
            make_trade_in(quantity=0)

    def test_default_order_type_market(self):
        t = make_trade_in()
        assert t.order_type == "MARKET"

    def test_default_product_type_mis(self):
        t = make_trade_in()
        assert t.product_type == "MIS"


class TestStrategyProposal:
    def _make_proposal(self, trades=None):
        if trades is None:
            trades = [make_trade_in()]
        return StrategyProposal(
            name="Test Strategy",
            description="Description",
            rationale="Rationale",
            duration_days=2,
            trades=trades,
        )

    def test_valid_proposal(self):
        p = self._make_proposal()
        assert p.name == "Test Strategy"
        assert len(p.trades) == 1

    def test_max_loss_possible_single_trade(self):
        # |2850 - 2800| * 10 = 500
        p = self._make_proposal()
        assert abs(p.max_loss_possible - 500.0) < 0.01

    def test_max_loss_possible_multi_trade(self):
        trades = [
            make_trade_in(sequence=1, entry_price=2850.0, stop_loss=2800.0, quantity=10),
            make_trade_in(sequence=2, symbol="INFY", direction="SELL",
                          entry_price=1800.0, stop_loss=1850.0, quantity=5),
        ]
        p = self._make_proposal(trades=trades)
        # Trade 1: 50*10=500, Trade 2: 50*5=250 → total 750
        assert abs(p.max_loss_possible - 750.0) < 0.01

    def test_max_loss_possible_no_sl_is_zero(self):
        trades = [make_trade_in(stop_loss=None, entry_price=None)]
        p = self._make_proposal(trades=trades)
        assert p.max_loss_possible == 0.0

    def test_duration_days_must_be_positive(self):
        with pytest.raises(ValidationError):
            StrategyProposal(
                name="X", description="d", rationale="r",
                duration_days=0, trades=[make_trade_in()]
            )

    def test_duration_days_max_30(self):
        with pytest.raises(ValidationError):
            StrategyProposal(
                name="X", description="d", rationale="r",
                duration_days=31, trades=[make_trade_in()]
            )


class TestStrategyApproval:
    def test_valid_approval(self):
        a = StrategyApproval(max_loss_approved=1000.0)
        assert a.max_loss_approved == 1000.0
        assert a.note is None

    def test_approval_with_note(self):
        a = StrategyApproval(max_loss_approved=500.0, note="Looks good")
        assert a.note == "Looks good"

    def test_zero_max_loss_rejected(self):
        with pytest.raises(ValidationError):
            StrategyApproval(max_loss_approved=0.0)

    def test_negative_max_loss_rejected(self):
        with pytest.raises(ValidationError):
            StrategyApproval(max_loss_approved=-100.0)
