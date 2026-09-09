"""P7 - INVESTOR DECISION LAYER: MARKET-IMPLIED EXPECTATIONS.

STATUS: EXPERIMENTAL - NOT WIRED INTO THE BASE DCF. Analytical interpretation
only. It reads a finished ValuationRun and the P6 sustainable-FCFF layer,
re-runs the PURE engine on COPIES, and NEVER writes back. Promotion to LIVE
requires an ADR (ISSUES.md #33, P7).

THE QUESTION. A valuation is not just a number; it is a set of expectations
about future economics. This layer answers: given today's market price, what
future outcome must occur for the CURRENT valuation framework to justify
that price, and how demanding is that outcome relative to the company's own
historical evidence and the current DCF?

IT IS NOT a valuation engine, a rating model, or a BUY/SELL signal. It emits
no numeric confidence score. It reuses the existing reverse-DCF mathematics
(a uniform-growth solve) and adds ONE new closed-form solve - the base FCFF
that equates the DCF price to the market price with the FADED growth path
held fixed.

ANTI-CIRCULARITY (Phase 17). The market price flows in and analytical
outputs flow out. Nothing here modifies inputs, the run, or any valuation
number. A regression test proves the point value is byte-identical with this
layer present.
"""
from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum

from .dcf_engine import (
    DCFConsistencyError,
    DCFInputs,
    REVERSE_DCF_HIGH,
    REVERSE_DCF_LOW,
    reverse_dcf,
    run_dcf,
)

__all__ = [
    "Solvability",
    "ExpectationsVsEvidence",
    "ExpectationsLevel",
    "ImpliedQuantity",
    "AnchorScenarioExpectation",
    "SensitivityRow",
    "ExpectationsGap",
    "MarketExpectations",
    "implied_uniform_growth",
    "implied_base_fcff",
    "anchor_scenarios",
    "wacc_sensitivity",
    "terminal_growth_sensitivity",
    "assess_market_expectations",
    "LEVEL_DEMANDING_RATIO",
    "LEVEL_EXTREME_RATIO",
    "ALIGNED_TOLERANCE_FRAC",
    "REVERSE_DCF_TOLERANCE",
]

# --------------------------------------------------------------------------- #
# thresholds - explicit, documented, comparison-based. They gate a
# categorical label, never a number, and never the base DCF.
# --------------------------------------------------------------------------- #
# The implied-growth solve reuses dcf_engine.reverse_dcf; this tolerance is
# its relative convergence tolerance, surfaced for provenance.
REVERSE_DCF_TOLERANCE = 0.001

# "ALIGNED" means the market-implied base FCFF sits inside the P6 sustainable
# range, give or take this fraction of the range's own width. Rationale: the
# sustainable range is already a wide LOW-HIGH band of explicit
# interpretations; a market price within a small margin of it is consistent
# with SOME defensible reading, which is all "ALIGNED" claims.
ALIGNED_TOLERANCE_FRAC = 0.05

# How far the market-implied base FCFF must exceed the top of the evidence-
# supported range before the expectation is "DEMANDING" / "EXTREME".
# Rationale: within the range and above CENTRAL is already demanding; 1.5x
# the range top is a bet the evidence cannot speak to at all.
LEVEL_DEMANDING_RATIO = 1.00     # implied above CENTRAL (inside the range)
LEVEL_EXTREME_RATIO = 1.50       # implied above 1.5x the range HIGH


class Solvability(str, Enum):
    SOLVED = "SOLVED"
    NOT_SOLVABLE = "NOT_SOLVABLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class ExpectationsVsEvidence(str, Enum):
    MARKET_EXPECTATIONS_BELOW_EVIDENCE = "MARKET_EXPECTATIONS_BELOW_EVIDENCE"
    MARKET_EXPECTATIONS_ALIGNED = "MARKET_EXPECTATIONS_ALIGNED"
    MARKET_EXPECTATIONS_ABOVE_EVIDENCE = "MARKET_EXPECTATIONS_ABOVE_EVIDENCE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class ExpectationsLevel(str, Enum):
    EXPECTATIONS_MODEST = "EXPECTATIONS_MODEST"
    EXPECTATIONS_DEMANDING = "EXPECTATIONS_DEMANDING"
    EXPECTATIONS_EXTREME = "EXPECTATIONS_EXTREME"
    NOT_CLASSIFIED = "NOT_CLASSIFIED"


# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ImpliedQuantity:
    """A quantity solved from the market price, with the full inversion on
    record: the equation, which inputs were held fixed, which variable was
    solved, the search/solution range, solvability, and the tolerance."""
    name: str
    value: float | None
    equation: str
    solved_variable: str
    fixed_inputs: dict
    solution_low: float | None
    solution_high: float | None
    solvability: Solvability
    tolerance: float


@dataclass(frozen=True)
class AnchorScenarioExpectation:
    anchor_label: str                 # "latest" | "sustainable_low" | ...
    anchor_fcff: float | None
    implied_uniform_growth: float | None
    solvability: Solvability
    delta_vs_latest_anchor: float | None   # implied growth diff vs the latest-anchor solve


@dataclass(frozen=True)
class SensitivityRow:
    label: str                        # "low" | "base" | "high"
    param_name: str                   # "discount_rate" | "terminal_growth"
    param_value: float
    implied_uniform_growth: float | None
    solvability: Solvability


@dataclass(frozen=True)
class ExpectationsGap:
    quantity: str
    market_implied: str
    historical_evidence: str
    current_dcf_assumption: str
    sustainable_scenario: str
    direction: str                    # "ABOVE" | "BELOW" | "WITHIN" | "N/A"


@dataclass(frozen=True)
class MarketExpectations:
    doc_id: str
    price: float
    as_of: str
    wacc: float
    terminal_growth: float
    base_fcff: float
    shares: float
    net_debt: float
    forecast_years: int
    forward_dcf_value: float
    implied_uniform_growth: ImpliedQuantity
    implied_base_fcff: ImpliedQuantity
    sustainable_fcff_low: float | None
    sustainable_fcff_central: float | None
    sustainable_fcff_high: float | None
    sustainable_status: str
    evidence_status: str
    applicability: str
    anchor_scenarios: tuple[AnchorScenarioExpectation, ...]
    wacc_sensitivity: tuple[SensitivityRow, ...]
    terminal_growth_sensitivity: tuple[SensitivityRow, ...]
    gaps: tuple[ExpectationsGap, ...]
    vs_evidence: ExpectationsVsEvidence
    level: ExpectationsLevel
    interpretation: str
    notes: tuple[str, ...] = field(default_factory=tuple)


# --------------------------------------------------------------------------- #
# solvers - reuse the engine, never a second implementation
# --------------------------------------------------------------------------- #
def _fixed_inputs(inputs: DCFInputs) -> dict:
    return {
        "discount_rate": inputs.discount_rate,
        "terminal_growth": inputs.terminal_growth,
        "net_debt": inputs.net_debt,
        "shares_outstanding": inputs.shares_outstanding,
        "forecast_years": len(inputs.growth_rates),
        "growth_path": "faded vector (forward DCF)"
        if len(set(inputs.growth_rates)) > 1 else "uniform",
    }


def implied_uniform_growth(inputs: DCFInputs, market_price: float) -> ImpliedQuantity:
    """The UNIFORM annual growth rate that, applied to every forecast year in
    place of the faded vector, makes the forward DCF reproduce the market
    price - holding base FCFF, WACC, terminal growth, net debt and shares
    fixed. This is the existing reverse_dcf; NOT 'the expected growth rate'
    and NOT the inverse of the forward DCF (which uses a faded vector)."""
    fixed = _fixed_inputs(inputs)
    fixed["base_cash_flow"] = inputs.base_cash_flow
    if not math.isfinite(market_price):
        return ImpliedQuantity(
            "implied_uniform_growth", None,
            "run_dcf(growth_rates=[g]*n).value_per_share == market_price, solve g",
            "g (uniform annual growth, all forecast years)", fixed,
            REVERSE_DCF_LOW, REVERSE_DCF_HIGH, Solvability.NOT_SOLVABLE,
            REVERSE_DCF_TOLERANCE)
    g = reverse_dcf(deepcopy(inputs), market_price)
    return ImpliedQuantity(
        "implied_uniform_growth", g,
        "run_dcf(growth_rates=[g]*n).value_per_share == market_price, solve g",
        "g (uniform annual growth, all forecast years)", fixed,
        REVERSE_DCF_LOW, REVERSE_DCF_HIGH,
        Solvability.SOLVED if g is not None else Solvability.NOT_SOLVABLE,
        REVERSE_DCF_TOLERANCE)


