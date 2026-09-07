"""Assemble DCFInputs from derived assumptions. Deterministic, no LLM.

Four consistency rules are enforced here because the engine cannot see them:

  1. Numerator and denominator must match. Cash flow from operations is stated
     AFTER interest paid, so it is a levered figure. Discounting it at WACC and
     then subtracting net debt charges for the debt twice. FCFF is therefore
     reconstructed explicitly: CFO + interest x (1 - tax) - capex - SBC.

  2. Units are converted once, from the DECLARED unit on each range, never
     inferred from magnitude. Cash flow is reported in millions and share
     counts in thousands; dividing one by the other unconverted yields a
     per-share value wrong by a factor of 1000 with no arithmetic error to
     detect.

  3. A placeholder discount rate blocks the run. It is a large driver of the
     result, so a run on an invented rate produces a number that looks like a
     valuation and is not.

     The discount rate is DERIVED, by build_wacc, and written into the market
     dict by the caller. data/market.json therefore carries no discount_rate
     key at all: when WACC cannot be built, the absence of the key is what
     stops the run here. Measured before this was true (ISSUES.md #19): with
     a discount_rate present, a failed build_wacc fell through to it and
     valued UBER_FY2024 at $73.54/share on a 0.09 rate whose own rationale
     read "NOT A VALUATION INPUT", behind a single warning line above a full
     result block.

  4. Stock-based compensation is a cash cost, not an accounting add-back to
     ignore. CFO already adds SBC back to net income, so it silently counts
     as free cash flow unless removed. Subtracted here at full value - it is
     already tax-affected inside net income, so no further (1 - tax)
     adjustment applies. The share count is held flat, deliberately:
     subtracting SBC from cash flow AND modelling the dilution it funds
     would double-count the same cost.
"""
from dataclasses import dataclass

from ..infra.units import matching_scales, resolve_scale
from ..schemas.valuation import AssumptionRange, MarketAssumption

# "integration test" is here because it was the one that got through: four
# market.json blocks carried a 0.09 discount_rate under that source, and
# _market's own error message named it as the string to use to bypass this
# check. A guard that advertises its own escape hatch is not a guard.
PLACEHOLDER_SOURCES = ("placeholder", "todo", "tbd", "integration test")


class BridgeError(ValueError):
    """Raised when inputs cannot be assembled without violating a rule."""


@dataclass
class Bridged:
    inputs: object            # DCFInputs, imported lazily to keep layers apart
    tornado_ranges: dict
    notes: list[str]
    # Structured form of the base_cash_flow bound, for callers that need the
    # period labels rather than just the two numbers already in
    # tornado_ranges - the RESULT block prints "range across FY2023-FY2025",
    # not just two figures, and a string is not something to re-parse for it.
    # {"available": True, "low_period", "low_fcff", "high_period",
    # "high_fcff", "note"} on success; {"available": False, "reason"} when
    # the multi-year bound could not be reconstructed at all.
    base_cash_flow_bound: dict = None


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

    matches = matching_scales(assumption.unit)
    if len(matches) != 1:
        raise BridgeError(
            f"{assumption.name}: unit '{assumption.unit}' names "
            f"{len(matches)} known scales; cannot convert without guessing"
        )
    return value * matches[0][1]


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
        if name == "discount_rate":
            # Telling the reader to add this to market.json is what caused
            # #19. It is derived, never authored: the caller writes it in
            # after build_wacc succeeds, so its absence means WACC failed.
            raise BridgeError(
                "'discount_rate' is DERIVED by build_wacc, not authored. Its "
                "absence means WACC could not be built - fix the missing WACC "
                "input it named. Do NOT add a discount_rate to data/market.json: "
                "a hand-written one silently values the filing off an invented "
                "rate (ISSUES.md #19)."
            )
        raise BridgeError(
            f"'{name}' is a market or judgment input and is not derivable from "
            "the filing; supply it with an as_of date in data/market.json"
        )
    if found.source.strip().lower() in PLACEHOLDER_SOURCES:
        raise BridgeError(
            f"'{name}' is marked as a placeholder (source: '{found.source}'). "
            "Give it a real source, with an as_of date and a rationale, in "
            "data/market.json. There is no source string that lets a "
            "placeholder through - naming one here is what let an "
            "'integration test' discount rate value four filings (ISSUES.md #19)."
        )
    return found


