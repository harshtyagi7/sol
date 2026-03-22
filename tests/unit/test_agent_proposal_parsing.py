"""Unit tests for agent proposal parsing (no LLM calls)."""

import pytest
from sol.agents.claude_agent import ClaudeAgent
from sol.agents.gpt_agent import GPTAgent
from sol.agents.gemini_agent import GeminiAgent
from sol.agents.base_agent import MarketDataSnapshot


def make_agent(cls, name="test-agent"):
    return cls("agent-001", name, cls.__name__.lower(), virtual_capital=1_000_000.0)


VALID_PROPOSAL_DATA = [
    {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "direction": "BUY",
        "order_type": "MARKET",
        "product_type": "MIS",
        "quantity": 10,
        "entry_price": 2850.0,
        "stop_loss": 2800.0,
        "take_profit": 2950.0,
        "rationale": "Breakout above resistance",
    }
]


class TestClaudeAgentParsing:
    def test_parse_valid_proposal(self):
        agent = make_agent(ClaudeAgent)
        results = agent._parse_proposals(VALID_PROPOSAL_DATA)
        assert len(results) == 1
        p = results[0]
        assert p.symbol == "RELIANCE"
        assert p.direction == "BUY"
        assert p.quantity == 10
        assert p.stop_loss == 2800.0

    def test_parse_symbol_uppercased(self):
        agent = make_agent(ClaudeAgent)
        results = agent._parse_proposals([{**VALID_PROPOSAL_DATA[0], "symbol": "reliance"}])
        assert results[0].symbol == "RELIANCE"

    def test_parse_missing_required_field_skipped(self):
        agent = make_agent(ClaudeAgent)
        bad_data = [{"symbol": "INFY", "direction": "BUY"}]  # missing quantity and rationale
        results = agent._parse_proposals(bad_data)
        assert results == []

    def test_parse_invalid_direction_skipped(self):
        agent = make_agent(ClaudeAgent)
        bad_data = [{**VALID_PROPOSAL_DATA[0], "direction": "HOLD"}]
        results = agent._parse_proposals(bad_data)
        assert results == []

    def test_parse_multiple_proposals(self):
        agent = make_agent(ClaudeAgent)
        data = [
            VALID_PROPOSAL_DATA[0],
            {**VALID_PROPOSAL_DATA[0], "symbol": "INFY", "direction": "SELL"},
        ]
        results = agent._parse_proposals(data)
        assert len(results) == 2

    def test_parse_empty_list(self):
        agent = make_agent(ClaudeAgent)
        assert agent._parse_proposals([]) == []

    def test_parse_optional_fields_default(self):
        agent = make_agent(ClaudeAgent)
        minimal = [{"symbol": "TCS", "exchange": "NSE", "direction": "BUY",
                    "quantity": 5, "stop_loss": 4100.0, "rationale": "test"}]
        results = agent._parse_proposals(minimal)
        assert len(results) == 1
        assert results[0].entry_price is None
        assert results[0].take_profit is None
        assert results[0].order_type == "MARKET"

    def test_parse_quantity_coerced_to_int(self):
        agent = make_agent(ClaudeAgent)
        data = [{**VALID_PROPOSAL_DATA[0], "quantity": "10"}]  # string input
        results = agent._parse_proposals(data)
        assert results[0].quantity == 10
        assert isinstance(results[0].quantity, int)

    def test_parse_mixed_valid_invalid(self):
        agent = make_agent(ClaudeAgent)
        data = [
            VALID_PROPOSAL_DATA[0],
            {"bad": "data"},  # will be skipped
            {**VALID_PROPOSAL_DATA[0], "symbol": "TCS"},
        ]
        results = agent._parse_proposals(data)
        assert len(results) == 2


class TestGPTAgentParsing:
    def test_parse_valid_proposal(self):
        agent = make_agent(GPTAgent)
        results = agent._parse_proposals(VALID_PROPOSAL_DATA)
        assert len(results) == 1
        assert results[0].symbol == "RELIANCE"

    def test_parse_empty(self):
        agent = make_agent(GPTAgent)
        assert agent._parse_proposals([]) == []


class TestGeminiAgentParsing:
    def test_parse_valid_proposal(self):
        agent = make_agent(GeminiAgent)
        results = agent._parse_proposals(VALID_PROPOSAL_DATA)
        assert len(results) == 1

    def test_parse_empty(self):
        agent = make_agent(GeminiAgent)
        assert agent._parse_proposals([]) == []


class TestMarketContextBuilder:
    def test_context_includes_symbol(self):
        agent = make_agent(ClaudeAgent)
        snap = MarketDataSnapshot(
            symbol="RELIANCE", exchange="NSE", current_price=2850.0,
            ohlcv_daily=[], ohlcv_15min=[],
        )
        context = agent._build_market_context([snap], [])
        assert "RELIANCE" in context
        assert "2850.0" in context

    def test_context_includes_open_positions(self):
        agent = make_agent(ClaudeAgent)
        snap = MarketDataSnapshot("TCS", "NSE", 4200.0, [], [])
        positions = [{"symbol": "INFY", "direction": "BUY", "quantity": 5,
                      "avg_price": 1750.0, "stop_loss": 1700.0, "unrealized_pnl": 250.0}]
        context = agent._build_market_context([snap], positions)
        assert "INFY" in context
        assert "Open Positions" in context

    def test_context_empty_positions(self):
        agent = make_agent(ClaudeAgent)
        snap = MarketDataSnapshot("TCS", "NSE", 4200.0, [], [])
        context = agent._build_market_context([snap], [])
        assert "Open Positions" not in context

    def test_context_includes_indicators(self):
        agent = make_agent(ClaudeAgent)
        snap = MarketDataSnapshot(
            "HDFC", "NSE", 1680.0, [], [],
            indicators={"rsi_14": 62.5, "sma_20": 1650.0}
        )
        context = agent._build_market_context([snap], [])
        assert "rsi_14" in context or "62.5" in context

    def test_context_includes_ohlcv_data(self):
        agent = make_agent(ClaudeAgent)
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
