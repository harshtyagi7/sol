"""Unit tests for agent strategy parsing (no LLM calls)."""

import pytest
from sol.agents.claude_agent import ClaudeAgent
from sol.agents.gpt_agent import GPTAgent
from sol.agents.gemini_agent import GeminiAgent
from sol.agents.base_agent import MarketDataSnapshot
from sol.schemas.strategy import StrategyProposal


def make_claude(name="test-agent"):
    return ClaudeAgent("agent-001", name, "claude-sonnet-4-6", virtual_capital=1_000_000.0)


def make_gpt(name="test-agent"):
    return GPTAgent("agent-002", name, "gpt-4o", virtual_capital=1_000_000.0)


def make_gemini(name="test-agent"):
    return GeminiAgent("agent-003", name, "gemini-1.5-pro", virtual_capital=1_000_000.0)


VALID_STRATEGY_DATA = {
    "name": "RELIANCE Breakout",
    "description": "Riding a breakout above key resistance",
    "rationale": "Volume surge + RSI breakout above 60",
    "duration_days": 2,
    "trades": [
        {
            "sequence": 1,
            "symbol": "reliance",  # should be uppercased
            "exchange": "NSE",
            "direction": "BUY",
            "order_type": "MARKET",
            "product_type": "CNC",
            "quantity": 10,
            "entry_price": 2850.0,
            "stop_loss": 2800.0,
            "take_profit": 2950.0,
            "rationale": "Entry on breakout candle close",
        }
    ],
}


class TestClaudeAgentStrategyParsing:
    def test_parse_valid_strategy(self):
        agent = make_claude()
        result = agent._parse_strategy(VALID_STRATEGY_DATA)
        assert result is not None
        assert isinstance(result, StrategyProposal)
        assert result.name == "RELIANCE Breakout"
        assert len(result.trades) == 1

    def test_parse_symbol_uppercased(self):
        agent = make_claude()
        result = agent._parse_strategy(VALID_STRATEGY_DATA)
        assert result.trades[0].symbol == "RELIANCE"

    def test_parse_multi_trade_strategy(self):
        agent = make_claude()
        data = {
            **VALID_STRATEGY_DATA,
            "trades": [
                {**VALID_STRATEGY_DATA["trades"][0], "sequence": 1},
                {
                    "sequence": 2,
                    "symbol": "INFY",
                    "exchange": "NSE",
                    "direction": "SELL",
                    "order_type": "LIMIT",
                    "product_type": "MIS",
                    "quantity": 5,
                    "entry_price": 1800.0,
                    "stop_loss": 1850.0,
                    "take_profit": 1750.0,
                    "rationale": "Hedge on IT sector weakness",
                },
            ],
        }
        result = agent._parse_strategy(data)
        assert result is not None
        assert len(result.trades) == 2
        assert result.trades[1].symbol == "INFY"

    def test_parse_empty_trades_returns_none(self):
        agent = make_claude()
        data = {**VALID_STRATEGY_DATA, "trades": []}
        result = agent._parse_strategy(data)
        assert result is None

    def test_parse_missing_name_returns_none(self):
        agent = make_claude()
        bad = {k: v for k, v in VALID_STRATEGY_DATA.items() if k != "name"}
        result = agent._parse_strategy(bad)
        assert result is None

    def test_parse_invalid_direction_returns_none(self):
        agent = make_claude()
        bad_trade = {**VALID_STRATEGY_DATA["trades"][0], "direction": "HOLD"}
        data = {**VALID_STRATEGY_DATA, "trades": [bad_trade]}
        result = agent._parse_strategy(data)
        assert result is None

    def test_parse_duration_days_defaults_to_1(self):
        agent = make_claude()
        data = {k: v for k, v in VALID_STRATEGY_DATA.items() if k != "duration_days"}
        result = agent._parse_strategy(data)
        assert result is not None
        assert result.duration_days == 1

    def test_max_loss_possible_computed(self):
        agent = make_claude()
        result = agent._parse_strategy(VALID_STRATEGY_DATA)
        # entry=2850, SL=2800, qty=10 → risk = 50*10 = 500
        assert result is not None
        assert abs(result.max_loss_possible - 500.0) < 0.01

    def test_quantity_coerced_to_int(self):
        agent = make_claude()
        trade = {**VALID_STRATEGY_DATA["trades"][0], "quantity": "10"}
        data = {**VALID_STRATEGY_DATA, "trades": [trade]}
        result = agent._parse_strategy(data)
        assert result is not None
        assert isinstance(result.trades[0].quantity, int)