def _dcf_multiple(inputs: DCFInputs) -> float | None:
    """Phi = enterprise value / base FCFF for the FIXED faded growth path.
    run_dcf's enterprise value is exactly linear in base_cash_flow with the
    growth path fixed, so Phi is a constant and value/share is
    (B * Phi - net_debt) / shares."""
    try:
        res = run_dcf(deepcopy(inputs))
    except DCFConsistencyError:
        return None
    if inputs.base_cash_flow == 0 or not math.isfinite(res.enterprise_or_equity_value):
        return None
    return res.enterprise_or_equity_value / inputs.base_cash_flow


def implied_base_fcff(inputs: DCFInputs, market_price: float,
                      tolerance: float = 1e-4) -> ImpliedQuantity:
    r"""The base FCFF that makes the forward DCF price equal the market price,
    holding WACC, the FADED growth path, terminal growth, horizon, net debt
    and shares fixed.

    CLOSED FORM, and the inversion is EXACT - not sampled, not iterated.
    In run_dcf, with base FCFF B and the growth path fixed:

        cf_k       = B * prod_{j<=k}(1 + g_j)
        PV_explicit= B * sum_k [prod_{j<=k}(1 + g_j)] / (1 + r)^k
        PV_terminal= B * [prod_all (1 + g_j)] * (1 + g_T) / (r - g_T) / (1 + r)^n
        EV(B)      = B * Phi         Phi depends ONLY on the growth path, r, g_T, n
        value/share(B) = (B * Phi - net_debt) / shares          (FCFF)

    So value/share is EXACTLY AFFINE in B. _dcf_multiple computes Phi from the
    reference run (which succeeded - the ValuationRun has a result), so
    Phi is finite and non-zero, and

        B* = (market_price * shares + net_debt) / Phi

    reproduces the market price to floating-point precision. A re-run at B*
    cannot raise either: the only changed input is base_cash_flow, and every
    validate() guard keyed on it (finite, non-zero) is checked below; every
    other guard is unchanged from the reference run. A verify-by-re-run step
    was therefore provably dead and was removed (cf. P5.1, the reverse_dcf
    guards). NOT_SOLVABLE is still returned when the price is non-finite, Phi
    is undefined/zero (e.g. g_T >= r makes the reference run raise), or B* is
    non-finite/zero.

    Different from reverse_dcf, which solves for a growth rate, not a level.
    """
    fixed = _fixed_inputs(inputs)
    fixed["current_base_fcff"] = inputs.base_cash_flow
    equation = ("value/share(B) = (B * Phi - net_debt) / shares == market_price; "
                "Phi = EV / base_FCFF for the fixed faded growth path; "
                "B* = (market_price * shares + net_debt) / Phi")
    if not math.isfinite(market_price):
        return ImpliedQuantity("implied_base_fcff", None, equation,
                               "B (base FCFF level)", fixed, None, None,
                               Solvability.NOT_SOLVABLE, tolerance)
    phi = _dcf_multiple(inputs)
    if phi is None or phi == 0 or not math.isfinite(phi):
        return ImpliedQuantity("implied_base_fcff", None, equation,
                               "B (base FCFF level)", fixed, None, None,
                               Solvability.NOT_SOLVABLE, tolerance)
    b_star = (market_price * inputs.shares_outstanding + inputs.net_debt) / phi
    if b_star == 0 or not math.isfinite(b_star):
        return ImpliedQuantity("implied_base_fcff", None, equation,
                               "B (base FCFF level)", fixed, None, None,
                               Solvability.NOT_SOLVABLE, tolerance)
    return ImpliedQuantity("implied_base_fcff", b_star, equation,
                           "B (base FCFF level)", fixed, b_star, b_star,
                           Solvability.SOLVED, tolerance)