def _per_period_fcff(
    ranges: dict[str, AssumptionRange], tax: float
) -> tuple[dict[str, float] | None, str]:
    """Reconstruct FCFF for every period the filing discloses, not the
    latest one alone - see ISSUES.md #29. Each observation is converted
    through its OWN declared unit via resolve_scale, the same mechanism
    that converts the AssumptionRange itself - a raw, unconverted value
    produced a nonsense five-figure Lyft result once already, by hand,
    while measuring the numbers that led to this function.

    interest_expense with no observations at all - an override built from
    no disclosed per-period figure, e.g. a filer with no gross interest
    expense line - is applied as that flat value to every period, and the
    substitution is named in the returned note so it is never mistaken for
    measured data.

    Returns (fcff_by_period, note) with fcff_by_period non-None on success;
    note is "" unless a substitution was made. Returns (None, reason) when
    fewer than two periods reconcile across all four quantities - never a
    silent fallback to a narrower bound.
    """
    def periods_millions(name: str) -> dict[str, float]:
        result = {}
        for o in ranges[name].observations:
            scale = resolve_scale(o.unit)
            if scale is not None:
                result[o.period] = o.value * scale
        return result

    cfo_p = periods_millions("operating_cash_flow")
    capex_p = periods_millions("capex")
    sbc_p = periods_millions("stock_based_compensation")
    interest_p = periods_millions("interest_expense")

    note = ""
    if not interest_p:
        interest_range = ranges["interest_expense"]
        if interest_range.base is None:
            return None, (
                f"interest_expense is {interest_range.status} with no "
                f"per-period observations and no fixed value to fall back "
                f"to; a multi-year bound needs at least one"
            )
        flat_interest = abs(to_millions(interest_range))
        common = set(cfo_p) & set(capex_p) & set(sbc_p)
        interest_p = {p: flat_interest for p in common}
        note = (
            f"interest_expense has no per-period disclosure; the flat "
            f"override value ({flat_interest:,.0f}) was applied to every "
            f"period tested, not measured data"
        )

    periods = sorted(set(cfo_p) & set(capex_p) & set(sbc_p) & set(interest_p))
    if len(periods) < 2:
        return None, (
            f"only {len(periods)} period(s) reconcile across CFO, interest, "
            f"capex and SBC; a bound needs at least two"
        )

    fcff_by_period = {
        p: cfo_p[p] + abs(interest_p[p]) * (1 - tax) - abs(capex_p[p]) - abs(sbc_p[p])
        for p in periods
    }
    return fcff_by_period, note


