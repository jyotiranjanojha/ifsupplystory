"""Deterministic KPI engine for BY ESP planning explainability.

This module is intentionally pure Python and contains no LLM calls.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import isfinite
from typing import Any, Dict, List, Sequence


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and isfinite(float(value))


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class KPIResult:
    name: str
    value: float
    unit: str
    formula: str
    business_description: str
    output_validation: Dict[str, Any]
    components: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class KPIInputBundle:
    on_hand_inventory: float
    demand_qty: float
    period_days: float
    cogs: float
    average_inventory: float
    forecast_qty: Sequence[float]
    actual_qty: Sequence[float]
    fulfilled_qty: float
    total_demand_qty: float
    on_time_orders: int
    total_orders: int
    current_safety_stock: float
    target_safety_stock: float
    projected_stockout_periods: int
    total_periods: int
    fulfilled_customer_order_qty: float
    total_customer_order_qty: float
    total_supply_qty: float
    total_demand_analysis_qty: float
    required_capacity: float
    available_capacity: float


class DeterministicKPIEngine:
    """Pure deterministic KPI calculator with explicit validation metadata."""

    @staticmethod
    def _build_validation(
        *,
        value: float,
        range_low: float | None = None,
        range_high: float | None = None,
        denominator_positive: bool = True,
        extra_checks: Dict[str, bool] | None = None,
    ) -> Dict[str, Any]:
        checks = {
            "is_finite": _is_finite_number(value),
            "denominator_positive": bool(denominator_positive),
        }
        if range_low is not None:
            checks["gte_min"] = value >= range_low
        if range_high is not None:
            checks["lte_max"] = value <= range_high
        if extra_checks:
            checks.update(extra_checks)
        is_valid = all(checks.values())
        warnings: List[str] = []
        for k, ok in checks.items():
            if not ok:
                warnings.append(f"Validation check failed: {k}")
        return {
            "is_valid": is_valid,
            "checks": checks,
            "warnings": warnings,
        }

    def inventory_coverage(self, on_hand_inventory: float, demand_qty: float, period_days: float) -> KPIResult:
        """Inventory Coverage (days) = On Hand Inventory / Average Daily Demand."""
        avg_daily_demand = (demand_qty / period_days) if period_days > 0 else 0.0
        denom_ok = avg_daily_demand > 0
        value = (on_hand_inventory / avg_daily_demand) if denom_ok else 0.0
        validation = self._build_validation(
            value=value,
            range_low=0.0,
            denominator_positive=denom_ok,
            extra_checks={"period_days_positive": period_days > 0, "on_hand_non_negative": on_hand_inventory >= 0},
        )
        return KPIResult(
            name="Inventory Coverage",
            value=float(value),
            unit="days",
            formula="on_hand_inventory / (demand_qty / period_days)",
            business_description="Estimated number of days current on-hand inventory can satisfy expected demand.",
            output_validation=validation,
            components={
                "on_hand_inventory": float(on_hand_inventory),
                "demand_qty": float(demand_qty),
                "period_days": float(period_days),
                "average_daily_demand": float(avg_daily_demand),
            },
        )

    def inventory_turns(self, cogs: float, average_inventory: float) -> KPIResult:
        """Inventory Turns = Cost of Goods Sold / Average Inventory."""
        denom_ok = average_inventory > 0
        value = (cogs / average_inventory) if denom_ok else 0.0
        validation = self._build_validation(
            value=value,
            range_low=0.0,
            denominator_positive=denom_ok,
            extra_checks={"cogs_non_negative": cogs >= 0},
        )
        return KPIResult(
            name="Inventory Turns",
            value=float(value),
            unit="turns",
            formula="cogs / average_inventory",
            business_description="How many times inventory is cycled through demand over the period.",
            output_validation=validation,
            components={"cogs": float(cogs), "average_inventory": float(average_inventory)},
        )

    def forecast_accuracy(self, forecast_qty: Sequence[float], actual_qty: Sequence[float]) -> KPIResult:
        """Forecast Accuracy = 1 - WMAPE, where WMAPE = sum(|F-A|)/sum(A)."""
        pairs_ok = len(forecast_qty) == len(actual_qty) and len(actual_qty) > 0
        if not pairs_ok:
            value = 0.0
            wmape = 1.0
            total_abs_actual = 0.0
            total_abs_error = 0.0
        else:
            total_abs_error = 0.0
            total_abs_actual = 0.0
            for f, a in zip(forecast_qty, actual_qty):
                total_abs_error += abs(float(f) - float(a))
                total_abs_actual += abs(float(a))
            if total_abs_actual <= 0:
                wmape = 1.0
            else:
                wmape = total_abs_error / total_abs_actual
            value = _clamp(1.0 - wmape, 0.0, 1.0)

        validation = self._build_validation(
            value=value,
            range_low=0.0,
            range_high=1.0,
            denominator_positive=total_abs_actual > 0,
            extra_checks={"paired_series": pairs_ok},
        )
        return KPIResult(
            name="Forecast Accuracy",
            value=float(value),
            unit="ratio",
            formula="1 - (sum(abs(forecast-actual)) / sum(abs(actual)))",
            business_description="Measures forecast closeness to actual demand using weighted absolute percentage error.",
            output_validation=validation,
            components={
                "sum_abs_error": float(total_abs_error),
                "sum_abs_actual": float(total_abs_actual),
                "wmape": float(wmape),
            },
        )

    def fill_rate(self, fulfilled_qty: float, total_demand_qty: float) -> KPIResult:
        """Fill Rate = Fulfilled Quantity / Total Demand Quantity."""
        denom_ok = total_demand_qty > 0
        value = (fulfilled_qty / total_demand_qty) if denom_ok else 0.0
        value = _clamp(value, 0.0, 1.0)
        validation = self._build_validation(
            value=value,
            range_low=0.0,
            range_high=1.0,
            denominator_positive=denom_ok,
            extra_checks={"fulfilled_non_negative": fulfilled_qty >= 0},
        )
        return KPIResult(
            name="Fill Rate",
            value=float(value),
            unit="ratio",
            formula="fulfilled_qty / total_demand_qty",
            business_description="Portion of demanded quantity fulfilled in the planning horizon.",
            output_validation=validation,
            components={"fulfilled_qty": float(fulfilled_qty), "total_demand_qty": float(total_demand_qty)},
        )

    def service_level(self, on_time_orders: int, total_orders: int) -> KPIResult:
        """Service Level = On-Time Orders / Total Orders."""
        denom_ok = total_orders > 0
        value = (on_time_orders / total_orders) if denom_ok else 0.0
        value = _clamp(value, 0.0, 1.0)
        validation = self._build_validation(
            value=value,
            range_low=0.0,
            range_high=1.0,
            denominator_positive=denom_ok,
            extra_checks={
                "orders_non_negative": on_time_orders >= 0 and total_orders >= 0,
                "on_time_not_exceed_total": on_time_orders <= total_orders if total_orders >= 0 else False,
            },
        )
        return KPIResult(
            name="Service Level",
            value=float(value),
            unit="ratio",
            formula="on_time_orders / total_orders",
            business_description="Fraction of customer orders delivered on or before promised date.",
            output_validation=validation,
            components={"on_time_orders": float(on_time_orders), "total_orders": float(total_orders)},
        )

    def safety_stock_gap(self, current_safety_stock: float, target_safety_stock: float) -> KPIResult:
        """Safety Stock Gap = Target Safety Stock - Current Safety Stock."""
        value = target_safety_stock - current_safety_stock
        validation = self._build_validation(
            value=value,
            denominator_positive=True,
            extra_checks={
                "current_non_negative": current_safety_stock >= 0,
                "target_non_negative": target_safety_stock >= 0,
            },
        )
        return KPIResult(
            name="Safety Stock Gap",
            value=float(value),
            unit="quantity",
            formula="target_safety_stock - current_safety_stock",
            business_description="Positive values indicate additional buffer inventory needed to meet safety stock policy.",
            output_validation=validation,
            components={
                "current_safety_stock": float(current_safety_stock),
                "target_safety_stock": float(target_safety_stock),
            },
        )

    def stockout_risk(self, projected_stockout_periods: int, total_periods: int) -> KPIResult:
        """Stockout Risk = Projected Stockout Periods / Total Periods."""
        denom_ok = total_periods > 0
        value = (projected_stockout_periods / total_periods) if denom_ok else 0.0
        value = _clamp(value, 0.0, 1.0)
        validation = self._build_validation(
            value=value,
            range_low=0.0,
            range_high=1.0,
            denominator_positive=denom_ok,
            extra_checks={
                "periods_non_negative": projected_stockout_periods >= 0 and total_periods >= 0,
                "stockout_periods_not_exceed_total": projected_stockout_periods <= total_periods if total_periods >= 0 else False,
            },
        )
        return KPIResult(
            name="Stockout Risk",
            value=float(value),
            unit="ratio",
            formula="projected_stockout_periods / total_periods",
            business_description="Likelihood proxy of running out of stock across evaluated periods.",
            output_validation=validation,
            components={
                "projected_stockout_periods": float(projected_stockout_periods),
                "total_periods": float(total_periods),
            },
        )

    def customer_order_fulfilment(self, fulfilled_customer_order_qty: float, total_customer_order_qty: float) -> KPIResult:
        """Customer Order Fulfilment = Fulfilled Customer Order Quantity / Total Customer Order Quantity."""
        denom_ok = total_customer_order_qty > 0
        value = (fulfilled_customer_order_qty / total_customer_order_qty) if denom_ok else 0.0
        value = _clamp(value, 0.0, 1.0)
        validation = self._build_validation(
            value=value,
            range_low=0.0,
            range_high=1.0,
            denominator_positive=denom_ok,
            extra_checks={"fulfilled_non_negative": fulfilled_customer_order_qty >= 0},
        )
        return KPIResult(
            name="Customer Order Fulfilment",
            value=float(value),
            unit="ratio",
            formula="fulfilled_customer_order_qty / total_customer_order_qty",
            business_description="Share of customer order quantity fulfilled in the requested horizon.",
            output_validation=validation,
            components={
                "fulfilled_customer_order_qty": float(fulfilled_customer_order_qty),
                "total_customer_order_qty": float(total_customer_order_qty),
            },
        )

    def demand_supply_analysis(self, total_supply_qty: float, total_demand_analysis_qty: float) -> KPIResult:
        """Demand Supply Analysis = Total Supply Quantity / Total Demand Quantity."""
        denom_ok = total_demand_analysis_qty > 0
        value = (total_supply_qty / total_demand_analysis_qty) if denom_ok else 0.0
        validation = self._build_validation(
            value=value,
            range_low=0.0,
            denominator_positive=denom_ok,
            extra_checks={"supply_non_negative": total_supply_qty >= 0},
        )
        return KPIResult(
            name="Demand Supply Analysis",
            value=float(value),
            unit="ratio",
            formula="total_supply_qty / total_demand_analysis_qty",
            business_description="Balance ratio between available supply and demand; values below 1 indicate shortage pressure.",
            output_validation=validation,
            components={
                "total_supply_qty": float(total_supply_qty),
                "total_demand_analysis_qty": float(total_demand_analysis_qty),
                "demand_supply_gap_qty": float(total_supply_qty - total_demand_analysis_qty),
            },
        )

    def capacity_constraint(self, required_capacity: float, available_capacity: float) -> KPIResult:
        """Capacity Constraint = max((Required Capacity - Available Capacity)/Available Capacity, 0)."""
        denom_ok = available_capacity > 0
        overload = (required_capacity - available_capacity)
        value = (max(overload, 0.0) / available_capacity) if denom_ok else 0.0
        validation = self._build_validation(
            value=value,
            range_low=0.0,
            denominator_positive=denom_ok,
            extra_checks={
                "required_non_negative": required_capacity >= 0,
                "available_non_negative": available_capacity >= 0,
            },
        )
        return KPIResult(
            name="Capacity Constraint",
            value=float(value),
            unit="ratio",
            formula="max((required_capacity - available_capacity), 0) / available_capacity",
            business_description="Relative overload against available capacity; zero means no overload.",
            output_validation=validation,
            components={
                "required_capacity": float(required_capacity),
                "available_capacity": float(available_capacity),
                "overload_qty": float(max(overload, 0.0)),
                "utilization_ratio": float((required_capacity / available_capacity) if denom_ok else 0.0),
            },
        )

    def compute_all(self, data: KPIInputBundle) -> Dict[str, KPIResult]:
        """Compute all supported KPIs in one deterministic pass."""
        return {
            "Inventory Coverage": self.inventory_coverage(data.on_hand_inventory, data.demand_qty, data.period_days),
            "Inventory Turns": self.inventory_turns(data.cogs, data.average_inventory),
            "Forecast Accuracy": self.forecast_accuracy(data.forecast_qty, data.actual_qty),
            "Fill Rate": self.fill_rate(data.fulfilled_qty, data.total_demand_qty),
            "Service Level": self.service_level(data.on_time_orders, data.total_orders),
            "Safety Stock Gap": self.safety_stock_gap(data.current_safety_stock, data.target_safety_stock),
            "Stockout Risk": self.stockout_risk(data.projected_stockout_periods, data.total_periods),
            "Customer Order Fulfilment": self.customer_order_fulfilment(
                data.fulfilled_customer_order_qty, data.total_customer_order_qty
            ),
            "Demand Supply Analysis": self.demand_supply_analysis(data.total_supply_qty, data.total_demand_analysis_qty),
            "Capacity Constraint": self.capacity_constraint(data.required_capacity, data.available_capacity),
        }


__all__ = ["KPIResult", "KPIInputBundle", "DeterministicKPIEngine"]
