from typing import Literal, Optional

from pydantic import BaseModel


class AgentCreate(BaseModel):
    name: str
    llm_provider: Literal["anthropic", "openai", "google"]
    model_id: str
    strategy_prompt: str = ""
    paper_only: bool = False
    virtual_capital: float = 1_000_000.0
    config_json: dict = {}


class AgentUpdate(BaseModel):
    strategy_prompt: Optional[str] = None
    is_active: Optional[bool] = None
    paper_only: Optional[bool] = None
    config_json: Optional[dict] = None


class AgentOut(BaseModel):
    id: str
    name: str
    llm_provider: str
    model_id: str
    is_active: bool
    paper_only: bool
    virtual_capital: float
    config_json: dict

    model_config = {"from_attributes": True}


class AgentPerformance(BaseModel):
    agent_id: str
    agent_name: str
    virtual_capital: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    total_pnl: float
    win_rate: float
    avg_pnl_per_trade: float
    open_positions: int