class TestGPTAgentStrategyParsing:
    def test_parse_valid_strategy(self):
        agent = make_gpt()
        result = agent._parse_strategy(VALID_STRATEGY_DATA)
        assert result is not None
        assert result.name == "RELIANCE Breakout"

    def test_parse_empty_trades_returns_none(self):
        agent = make_gpt()
        result = agent._parse_strategy({**VALID_STRATEGY_DATA, "trades": []})
        assert result is None

    def test_parse_symbol_uppercased(self):
        agent = make_gpt()
        result = agent._parse_strategy(VALID_STRATEGY_DATA)
        assert result.trades[0].symbol == "RELIANCE"

    def test_parse_missing_required_field_returns_none(self):
        agent = make_gpt()
        bad = {k: v for k, v in VALID_STRATEGY_DATA.items() if k != "description"}
        result = agent._parse_strategy(bad)
        assert result is None


class TestGeminiAgentStrategyParsing:
    def test_parse_valid_strategy(self):
        agent = make_gemini()
        result = agent._parse_strategy(VALID_STRATEGY_DATA)
        assert result is not None
        assert len(result.trades) == 1

    def test_parse_empty_trades_returns_none(self):
        agent = make_gemini()
        result = agent._parse_strategy({**VALID_STRATEGY_DATA, "trades": []})
        assert result is None

    def test_parse_symbol_uppercased(self):
        agent = make_gemini()
        result = agent._parse_strategy(VALID_STRATEGY_DATA)
        assert result.trades[0].symbol == "RELIANCE"


class TestMarketContextBuilder:
    def test_context_includes_symbol(self):
        agent = make_claude()
        snap = MarketDataSnapshot(
            symbol="RELIANCE", exchange="NSE", current_price=2850.0,
            ohlcv_daily=[], ohlcv_15min=[],
        )
        context = agent._build_market_context([snap], [])
        assert "RELIANCE" in context
        assert "2850.0" in context

    def test_context_includes_open_positions(self):
        agent = make_claude()
        snap = MarketDataSnapshot("TCS", "NSE", 4200.0, [], [])
        positions = [{"symbol": "INFY", "direction": "BUY", "quantity": 5,
                      "avg_price": 1750.0, "stop_loss": 1700.0, "unrealized_pnl": 250.0}]
        context = agent._build_market_context([snap], positions)
        assert "INFY" in context
        assert "Open Positions" in context or "Active Positions" in context

    def test_context_empty_positions(self):
        agent = make_claude()
        snap = MarketDataSnapshot("TCS", "NSE", 4200.0, [], [])
        context = agent._build_market_context([snap], [])
        assert "INFY" not in context

    def test_context_includes_indicators(self):
        agent = make_claude()
        snap = MarketDataSnapshot(
            "HDFC", "NSE", 1680.0, [], [],
            indicators={"rsi_14": 62.5, "sma_20": 1650.0}
        )
        context = agent._build_market_context([snap], [])
        assert "rsi_14" in context or "62.5" in context

    def test_context_includes_ohlcv_data(self):
        agent = make_claude()
        snap = MarketDataSnapshot(
            "SBIN", "NSE", 820.0,
            ohlcv_daily=[
                {"date": "2025-01-06", "open": 815.0, "high": 825.0,
                 "low": 810.0, "close": 820.0, "volume": 1_000_000}
            ],
            ohlcv_15min=[],
        )
        context = agent._build_market_context([snap], [])
        assert "815.0" in context or "825.0" in context

    def test_context_includes_multiple_symbols(self):
        agent = make_claude()
        snaps = [
            MarketDataSnapshot("RELIANCE", "NSE", 2850.0, [], []),
            MarketDataSnapshot("INFY", "NSE", 1800.0, [], []),
        ]
        context = agent._build_market_context(snaps, [])
        assert "RELIANCE" in context
        assert "INFY" in context