# --------------------------------------------------------------------------- #
# Phase 4 - implied growth under each FCFF anchor
# --------------------------------------------------------------------------- #
def anchor_scenarios(inputs: DCFInputs, market_price: float,
                     anchors: list[tuple[str, float | None]]
                     ) -> tuple[AnchorScenarioExpectation, ...]:
    """Re-solve the implied UNIFORM growth under each FCFF anchor (latest and
    each sustainable-FCFF case), everything else fixed. No anchor is chosen
    as correct."""
    base_g = reverse_dcf(deepcopy(inputs), market_price) if math.isfinite(market_price) else None
    rows: list[AnchorScenarioExpectation] = []
    for label, fcff in anchors:
        if fcff is None or not math.isfinite(fcff) or fcff == 0:
            rows.append(AnchorScenarioExpectation(label, fcff, None,
                        Solvability.NOT_SOLVABLE, None))
            continue
        trial = deepcopy(inputs)
        trial.base_cash_flow = fcff
        trial.assumptions = []
        g = reverse_dcf(trial, market_price) if math.isfinite(market_price) else None
        delta = (g - base_g) if (g is not None and base_g is not None) else None
        rows.append(AnchorScenarioExpectation(
            label, fcff, g,
            Solvability.SOLVED if g is not None else Solvability.NOT_SOLVABLE,
            delta))
    return tuple(rows)


# --------------------------------------------------------------------------- #
# Phase 12 + 13 - sensitivity of the implied growth to the EXISTING bands
# --------------------------------------------------------------------------- #
def _sensitivity(inputs: DCFInputs, market_price: float, param: str,
                 bounds: tuple[float, float]) -> tuple[SensitivityRow, ...]:
    base_val = getattr(inputs, param)
    rows: list[SensitivityRow] = []
    for label, v in (("low", bounds[0]), ("base", base_val), ("high", bounds[1])):
        trial = deepcopy(inputs)
        setattr(trial, param, v)
        trial.assumptions = []
        try:
            g = reverse_dcf(trial, market_price) if math.isfinite(market_price) else None
        except DCFConsistencyError:
            g = None
        rows.append(SensitivityRow(
            label, param, v, g,
            Solvability.SOLVED if g is not None else Solvability.NOT_SOLVABLE))
    return tuple(rows)


def wacc_sensitivity(inputs, market_price, wacc_bounds):
    """Implied uniform growth at the EXISTING beta-derived WACC bounds. WACC
    itself is never altered - only which of the already-computed bounds is
    used for this analytical solve."""
    return _sensitivity(inputs, market_price, "discount_rate", wacc_bounds)


def terminal_growth_sensitivity(inputs, market_price, tg_bounds):
    """Implied uniform growth at the EXISTING terminal-growth tornado band."""
    return _sensitivity(inputs, market_price, "terminal_growth", tg_bounds)


# --------------------------------------------------------------------------- #
# Phase 8 + 16 - deterministic classification, no score
# --------------------------------------------------------------------------- #
def _classify_vs_evidence(implied_fcff, sust_low, sust_high, sust_status
                          ) -> tuple[ExpectationsVsEvidence, str]:
    if sust_status != "SUPPORTED_RANGE" or implied_fcff is None \
            or sust_low is None or sust_high is None:
        return (ExpectationsVsEvidence.INSUFFICIENT_EVIDENCE,
                "the P6 sustainable-FCFF range is INSUFFICIENT_EVIDENCE, or the "
                "market-implied FCFF is NOT_SOLVABLE; expectations cannot be "
                "compared to the evidence")
    lo, hi = min(sust_low, sust_high), max(sust_low, sust_high)
    width = hi - lo
    margin = ALIGNED_TOLERANCE_FRAC * width if width > 0 else abs(hi) * ALIGNED_TOLERANCE_FRAC
    if implied_fcff > hi + margin:
        return (ExpectationsVsEvidence.MARKET_EXPECTATIONS_ABOVE_EVIDENCE,
                f"market-implied base FCFF {implied_fcff:,.0f} exceeds the top "
                f"of the evidence-supported sustainable range ({hi:,.0f}); the "
                "price requires FCFF the best evidence-based case does not reach")
    if implied_fcff < lo - margin:
        return (ExpectationsVsEvidence.MARKET_EXPECTATIONS_BELOW_EVIDENCE,
                f"market-implied base FCFF {implied_fcff:,.0f} is below the "
                f"conservative end of the sustainable range ({lo:,.0f}); the "
                "price is pricing in LESS than even the cautious evidence case")
    return (ExpectationsVsEvidence.MARKET_EXPECTATIONS_ALIGNED,
            f"market-implied base FCFF {implied_fcff:,.0f} sits inside the "
            f"evidence-supported sustainable range ({lo:,.0f} to {hi:,.0f})")


