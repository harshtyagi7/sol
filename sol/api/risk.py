"""Risk configuration and exposure endpoints."""

from fastapi import APIRouter, HTTPException

from sol.schemas.risk import RiskConfigOut, RiskConfigUpdate

router = APIRouter(prefix="/api/risk", tags=["risk"])


@router.get("/config")
async def get_risk_config():
    from sol.database import get_session
    from sol.models.risk_config import RiskConfig
    from sqlalchemy import select

    async with get_session() as db:
        result = await db.execute(select(RiskConfig).where(RiskConfig.is_active == True).limit(1))
        cfg = result.scalar_one_or_none()
        if not cfg:
            raise HTTPException(status_code=404, detail="No active risk config found")
        return RiskConfigOut.model_validate(cfg)


@router.put("/config")
async def update_risk_config(data: RiskConfigUpdate):
    from sol.database import get_session
    from sol.models.risk_config import RiskConfig
    from sqlalchemy import select

    async with get_session() as db:
        result = await db.execute(select(RiskConfig).where(RiskConfig.is_active == True).limit(1))
        cfg = result.scalar_one_or_none()
        if not cfg:
            cfg = RiskConfig()
            db.add(cfg)

        cfg.max_capital_pct = data.max_capital_pct
        cfg.daily_loss_limit_pct = data.daily_loss_limit_pct
        cfg.max_open_positions = data.max_open_positions
        cfg.max_position_size_pct = data.max_position_size_pct
        cfg.require_stop_loss = data.require_stop_loss
        await db.flush()
        return RiskConfigOut.model_validate(cfg)


@router.get("/report")
async def risk_exposure_report():
    from sol.services.risk_service import get_risk_service
    svc = get_risk_service()
    return await svc.get_exposure_report()
