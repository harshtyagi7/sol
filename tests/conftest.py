"""Shared pytest fixtures."""

import pytest
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime
import pytz

IST = pytz.timezone("Asia/Kolkata")


def make_risk_config(
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


def make_proposal_orm(
    id="test-id-001",
    agent_id="agent-001",
    agent_name="test-agent",
    symbol="RELIANCE",
    exchange="NSE",
    direction="BUY",
    order_type="MARKET",
    product_type="MIS",
    quantity=10,
    entry_price=2850.0,
    stop_loss=2800.0,
    take_profit=2950.0,
    rationale="Test rationale",
    status="PENDING",
    is_virtual=True,
):
    p = MagicMock()
    p.id = id
    p.agent_id = agent_id
    p.agent_name = agent_name
    p.symbol = symbol
    p.exchange = exchange
    p.direction = direction
    p.order_type = order_type
    p.product_type = product_type
    p.quantity = quantity
    p.entry_price = entry_price
    p.stop_loss = stop_loss
    p.take_profit = take_profit
    p.rationale = rationale
    p.status = status
    p.is_virtual = is_virtual
    return p


def make_position_orm(
    id="pos-001",
    proposal_id="test-id-001",
    agent_id="agent-001",
    agent_name="test-agent",
    symbol="RELIANCE",
    exchange="NSE",
    direction="BUY",
    product_type="MIS",
    quantity=10,
    avg_price=2850.0,
    current_price=2900.0,
    stop_loss=2800.0,
    take_profit=2950.0,
    status="OPEN",
    is_virtual=True,
):
    p = MagicMock()
    p.id = id
    p.proposal_id = proposal_id
    p.agent_id = agent_id
    p.agent_name = agent_name
    p.symbol = symbol
    p.exchange = exchange
    p.direction = direction
    p.product_type = product_type
    p.quantity = quantity
    p.avg_price = avg_price
    p.current_price = current_price
    p.stop_loss = stop_loss
    p.take_profit = take_profit
    p.status = status
    p.is_virtual = is_virtual
    # Simulate the unrealized_pnl property
    mult = 1 if direction == "BUY" else -1
    p.unrealized_pnl = mult * (current_price - avg_price) * quantity
    return p
