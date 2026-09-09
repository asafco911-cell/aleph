"""P9 - DRIVER-BASED DCF. EXPERIMENTAL.

Consumes an OperatingForecast (revenue -> margin -> WC -> capex -> FCFF) and
feeds the EXISTING pure DCF mathematics (dcf_engine.run_dcf) - it changes
the economics ENTERING the DCF, not the DCF math. It never modifies the live
DCFInputs, WACC, terminal growth, or the live point value, and it never
reads a market price.

The forecast gives an explicit FCFF path fcff_1..fcff_n. run_dcf takes a
base cash flow plus a growth vector, so the path is expressed as
base = fcff_0 and growth_rates[k] = fcff_k / fcff_{k-1} - 1. This is exact
for a strictly-positive path. A path that is non-positive anywhere cannot be
represented as multiplicative growth -> NOT_REPRESENTABLE (honest, not a
fabricated number).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from .dcf_engine import DCFConsistencyError, DCFInputs, run_dcf
from .operating_model import ForecastSupport, OperatingForecast

__all__ = ["DriverDCFStatus", "DriverDCFResult", "driver_based_dcf"]


class DriverDCFStatus(str, Enum):
    OK = "OK"
    NOT_REPRESENTABLE = "NOT_REPRESENTABLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True)
class DriverDCFResult:
    doc_id: str
    scenario: str
    status: DriverDCFStatus
    value_per_share: float | None
    base_fcff: float | None
    forecast_fcff: tuple[float, ...]
    implied_growth_path: tuple[float, ...]
    enterprise_value: float | None
    equity_value: float | None
    forecast_support: str
    note: str


def driver_based_dcf(forecast: OperatingForecast, *, discount_rate: float,
                     terminal_growth: float, net_debt: float,
                     shares_outstanding: float) -> DriverDCFResult:
    doc_id, sc = forecast.doc_id, forecast.scenario.value
    if forecast.support is ForecastSupport.INSUFFICIENT_EVIDENCE \
            or forecast.base_fcff is None or not forecast.years:
        return DriverDCFResult(
            doc_id, sc, DriverDCFStatus.INSUFFICIENT_EVIDENCE, None, None, (), (),
            None, None, forecast.support.value,
            "the operating forecast is INSUFFICIENT_EVIDENCE; no driver DCF")

    fcffs = [y.fcff for y in forecast.years]
    base = forecast.base_fcff
    if base is None or base <= 0 or any(f is None or f <= 0 for f in fcffs):
        return DriverDCFResult(
            doc_id, sc, DriverDCFStatus.NOT_REPRESENTABLE, None, base,
            tuple(f for f in fcffs if f is not None), (), None, None,
            forecast.support.value,
            "the forecast FCFF path is non-positive somewhere; it cannot be "
            "expressed as multiplicative growth for run_dcf - no value is "
            "fabricated")

    prev, growth = base, []
    for f in fcffs:
        growth.append(f / prev - 1.0)
        prev = f
    try:
        inp = DCFInputs(
            cash_flow_type="FCFF", base_cash_flow=base, growth_rates=growth,
            terminal_growth=terminal_growth, discount_rate=discount_rate,
            net_debt=net_debt, shares_outstanding=shares_outstanding,
            assumptions=[])
        res = run_dcf(inp)
    except DCFConsistencyError as exc:
        return DriverDCFResult(
            doc_id, sc, DriverDCFStatus.NOT_REPRESENTABLE, None, base,
            tuple(fcffs), tuple(growth), None, None, forecast.support.value,
            f"run_dcf rejected the driver path: {exc}")
    if not math.isfinite(res.value_per_share):
        return DriverDCFResult(
            doc_id, sc, DriverDCFStatus.NOT_REPRESENTABLE, None, base,
            tuple(fcffs), tuple(growth), None, None, forecast.support.value,
            "run_dcf produced a non-finite value")
    return DriverDCFResult(
        doc_id, sc, DriverDCFStatus.OK, res.value_per_share, base,
        tuple(fcffs), tuple(growth), res.enterprise_or_equity_value,
        res.equity_value, forecast.support.value,
        "driver economics fed into the existing DCF mathematics; nothing in "
        "the live model changed")
