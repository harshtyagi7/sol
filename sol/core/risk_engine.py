"""
Risk Engine — The safety firewall.
Validates every trade proposal before it reaches the user or gets executed.
Risk limits are NEVER bypassed.
"""

import logging
from typing import Optional

from sol.schemas.trade import RiskReport, TradeProposalCreate
from sol.utils.market_hours import is_market_open

logger = logging.getLogger(__name__)


class RiskEngine:
    """
    All validation checks run in order. Any blocking violation prevents approval.
    Non-blocking violations (like quantity reduction) modify the proposal.
    """

    def __init__(self, risk_config, capital: float, daily_pnl: float, open_position_count: int):
        self.cfg = risk_config  # RiskConfig ORM model
        self.capital = float(capital)
        self.daily_pnl = float(daily_pnl)
        self.open_position_count = int(open_position_count)
        # Cast DB Decimal fields to float/int so arithmetic never raises TypeError
        self.cfg.daily_loss_limit_pct = float(risk_config.daily_loss_limit_pct)
        self.cfg.max_capital_pct = float(risk_config.max_capital_pct)
        self.cfg.max_position_size_pct = float(risk_config.max_position_size_pct)
        self.cfg.max_open_positions = int(risk_config.max_open_positions)

    def validate(self, proposal: "TradeProposalCreate") -> RiskReport:
        violations: list[str] = []
        modified_quantity: Optional[int] = None
        risk_amount = 0.0
        risk_pct = 0.0

        # 1. Market hours check
        if not is_market_open():
            violations.append("Market is currently closed. Cannot place orders.")
            return RiskReport(
                approved=False,
                violations=violations,
                message="Market closed",
            )

        # 2. Daily loss limit check
        if self.capital > 0:
            daily_loss_pct = abs(min(0.0, self.daily_pnl)) / self.capital * 100
            if daily_loss_pct >= self.cfg.daily_loss_limit_pct:
                violations.append(
                    f"Daily loss limit reached: {daily_loss_pct:.1f}% >= {self.cfg.daily_loss_limit_pct}%. "
                    "Trading halted for today."
                )
                return RiskReport(
                    approved=False,
                    violations=violations,
                    message="Daily loss limit hit",
                )

        # 3. Stop-loss required
        if self.cfg.require_stop_loss and proposal.stop_loss is None:
            violations.append("Stop-loss is required but not provided.")

        # 4. Max open positions
        if self.open_position_count >= self.cfg.max_open_positions:
            violations.append(
                f"Max open positions reached: {self.open_position_count}/{self.cfg.max_open_positions}"
            )

        # 5. Compute risk amount
        # For F&O options/futures, quantity = number of lots.
        # Risk and notional must be scaled by lot_size so the limits mean the same thing.
        entry = float(proposal.entry_price) if proposal.entry_price is not None else None
        sl = float(proposal.stop_loss) if proposal.stop_loss is not None else None
        qty = proposal.quantity

        # Resolve lot size: 1 for equity, actual lot size for F&O
        lot_size = 1
        is_fno = (
            getattr(proposal, "exchange", None) == "NFO"
            or getattr(proposal, "option_type", None) in ("CE", "PE", "FUT")
            or getattr(proposal, "product_type", None) == "NRML"
        )
        if is_fno:
            from sol.services.option_chain_service import DEFAULT_LOT_SIZES
            sym = proposal.symbol.upper()
            for nfo_name, lot in DEFAULT_LOT_SIZES.items():
                if sym.startswith(nfo_name):
                    lot_size = lot
                    break
            if lot_size == 1:
                lot_size = 75  # safe fallback — NIFTY default

        effective_qty = qty * lot_size  # actual units for risk calculation

        if entry and sl and qty:
            per_unit_risk = abs(entry - sl)
            risk_amount = per_unit_risk * effective_qty
            if self.capital > 0:
                risk_pct = risk_amount / self.capital * 100

        # 6. Max risk per trade check (enforced in lot units for F&O)
        if self.capital > 0 and risk_pct > self.cfg.max_capital_pct:
            if entry and sl:
                per_unit_risk = abs(entry - sl)
                per_lot_risk = per_unit_risk * lot_size
                if per_lot_risk > 0:
                    max_risk_amount = self.capital * self.cfg.max_capital_pct / 100
                    allowed_lots = int(max_risk_amount / per_lot_risk)
                    if allowed_lots < 1:
                        # For very small accounts: allow qty=1 if total risk ≤ full capital
                        # (better to trade 1 share than block entirely)
                        if per_lot_risk <= self.capital:
                            modified_quantity = 1
                            risk_amount = per_lot_risk
                            risk_pct = risk_amount / self.capital * 100
                            logger.info(f"Small capital: allowing qty=1, risk ₹{risk_amount:.0f}")
                        else:
                            violations.append(
                                f"Risk per trade exceeds limit ({risk_pct:.1f}% > {self.cfg.max_capital_pct}%) "
                                f"and cannot be reduced to acceptable quantity."
                            )
                    else:
                        modified_quantity = allowed_lots
                        risk_amount = per_lot_risk * allowed_lots
                        risk_pct = risk_amount / self.capital * 100
                        logger.info(
                            f"Quantity reduced from {qty} to {allowed_lots} lot(s) to meet risk limit"
                        )

        # 7. Max position size check
        if entry and qty and self.capital > 0:
            actual_qty = modified_quantity or qty
            position_value = entry * (actual_qty * lot_size)
            position_pct = position_value / self.capital * 100
            if position_pct > self.cfg.max_position_size_pct:
                max_lots = int(self.capital * self.cfg.max_position_size_pct / 100 / (entry * lot_size))
                if max_lots < 1:
                    # For small accounts: allow qty=1 if notional ≤ full capital
                    if entry * lot_size <= self.capital:
                        if modified_quantity is None or 1 < modified_quantity:
                            modified_quantity = 1
                            logger.info(f"Small capital: allowing qty=1, notional ₹{entry * lot_size:.0f}")
                    else:
                        violations.append(
                            f"Position size too large: {position_pct:.1f}% > {self.cfg.max_position_size_pct}%"
                        )
                else:
                    if modified_quantity is None or max_lots < modified_quantity:
                        modified_quantity = max_lots

        has_blocking_violation = len(violations) > 0
        approved = not has_blocking_violation

        if approved:
            msg = "Risk checks passed."
            if modified_quantity and modified_quantity != qty:
                msg += f" Quantity adjusted from {qty} to {modified_quantity}."
        else:
            msg = "; ".join(violations)

        return RiskReport(
            approved=approved,
            violations=violations,
            risk_amount=round(risk_amount, 2),
            risk_pct=round(risk_pct, 2),
            modified_quantity=modified_quantity,
            message=msg,
        )

    def check_exposure_summary(self) -> dict:
        """Returns a summary of current risk exposure."""
        daily_loss_pct = abs(min(0.0, self.daily_pnl)) / self.capital * 100 if self.capital else 0
        return {
            "capital": self.capital,
            "daily_pnl": self.daily_pnl,
            "daily_loss_pct": round(daily_loss_pct, 2),
            "daily_loss_limit_pct": self.cfg.daily_loss_limit_pct,
            "open_positions": self.open_position_count,
            "max_open_positions": self.cfg.max_open_positions,
            "trading_halted": daily_loss_pct >= self.cfg.daily_loss_limit_pct,
        }
