from pydantic import BaseModel, Field


class RiskConfigUpdate(BaseModel):
    max_capital_pct: float = Field(default=2.0, ge=0.1, le=100.0)
    daily_loss_limit_pct: float = Field(default=5.0, ge=0.1, le=100.0)
    max_open_positions: int = Field(default=5, ge=1, le=50)
    max_position_size_pct: float = Field(default=10.0, ge=1.0, le=100.0)
    require_stop_loss: bool = True


class RiskConfigOut(BaseModel):
    id: str
    max_capital_pct: float
    daily_loss_limit_pct: float
    max_open_positions: int
    max_position_size_pct: float
    require_stop_loss: bool
    is_active: bool

    model_config = {"from_attributes": True}


class RiskExposureReport(BaseModel):
    total_capital: float
    available_capital: float
    invested_capital: float
    exposure_pct: float
    daily_pnl: float
    daily_pnl_pct: float
    daily_loss_limit_pct: float
    open_positions: int
    max_open_positions: int
    trading_halted: bool
    halt_reason: str = ""