def _classify_level(implied_fcff, sust_low, sust_central, sust_high, sust_status,
                    latest_fcff) -> tuple[ExpectationsLevel, str]:
    if implied_fcff is None:
        return (ExpectationsLevel.NOT_CLASSIFIED,
                "market-implied base FCFF is NOT_SOLVABLE")
    if sust_status != "SUPPORTED_RANGE" or sust_high is None:
        # No evidence range - grade against the latest reconstructed FCFF, the
        # only reference available, and say so explicitly.
        if latest_fcff is None or latest_fcff == 0 or not math.isfinite(latest_fcff):
            return (ExpectationsLevel.NOT_CLASSIFIED,
                    "no evidence range and no usable latest FCFF to grade against")
        ratio = implied_fcff / latest_fcff
        if ratio <= LEVEL_DEMANDING_RATIO + 0.05:
            lvl = ExpectationsLevel.EXPECTATIONS_MODEST
        elif ratio <= LEVEL_EXTREME_RATIO:
            lvl = ExpectationsLevel.EXPECTATIONS_DEMANDING
        else:
            lvl = ExpectationsLevel.EXPECTATIONS_EXTREME
        return (lvl, f"P6 returned {sust_status}; graded against the latest "
                f"reconstructed FCFF ({latest_fcff:,.0f}) only - the price "
                f"implies {ratio:.2f}x that level - NOT an evidence-range grading")
    lo, hi = min(sust_low, sust_high), max(sust_low, sust_high)
    central = sust_central if sust_central is not None else (lo + hi) / 2
    if implied_fcff <= central:
        return (ExpectationsLevel.EXPECTATIONS_MODEST,
                f"the price implies FCFF ({implied_fcff:,.0f}) at or below the "
                f"central sustainable estimate ({central:,.0f})")
    if implied_fcff <= max(hi, central) * LEVEL_EXTREME_RATIO and implied_fcff <= hi + abs(hi - lo):
        return (ExpectationsLevel.EXPECTATIONS_DEMANDING,
                f"the price implies FCFF ({implied_fcff:,.0f}) above the central "
                f"sustainable estimate ({central:,.0f}) - it needs the upper "
                "part of the evidence range to be realised")
    return (ExpectationsLevel.EXPECTATIONS_EXTREME,
            f"the price implies FCFF ({implied_fcff:,.0f}) well beyond the "
            f"evidence-supported range top ({hi:,.0f})")