def build_dcf_inputs(
    ranges: dict[str, AssumptionRange],
    market: dict[str, MarketAssumption],
    forecast_years: int = 10,
) -> Bridged:
    # Imported here rather than at module scope to keep the import graph
    # acyclic: dcf_engine is a leaf and must not pull the bridge back in.
    from aleph.valuation.dcf_engine import Assumption, DCFInputs

    tax = as_decimal(require(ranges, "effective_tax_rate"))
    growth = as_decimal(require(ranges, "revenue_growth"))

    cfo = to_millions(require(ranges, "operating_cash_flow"))
    capex = abs(to_millions(require(ranges, "capex")))
    interest = abs(to_millions(require(ranges, "interest_expense")))
    sbc = abs(to_millions(require(ranges, "stock_based_compensation")))
    shares = to_millions(require(ranges, "diluted_shares"))
    net_debt = to_millions(require(ranges, "net_debt"))

    # Rule 1 + Rule 4: rebuild a firm-level cash flow from a levered starting
    # point, then remove the cash cost CFO's own reconciliation added back.
    fcff = cfo + interest * (1 - tax) - capex - sbc

    discount_input = _market(market, "discount_rate")
    terminal_input = _market(market, "terminal_growth")
    discount = discount_input.value
    terminal = terminal_input.value

    assumptions = [
        Assumption("base_cash_flow", fcff, "filing",
                   f"FCFF = CFO {cfo:,.0f} + interest {interest:,.0f} x "
                   f"(1 - {tax:.1%}) - capex {capex:,.0f} - SBC {sbc:,.0f}"),
        Assumption("effective_tax_rate", tax, "analyst_judgment",
                   ranges["effective_tax_rate"].rationale[:150]),
        Assumption("growth_year_1", growth, "filing",
                   ranges["revenue_growth"].rationale[:150]),
        Assumption("terminal_growth", terminal, "analyst_judgment",
                   f"{terminal_input.rationale} [as of {terminal_input.as_of}]"),
        Assumption("discount_rate", discount, "market",
                   f"{discount_input.rationale} "
                   f"[{discount_input.source}, as of {discount_input.as_of}]"),
        Assumption("stock_based_compensation", sbc, "filing",
                   "Subtracted from FCFF at full value; already tax-affected "
                   "inside net income, so no (1 - tax) adjustment applies. "
                   "Share count is held flat, deliberately: subtracting SBC "
                   "and also modelling the dilution it funds would "
                   "double-count the same cost."),
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

    # Level quantities carry no historical band by construction. The bound
    # for cash flow comes from years the filing itself discloses, not from
    # capex dispersion alone, which does not carry the risk that made this
    # necessary - see ISSUES.md #29: the same company, same market price,
    # same day, valued 56% differently one filing apart, because CFO
    # inherits one year's deferred-tax and unrealized-investment swings in
    # full. base_cash_flow's BASE stays the latest period, unchanged - that
    # is the most current information and is not in question; only the
    # BOUND now reflects the years on record. A negative low bound is a
    # real result when a disclosed year's CFO was itself negative, and is
    # reported as such, not clamped - confirmed separately that run_dcf has
    # no guard on base_cash_flow's sign, so nothing downstream rejects it.
    fcff_by_period, fcff_note = _per_period_fcff(ranges, tax)
    if fcff_by_period is None:
        base_cash_flow_bound_note = f"base_cash_flow multi-year bound unavailable: {fcff_note}"
        base_cash_flow_bound = {"available": False, "reason": fcff_note}
    else:
        low_period = min(fcff_by_period, key=fcff_by_period.get)
        high_period = max(fcff_by_period, key=fcff_by_period.get)
        tornado["base_cash_flow"] = (fcff_by_period[low_period], fcff_by_period[high_period])
        detail = "; ".join(f"{p}={v:,.0f}" for p, v in sorted(fcff_by_period.items()))
        base_cash_flow_bound_note = (
            f"base_cash_flow bound from FCFF by period ({detail}): low "
            f"{low_period}={fcff_by_period[low_period]:,.0f}, high "
            f"{high_period}={fcff_by_period[high_period]:,.0f}"
            + (f". {fcff_note}" if fcff_note else "")
        )
        base_cash_flow_bound = {
            "available": True,
            # The whole series, not only its ends. The min/max pair bounds
            # the tornado; historical_fcff.py needs every period to report
            # what each starting-point METHOD implies, and recomputing it
            # there would be a second FCFF definition able to disagree
            # with this one.
            "fcff_by_period": dict(fcff_by_period),
            "low_period": low_period, "low_fcff": fcff_by_period[low_period],
            "high_period": high_period, "high_fcff": fcff_by_period[high_period],
            "note": fcff_note,
        }

    # The discount rate dominated the tornado in ch09 and must never be absent.
    # Bounds are declared judgment, not derivation: plus or minus 200bp around
    # the stated rate, and the terminal band stops below the engine's 3% guard.
    tornado["discount_rate"] = (discount - 0.02, discount + 0.02)
    tornado["terminal_growth"] = (
        max(0.0, terminal - 0.01), min(0.029, terminal + 0.005)
    )

    notes = [
        f"FCFF rebuilt from CFO: {cfo:,.0f} + {interest:,.0f} x (1 - {tax:.1%}) "
        f"- {capex:,.0f} - {sbc:,.0f} (SBC, subtracted at full value, no tax "
        f"adjustment - already tax-affected inside net income) = {fcff:,.0f}",
        f"Share count held flat at {shares:,.0f} despite the SBC subtraction "
        "above: modelling dilution as well would double-count the same cost",
        base_cash_flow_bound_note,
        f"Growth fades {growth:.1%} -> {terminal:.1%} over {forecast_years} years "
        "(linear; a modelling choice, not a derivation)",
        f"discount_rate {discount:.2%} from {discount_input.source} "
        f"as of {discount_input.as_of}; not derivable from the filing",
        "Tornado bounds for discount_rate and terminal_growth are declared "
        "judgment; the others come from observed dispersion",
    ]
    return Bridged(inputs=inputs, tornado_ranges=tornado, notes=notes,
                   base_cash_flow_bound=base_cash_flow_bound)
