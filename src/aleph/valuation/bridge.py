"""Assemble DCFInputs from derived assumptions. Deterministic, no LLM.

Two consistency rules are enforced here because the engine cannot see them:

  1. Numerator and denominator must match. Cash flow from operations is stated
     AFTER interest paid, so it is a levered figure. Discounting it at WACC and
     then subtracting net debt charges for the debt twice. FCFF is therefore
     reconstructed explicitly: CFO + interest x (1 - tax) - capex.

  2. Units are converted once, from the declared unit on each range, never
     inferred from magnitude. A rate of 0.21 and a rate of 21.0 are both
     plausible-looking numbers and mean different things.
"""
from dataclasses import dataclass

from ..schemas.valuation import AssumptionRange, MarketAssumption


class BridgeError(ValueError):
    """Raised when inputs cannot be assembled without violating a rule."""


@dataclass
class Bridged:
    inputs: object            # DCFInputs, imported lazily to keep layers apart
    tornado_ranges: dict
    notes: list[str]


def as_decimal(assumption: AssumptionRange, which: str = "base") -> float:
    """Convert a range to a decimal rate using its DECLARED unit."""
    value = getattr(assumption, which)
    if value is None:
        raise BridgeError(f"{assumption.name}: {which} is unset ({assumption.status})")
    if assumption.unit == "percent":
        return value / 100.0
    if assumption.unit in ("decimal", "ratio"):
        return value
    raise BridgeError(
        f"{assumption.name}: unit '{assumption.unit}' cannot be read as a rate"
    )

SCALE_TO_MILLIONS = {
    "USD millions": 1.0,
    "millions": 1.0,
    "thousands": 0.001,
    "USD thousands": 0.001,
    "billions": 1000.0,
}


def to_millions(assumption: AssumptionRange, which: str = "base") -> float:
    """Convert to millions using the DECLARED unit, never inferred from size.

    Cash flow is reported in millions and share counts in thousands. Dividing
    one by the other without conversion yields a per-share value wrong by a
    factor of 1000, with no arithmetic error to detect.
    """
    value = getattr(assumption, which)
    if value is None:
        raise BridgeError(f"{assumption.name}: {which} is unset ({assumption.status})")
    scale = SCALE_TO_MILLIONS.get(assumption.unit)
    if scale is None:
        raise BridgeError(
            f"{assumption.name}: unit '{assumption.unit}' has no known scale; "
            "add it to SCALE_TO_MILLIONS rather than assuming"
        )
    return value * scale

def require(ranges: dict[str, AssumptionRange], name: str) -> AssumptionRange:
    found = ranges.get(name)
    if found is None:
        raise BridgeError(f"missing required assumption '{name}'")
    if found.status == "blocked":
        raise BridgeError(f"'{name}' is blocked: {found.rationale}")
    return found


def fade(start: float, end: float, years: int) -> list[float]:
    """Linear fade from the starting growth rate to the terminal rate.

    The shape is a modelling choice, not a derivation, and is recorded as such.
    A company growing 18 percent does not step to 2.5 percent in one year, and
    holding 18 percent for a decade is the commonest way a DCF manufactures a
    number that looks defensible.
    """
    if years < 2:
        return [start]
    step = (start - end) / (years - 1)
    return [start - step * i for i in range(years)]


def build_dcf_inputs(
    ranges: dict[str, AssumptionRange],
    market: dict[str, MarketAssumption],
    forecast_years: int = 10,
) -> Bridged:
    from dcf_engine import Assumption, DCFInputs  # engine stays independent

    tax = as_decimal(require(ranges, "effective_tax_rate"))
    growth = as_decimal(require(ranges, "revenue_growth"))

    cfo = require(ranges, "operating_cash_flow").base
    capex = abs(require(ranges, "capex").base)
    interest = abs(require(ranges, "interest_expense").base)
    shares_range = require(ranges, "diluted_shares")
    shares = to_millions(shares_range)
    net_debt = require(ranges, "net_debt").base

    # Rule 1: rebuild a firm-level cash flow from a levered starting point.
    fcff = cfo + interest * (1 - tax) - capex

    if "discount_rate" not in market or "terminal_growth" not in market:
        raise BridgeError(
            "discount_rate and terminal_growth are market/judgment inputs and "
            "must be supplied with an as_of date; they are not in the filing"
        )
    discount = market["discount_rate"].value
    terminal = market["terminal_growth"].value

    assumptions = [
        Assumption("base_cash_flow", fcff, "filing",
                   f"FCFF = CFO {cfo:,.0f} + interest {interest:,.0f} x "
                   f"(1 - {tax:.1%}) - capex {capex:,.0f}"),
        Assumption("effective_tax_rate", tax, "analyst_judgment",
                   ranges["effective_tax_rate"].rationale[:150]),
        Assumption("growth_year_1", growth, "filing",
                   ranges["revenue_growth"].rationale[:150]),
        Assumption("terminal_growth", terminal, "analyst_judgment",
                   f"{market['terminal_growth'].rationale} "
                   f"[as of {market['terminal_growth'].as_of}]"),
        Assumption("discount_rate", discount, "market",
                   f"{market['discount_rate'].rationale} "
                   f"[{market['discount_rate'].source}, "
                   f"as of {market['discount_rate'].as_of}]"),
        Assumption("shares_outstanding", shares, "filing",
                   ranges["diluted_shares"].rationale[:150]),
        Assumption("net_debt", net_debt, "filing",
                   ranges["net_debt"].rationale[:150]),
    ]

    inputs = DCFInputs(
        cash_flow_type="FCFF",
        base_cash_flow=fcff,
        growth_rates=fade(growth, terminal, forecast_years),
        terminal_growth=terminal,
        discount_rate=discount,
        net_debt=net_debt,
        shares_outstanding=shares,
        assumptions=assumptions,
    )

    # Tornado bounds come from OBSERVED dispersion, not from bounds chosen by
    # hand. A tornado measures the ranges it is given, so hand-picked bounds
    # decide their own winner before the calculation runs.
    tornado = {}
    growth_range = ranges["revenue_growth"]
    if growth_range.low is not None and growth_range.high is not None:
        span = (growth_range.high - growth_range.low) / 100.0 / 2
        tornado["growth_rates_shift"] = (-span, span)

    cash = ranges["operating_cash_flow"]
    if cash.low is not None and cash.high is not None:
        low_fcff = cash.low + interest * (1 - tax) - capex
        high_fcff = cash.high + interest * (1 - tax) - capex
        tornado["base_cash_flow"] = (low_fcff, high_fcff)

    notes = [
        f"FCFF rebuilt from CFO: {cfo:,.0f} + {interest:,.0f} x (1 - {tax:.1%}) "
        f"- {capex:,.0f} = {fcff:,.0f}",
        f"Growth fades {growth:.1%} -> {terminal:.1%} over {forecast_years} years "
        "(linear; a modelling choice, not a derivation)",
        "discount_rate and terminal_growth are not derivable from the filing",
    ]
    return Bridged(inputs=inputs, tornado_ranges=tornado, notes=notes)