# --------------------------------------------------------------------------- #
# orchestrator
# --------------------------------------------------------------------------- #
def assess_market_expectations(run, market_price: float | None = None
                               ) -> MarketExpectations | None:
    """Read a finished ValuationRun (+ the P6 sustainable layer) and produce
    the market-implied expectations analysis. Never mutates the run."""
    inputs = getattr(getattr(run, "bridged", None), "inputs", None)
    result = getattr(run, "result", None)
    if inputs is None or result is None:
        return None
    price = market_price if market_price is not None else getattr(run, "market_price", None)
    if price is None or not math.isfinite(price):
        return None

    doc_id = getattr(run, "doc_id", "")
    as_of = "as supplied to the run"
    sp = (getattr(run, "market", {}) or {}).get("share_price")
    if sp is not None and getattr(sp, "as_of", None):
        as_of = sp.as_of

    # P6 sustainable layer (one-directional dependency)
    sust_low = sust_central = sust_high = None
    sust_status = "NOT_ASSESSED"
    try:
        from .sustainable_fcff import assess_sustainable_fcff
        s = assess_sustainable_fcff(run)
        sust_status = s.status.value
        sust_low, sust_central, sust_high = s.low, s.central, s.high
    except Exception:  # noqa: BLE001 - experimental dependency, never fatal
        pass

    iug = implied_uniform_growth(inputs, price)
    ibf = implied_base_fcff(inputs, price)

    anchors: list[tuple[str, float | None]] = [
        ("latest", inputs.base_cash_flow),
        ("sustainable_low", sust_low),
        ("sustainable_central", sust_central),
        ("sustainable_high", sust_high),
    ]
    scen = anchor_scenarios(inputs, price, anchors)

    wacc_bounds = getattr(run, "wacc_at_beta_bounds", None) or (
        inputs.discount_rate - 0.02, inputs.discount_rate + 0.02)
    tg_bounds = (getattr(run, "bridged", None).tornado_ranges or {}).get(
        "terminal_growth", (max(0.0, inputs.terminal_growth - 0.01),
                            min(0.029, inputs.terminal_growth + 0.005)))
    wacc_sens = wacc_sensitivity(inputs, price, tuple(wacc_bounds))
    tg_sens = terminal_growth_sensitivity(inputs, price, tuple(tg_bounds))

    vs_ev, vs_reason = _classify_vs_evidence(ibf.value, sust_low, sust_high, sust_status)
    level, level_reason = _classify_level(ibf.value, sust_low, sust_central,
                                          sust_high, sust_status,
                                          inputs.base_cash_flow)

    applic = ""
    rob = getattr(run, "robustness", None)
    if rob is not None and getattr(rob, "applicability", None) is not None:
        applic = rob.applicability.value

    # historical evidence strings (for the gap table, not for arithmetic)
    rg = (getattr(run, "ranges", {}) or {}).get("revenue_growth")
    hist_growth = (f"{rg.low:.1f}%-{rg.high:.1f}% YoY revenue growth (median "
                   f"{rg.base:.1f}%)" if rg is not None and rg.low is not None
                   else "not available")
    fwd_g1 = inputs.growth_rates[0] if inputs.growth_rates else float("nan")

    gaps = (
        ExpectationsGap(
            "uniform FCFF growth",
            f"{iug.value:.1%}" if iug.value is not None else "NOT_SOLVABLE",
            hist_growth,
            f"faded FCFF-growth vector {fwd_g1:.1%} -> {inputs.terminal_growth:.1%}",
            "n/a (P6 solves a level, not a growth)",
            ("N/A" if iug.value is None else
             "ABOVE" if iug.value > fwd_g1 else
             "BELOW" if iug.value < inputs.terminal_growth else "WITHIN")),
        ExpectationsGap(
            "base FCFF level",
            f"{ibf.value:,.0f}" if ibf.value is not None else "NOT_SOLVABLE",
            f"latest reconstructed FCFF {inputs.base_cash_flow:,.0f}",
            f"{inputs.base_cash_flow:,.0f} (the base anchor)",
            (f"low {sust_low:,.0f} / central {sust_central:,.0f} / high "
             f"{sust_high:,.0f}" if sust_status == "SUPPORTED_RANGE"
             else f"P6: {sust_status}"),
            ("N/A" if ibf.value is None or sust_status != "SUPPORTED_RANGE" else
             "ABOVE" if ibf.value > max(sust_low, sust_high) else
             "BELOW" if ibf.value < min(sust_low, sust_high) else "WITHIN")),
        ExpectationsGap(
            "terminal dependence",
            f"implied growth moves {_span(tg_sens)} across the terminal-growth band",
            "n/a", f"terminal growth fixed at {inputs.terminal_growth:.1%}",
            "n/a", "N/A"),
        ExpectationsGap(
            "discount-rate dependence",
            f"implied growth moves {_span(wacc_sens)} across the WACC band",
            "n/a", f"WACC fixed at {inputs.discount_rate:.2%}",
            "n/a", "N/A"),
    )

    fwd_value = result.value_per_share
    diff = price - fwd_value
    interpretation = _interpret(
        doc_id, price, fwd_value, diff, iug, ibf, vs_ev, level,
        sust_status, sust_low, sust_central, sust_high, inputs, vs_reason,
        level_reason)

    notes = (
        "EXPERIMENTAL: nothing here changed the base DCF, WACC, FCFF, "
        "terminal value, or value per share.",
        "The implied-growth figure is a UNIFORM-growth equivalent holding all "
        "other model inputs fixed - not 'the expected growth rate' and not "
        "the inverse of the forward (faded-vector) DCF.",
        f"Forward DCF {fwd_value:,.2f} vs market {price:,.2f}: "
        f"{'market above DCF' if diff > 0 else 'market below DCF'} by "
        f"{abs(diff):,.2f}/share ({abs(diff) / fwd_value:.0%}).",
        "This layer does NOT conclude the stock is cheap or expensive; it "
        "states what the price requires and whether the evidence supports it.",
    )

    return MarketExpectations(
        doc_id=doc_id, price=price, as_of=as_of, wacc=inputs.discount_rate,
        terminal_growth=inputs.terminal_growth, base_fcff=inputs.base_cash_flow,
        shares=inputs.shares_outstanding, net_debt=inputs.net_debt,
        forecast_years=len(inputs.growth_rates), forward_dcf_value=fwd_value,
        implied_uniform_growth=iug, implied_base_fcff=ibf,
        sustainable_fcff_low=sust_low, sustainable_fcff_central=sust_central,
        sustainable_fcff_high=sust_high, sustainable_status=sust_status,
        evidence_status=vs_reason, applicability=applic,
        anchor_scenarios=scen, wacc_sensitivity=wacc_sens,
        terminal_growth_sensitivity=tg_sens, gaps=gaps,
        vs_evidence=vs_ev, level=level, interpretation=interpretation,
        notes=notes)


