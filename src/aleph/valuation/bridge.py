"""Assemble DCFInputs from derived assumptions. Deterministic, no LLM.

Three consistency rules are enforced here because the engine cannot see them:

  1. Numerator and denominator must match. Cash flow from operations is stated
     AFTER interest paid, so it is a levered figure. Discounting it at WACC and
     then subtracting net debt charges for the debt twice. FCFF is therefore
     reconstructed explicitly: CFO + interest x (1 - tax) - capex.

  2. Units are converted once, from the DECLARED unit on each range, never
     inferred from magnitude. Cash flow is reported in millions and share
     counts in thousands; dividing one by the other unconverted yields a
     per-share value wrong by a factor of 1000 with no arithmetic error to
     detect.

  3. A placeholder discount rate blocks the run. It is the largest single
     driver of the result, so a run on an invented rate produces a number that
     looks like a valuation and is not.
"""
from dataclasses import dataclass

from ..schemas.valuation import AssumptionRange, MarketAssumption

# Scale is matched on tokens, not on an exact string. The unit is free text
# chosen by the model, so "thousands", "USD thousands" and "thousands of
# shares" all describe the same scale and an exact-match table breaks on the
# first phrasing it has not seen.
SCALE_TOKENS = (
    ("billion", 1000.0),
    ("million", 1.0),
    ("thousand", 0.001),
)

PLACEHOLDER_SOURCES = ("placeholder", "todo", "tbd")


class BridgeError(ValueError):
    """Raised when inputs cannot be assembled without violating a rule."""


@dataclass
class Bridged:
    inputs: object            # DCFInputs, imported lazily to keep layers apart
    tornado_ranges: dict
    notes: list[str]


def require(ranges: dict[str, AssumptionRange], name: str) -> AssumptionRange:
    found = ranges.get(name)
    if found is None:
        raise BridgeError(f"missing required assumption '{name}'")
    if found.status == "blocked":
        raise BridgeError(f"'{name}' is blocked: {found.rationale}")
    return found


def as_decimal(assumption: AssumptionRange, which: str = "base") -> float:
    """Convert a range to a decimal rate using its DECLARED unit."""
    value = getattr(assumption, which)
    if value is None:
        raise BridgeError(f"{assumption.name}: {which} is unset ({assumption.status})")
    unit = assumption.unit.lower()
    if "percent" in unit or unit.strip() == "%":
        return value / 100.0
    if unit in ("decimal", "ratio"):
        return value
    raise BridgeError(
        f"{assumption.name}: unit '{assumption.unit}' cannot be read as a rate"
    )


def to_millions(assumption: AssumptionRange, which: str = "base") -> float:
    """Convert to millions using the DECLARED unit, never inferred from size."""
    value = getattr(assumption, which)
    if value is None:
        raise BridgeError(f"{assumption.name}: {which} is unset ({assumption.status})")

    unit = assumption.unit.lower()
    matches = [scale for token, scale in SCALE_TOKENS if token in unit]
    if len(matches) != 1:
        raise BridgeError(
            f"{assumption.name}: unit '{assumption.unit}' names "
            f"{len(matches)} known scales; cannot convert without guessing"
        )
    return value * matches[0]


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


def _market(market: dict[str, MarketAssumption], name: str) -> MarketAssumption:
    found = market.get(name)
    if found is None:
        raise BridgeError(
            f"'{name}' is a market or judgment input and is not derivable from "
            "the filing; supply it with an as_of date in data/market.json"
        )
    if found.source.strip().lower() in PLACEHOLDER_SOURCES:
        raise BridgeError(
            f"'{name}' is marked as a placeholder. Change source to something "
            "truthful only once the value is real, or to 'integration test' to "
            "acknowledge that the output is not a valuation."
        )
    return found