def _span(rows: tuple[SensitivityRow, ...]) -> str:
    gs = [r.implied_uniform_growth for r in rows if r.implied_uniform_growth is not None]
    if len(gs) < 2:
        return "NOT_SOLVABLE at one or more bounds"
    return f"{min(gs):.1%} to {max(gs):.1%}"


def _interpret(doc_id, price, fwd, diff, iug, ibf, vs_ev, level, sust_status,
               s_lo, s_ce, s_hi, inputs, vs_reason, level_reason) -> str:
    g_txt = (f"a uniform FCFF growth of {iug.value:.1%} for "
             f"{len(inputs.growth_rates)} years"
             if iug.value is not None else
             "a uniform FCFF growth outside the -50% to +100% search window "
             "(NOT_SOLVABLE)")
    f_txt = (f"a base FCFF of {ibf.value:,.0f} (vs the latest reconstructed "
             f"{inputs.base_cash_flow:,.0f})"
             if ibf.value is not None else "a base FCFF the model cannot solve for")
    if sust_status == "SUPPORTED_RANGE" and ibf.value is not None:
        ev_txt = (f"The P6 evidence supports a sustainable FCFF of "
                  f"{s_lo:,.0f} to {s_hi:,.0f} (central {s_ce:,.0f}). "
                  + vs_reason + ".")
    else:
        ev_txt = ("The P6 sustainable-FCFF layer returned "
                  f"{sust_status}, so the price cannot be checked against an "
                  "evidence-based FCFF range.")
    return (
        f"At {price:,.2f}/share the valuation framework requires {g_txt}, "
        f"equivalently {f_txt}, holding WACC ({inputs.discount_rate:.2%}), "
        f"terminal growth ({inputs.terminal_growth:.1%}), the 10-year horizon, "
        f"net debt and share count fixed. {ev_txt} "
        f"Expectations vs evidence: {vs_ev.value}; level: {level.value} "
        f"({level_reason}). The forward DCF values the filing at {fwd:,.2f}; "
        f"the market is {'above' if diff > 0 else 'below'} that by "
        f"{abs(diff):,.2f}. This is an interpretation of what the price "
        "embeds, not a recommendation.")