def build_dcf_inputs(
    ranges: dict[str, AssumptionRange],
    market: dict[str, MarketAssumption],
    forecast_years: int = 10,
) -> Bridged:
    from dcf_engine import Assumption, DCFInputs  # engine stays independent

    tax = as_decimal(require(ranges, "effective_tax_rate"))
    growth = as_decimal(require(ranges, "revenue_growth"))

    cfo = to_millions(require(ranges, "operating_cash_flow"))
    capex = abs(to_millions(require(ranges, "capex")))
    interest = abs(to_millions(require(ranges, "interest_expense")))
    shares = to_millions(require(ranges, "diluted_shares"))
    net_debt = to_millions(require(ranges, "net_debt"))

    # Rule 1: rebuild a firm-level cash flow from a levered starting point.
    fcff = cfo + interest * (1 - tax) - capex

    discount_input = _market(market, "discount_rate")
    terminal_input = _market(market, "terminal_growth")
    discount = discount_input.value
    terminal = terminal_input.value

    assumptions = [
        Assumption("base_cash_flow", fcff, "filing",
                   f"FCFF = CFO {cfo:,.0f} + interest {interest:,.0f} x "
                   f"(1 - {tax:.1%}) - capex {capex:,.0f}"),
        Assumption("effective_tax_rate", tax, "analyst_judgment",
                   ranges["effective_tax_rate"].rationale[:150]),
        Assumption("growth_year_1", growth, "filing",
                   ranges["revenue_growth"].rationale[:150]),
        Assumption("terminal_growth", terminal, "analyst_judgment",
                   f"{terminal_input.rationale} [as of {terminal_input.as_of}]"),
        Assumption("discount_rate", discount, "market",
                   f"{discount_input.rationale} "
                   f"[{discount_input.source}, as of {discount_input.as_of}]"),
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

    # A tornado measures the ranges it is given, so every driver must be present
    # and every bound must mean something. A parameter left out is reported as
    # irrelevant by omission, and a zero-width bound is reported as having no
    # effect at all - both look like findings and are artefacts.
    tornado: dict[str, tuple[float, float]] = {}

    growth_range = ranges["revenue_growth"]
    if growth_range.low is not None and growth_range.high is not None:
        span = (growth_range.high - growth_range.low) / 100.0 / 2
        if span:
            tornado["growth_rates_shift"] = (-span, span)

    # Level quantities carry no historical band by construction, so a bound for
    # cash flow must come from the volatile component rather than from prior
    # years of the level itself.
    capex_scale = to_millions(ranges["capex"]) / (ranges["capex"].base or 1.0)
    capex_values = [abs(o.value) * capex_scale for o in ranges["capex"].observations]
    if capex_values and max(capex_values) != min(capex_values):
        tornado["base_cash_flow"] = (
            cfo + interest * (1 - tax) - max(capex_values),
            cfo + interest * (1 - tax) - min(capex_values),
        )

    # The discount rate dominated the tornado in ch09 and must never be absent.
    # Bounds are declared judgment, not derivation: plus or minus 200bp around
    # the stated rate, and the terminal band stops below the engine's 3% guard.
    tornado["discount_rate"] = (discount - 0.02, discount + 0.02)
    tornado["terminal_growth"] = (
        max(0.0, terminal - 0.01), min(0.029, terminal + 0.005)
    )

    notes = [
        f"FCFF rebuilt from CFO: {cfo:,.0f} + {interest:,.0f} x (1 - {tax:.1%}) "
        f"- {capex:,.0f} = {fcff:,.0f}",
        f"Growth fades {growth:.1%} -> {terminal:.1%} over {forecast_years} years "
        "(linear; a modelling choice, not a derivation)",
        f"discount_rate {discount:.2%} from {discount_input.source} "
        f"as of {discount_input.as_of}; not derivable from the filing",
        "Tornado bounds for discount_rate and terminal_growth are declared "
        "judgment; the others come from observed dispersion",
    ]
    return Bridged(inputs=inputs, tornado_ranges=tornado, notes=notes)