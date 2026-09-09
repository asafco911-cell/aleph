"""P5 - valuation robustness diagnostics. DIAGNOSTIC ONLY.

The question this layer answers is not "can the engine compute a DCF" - it
can - but "how much of this valuation is determined by a CHOICE rather than
a fact, and is that choice's influence visible?". It measures:

  - FCFF ANCHOR sensitivity: value under latest / mean / median / each
    disclosed year. No anchor is promoted as objectively correct; the
    spread is reported.
  - TERMINAL VALUE dependence: what share of enterprise value rests on the
    Gordon tail rather than the explicit forecast.
  - ASSUMPTION sensitivity: which single assumption moves the valuation
    most (reads the tornado the pipeline already computed).
  - REVERSE DCF consistency: does the implied growth rate, fed back into
    the forward engine, reproduce the market price? If not solvable, say so.
  - VALUE-BRIDGE integrity: EV -> equity -> per-share arithmetic, and a
    magnitude check that catches a 1,000x unit error.
  - HISTORICAL REGIME: is the FCFF series even comparable across time, or
    is a single anchor a bet on one regime?

ISOLATION. This module imports only ``dcf_engine`` (to re-run the PURE
engine on trial copies) and stdlib. It never imports the bridge, WACC,
assumptions, or accounting-quality layers. It receives the already-built
``DCFInputs`` and the finished ``DCFResult``; it re-runs ``run_dcf`` on
COPIES and returns findings. Nothing it produces is read back into the
valuation. A regression test proves an absurd robustness report leaves
every valuation number byte-identical.

NO NEW MODEL. It does not normalise, does not choose an anchor, does not
adjust a rate. Where the mathematics is unsolvable it reports NOT_SOLVABLE;
where the model is economically inappropriate it reports
VALUATION_METHOD_LIMITATION; it never forces a number.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from statistics import mean, median

from .dcf_engine import DCFConsistencyError, DCFInputs, DCFResult, run_dcf

__all__ = [
    "FailureCategory",
    "Sensitivity",
    "Severity",
    "AnchorValuation",
    "Applicability",
    "ModelConvention",
    "model_conventions",
    "RobustnessFinding",
    "RobustnessReport",
    "assess_robustness",
    "categorize_failure",
    "WACC_BETA_EXTREME_LOW",
    "WACC_BETA_EXTREME_HIGH",
    "WACC_ERP_EXTREME_LOW",
    "WACC_ERP_EXTREME_HIGH",
    "WACC_RF_EXTREME_HIGH",
    "ANCHOR_SPREAD_HIGH",
    "ANCHOR_SPREAD_MEDIUM",
    "TV_DEPENDENCE_HIGH",
    "TV_DEPENDENCE_EXTREME",
    "REVERSE_DCF_TOLERANCE",
    "EV_TO_FCFF_SANE_LOW",
    "EV_TO_FCFF_SANE_HIGH",
    "PER_SHARE_SANE_LOW",
    "PER_SHARE_SANE_HIGH",
    "NET_DEBT_TO_EV_SANE",
]


# --------------------------------------------------------------------------- #
# Phase 14 - institutional failure taxonomy. A valuation is never just
# "failed"; the caller maps its exception to one of these.
# --------------------------------------------------------------------------- #
class FailureCategory(str, Enum):
    DATA_FAILURE = "DATA_FAILURE"
    EXTRACTION_FAILURE = "EXTRACTION_FAILURE"
    VERIFICATION_FAILURE = "VERIFICATION_FAILURE"
    ACCOUNTING_FAILURE = "ACCOUNTING_FAILURE"
    ECONOMIC_MODEL_FAILURE = "ECONOMIC_MODEL_FAILURE"
    MATHEMATICAL_FAILURE = "MATHEMATICAL_FAILURE"
    ASSUMPTION_FAILURE = "ASSUMPTION_FAILURE"
    MARKET_DATA_FAILURE = "MARKET_DATA_FAILURE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NOT_SOLVABLE = "NOT_SOLVABLE"


def categorize_failure(exc: BaseException) -> tuple[FailureCategory, str]:
    """Map a pipeline exception to a taxonomy category + a usability note.

    Deterministic, string-free of judgement: it keys off the exception type
    and, for the two broad ones, a substring already present in the message.
    """
    name = type(exc).__name__
    msg = str(exc)
    low = msg.lower()
    if name == "ContractBlockedError":
        return (FailureCategory.INSUFFICIENT_EVIDENCE,
                "a required observation is missing, ambiguous, wrong-unit or "
                "wrong-period; the valuation did not run and is NOT usable.")
    if name == "BlockedError":
        return (FailureCategory.ASSUMPTION_FAILURE,
                "a required assumption is blocked pending an analyst decision "
                "(e.g. net-debt policy); the valuation is NOT usable until it "
                "is supplied.")
    if name == "MarketDriftError":
        return (FailureCategory.MARKET_DATA_FAILURE,
                "a per-filing market input redefines a shared one; the "
                "cross-company comparison would be invalid.")
    if name == "BridgeError":
        if "discount_rate" in low or "wacc" in low:
            return (FailureCategory.MARKET_DATA_FAILURE,
                    "WACC could not be built from the declared market inputs; "
                    "the valuation is NOT usable.")
        if "unit" in low or "scale" in low:
            return (FailureCategory.DATA_FAILURE,
                    "a declared unit could not be converted; the valuation is "
                    "NOT usable.")
        return (FailureCategory.ASSUMPTION_FAILURE,
                "DCF inputs could not be assembled; the valuation is NOT usable.")
    if name == "DCFConsistencyError":
        if "not_solvable" in low or "zero" in low or "non-finite" in low:
            return (FailureCategory.NOT_SOLVABLE,
                    "the DCF is mathematically ill-posed for these inputs; no "
                    "value is produced by design.")
        if "terminal_growth" in low or "gordon" in low or "economy" in low:
            return (FailureCategory.ECONOMIC_MODEL_FAILURE,
                    "terminal growth is not below the discount rate, or exceeds "
                    "long-run economy growth; a perpetuity is inappropriate.")
        return (FailureCategory.MATHEMATICAL_FAILURE,
                "a DCF consistency guard rejected the inputs; the valuation is "
                "NOT usable.")
    return (FailureCategory.MATHEMATICAL_FAILURE,
            f"unclassified failure ({name}); treat the valuation as NOT usable.")


# --------------------------------------------------------------------------- #
class Sensitivity(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_SOLVABLE = "NOT_SOLVABLE"


class Severity(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


# Thresholds - conventions, each with a stated rationale. They gate a
# categorical label, never a number, and never the DCF.
#
# Anchor spread as a share of the anchor valuations' own midpoint. rationale:
# above half the midpoint, the choice of which year's FCFF to anchor on moves
# the answer more than any business fact in the model. Reused from
# historical_fcff.HIGH_ANCHOR_SENSITIVITY so the two cannot drift.
ANCHOR_SPREAD_HIGH = 0.50
ANCHOR_SPREAD_MEDIUM = 0.25

# Terminal value as a share of enterprise value. rationale: above 80% the
# valuation is a bet on the perpetuity, not on the forecast; above 90% the
# explicit years are rounding error. Not rejected - exposed.
TV_DEPENDENCE_HIGH = 0.80
TV_DEPENDENCE_EXTREME = 0.90

# Reverse-DCF round trip: the implied growth fed back into the forward engine
# must reproduce the market price within this relative tolerance, matching
# dcf_engine.reverse_dcf's own convergence tolerance.
REVERSE_DCF_TOLERANCE = 0.01

# EV / base-FCFF multiple that a well-posed DCF stays within. rationale: a
# 10-year DCF with 2-3% terminal growth and a high-single-digit discount
# rate implies an EV/FCFF roughly between 3x and 80x; an order of magnitude
# outside that is the signature of a growth/rate mistake. NOTE this ratio is
# scale-INVARIANT (FCFF and EV scale together) so it does NOT catch a
# shares/net-debt scale error - the per-share and net-debt/EV checks below
# do that.
EV_TO_FCFF_SANE_LOW = 3.0
EV_TO_FCFF_SANE_HIGH = 80.0

# A per-share value outside this band, or net debt more than this multiple of
# enterprise value, is the signature of a unit-scale error between FCFF, net
# debt, shares and price (ISSUES.md #15, the LYFT_FY2025 1000x). Very wide -
# it catches 1,000x, never a merely aggressive valuation.
PER_SHARE_SANE_LOW = 1e-2
PER_SHARE_SANE_HIGH = 1e6
NET_DEBT_TO_EV_SANE = 50.0

# WACC component sanity bounds. rationale: NOT economic truth - just the
# range outside which a value is almost certainly a data error, not a real
# market view. The engine NEVER clamps to these; a value outside them makes
# WACC_INPUT_QUALITY report LIMITED, and the reader decides. Wide on purpose.
WACC_BETA_EXTREME_LOW = 0.2      # below ~0.2 unlevered beta is implausible for an equity
WACC_BETA_EXTREME_HIGH = 3.0     # above ~3 is a distressed/leveraged single stock, not an industry
WACC_ERP_EXTREME_LOW = 0.02     # a mature-market ERP below 2% or
WACC_ERP_EXTREME_HIGH = 0.10    # above 10% is outside every historical estimate
WACC_RF_EXTREME_HIGH = 0.15     # a USD 10Y risk-free above 15% has not occurred in the modern era
# How many days between two market inputs' as_of dates before they are
# "describing different market states". A quarter.
WACC_STALE_DAYS = 92


@dataclass(frozen=True)
class AnchorValuation:
    method: str                 # "latest" | "historical_mean" | ... | "FY2023"
    basis: str                  # human sentence: what this number is
    fcff: float
    value_per_share: float | None
    rejected: str = ""          # guard message when the DCF refused this anchor


@dataclass(frozen=True)
class ModelConvention:
    """P5.2 - a methodology choice that materially affects the valuation,
    captured as a first-class object rather than a code default or a comment.
    Classification is always MODEL_CONVENTION."""
    name: str
    value: str
    rationale: str
    location: str
    effect: str
    classification: str = "MODEL_CONVENTION"


# Every convention that sits between the filing and the valuation. Values are
# read live where possible so this cannot drift from the code.
def model_conventions(inputs=None, forecast_years: int = 10) -> tuple["ModelConvention", ...]:
    fade_span = "n/a"
    if inputs is not None and getattr(inputs, "growth_rates", None):
        g = inputs.growth_rates
        fade_span = f"{g[0]:.2%} -> {g[-1]:.2%} over {len(g)} years"
    return (
        ModelConvention(
            "forecast_horizon", str(forecast_years),
            "10-year explicit forecast; matches the 10Y risk-free tenor used "
            "in WACC. Shorter/longer horizons shift the split between explicit "
            "PV and terminal value.",
            "bridge.py - DCF-inputs assembly, forecast_years default arg",
            "changes terminal-value share and the discount exponent"),
        ModelConvention(
            "growth_summary_statistic", "median",
            "year-1 growth is the MEDIAN of the year-over-year revenue growth "
            "observations (min/max are the band). Median resists one outlying "
            "year; a mean or the latest year would differ.",
            "assumptions.build_trend  base = median(values)",
            "sets the starting point of the growth fade"),
        ModelConvention(
            "growth_fade_shape", f"linear ({fade_span})",
            "growth steps linearly from year-1 to terminal over the horizon. "
            "A front- or back-loaded fade would move value materially; linear "
            "is a neutral default, not a derivation.",
            "bridge.fade()  step = (start - end) / (years - 1)",
            "controls how fast growth decays to terminal"),
        ModelConvention(
            "terminal_growth", "0.025",
            "held identical across every filer (a method choice, not a company "
            "fact); below long-run nominal GDP. Source in data/market.json is "
            "'analyst judgment'.",
            "data/market.json shared block; Assumption tagged analyst_judgment",
            "Gordon numerator and denominator - a large lever on terminal value"),
        ModelConvention(
            "terminal_growth_cap", "0.03",
            "the engine refuses terminal growth above 3% (a company cannot "
            "outgrow the whole economy forever).",
            "dcf_engine.validate Guard 2",
            "hard ceiling; blocks rather than clamps"),
        ModelConvention(
            "beta_sensitivity_factors", "0.75 / 1.45",
            "the WACC tornado band re-derives WACC at 75% and 145% of the "
            "unlevered industry beta. An asymmetric, hand-chosen band.",
            "pipeline.BETA_BOUND_FACTORS",
            "sets the discount-rate sensitivity range shown to the reader"),
        ModelConvention(
            "reverse_dcf_search_window", "-50% / +100%",
            "the uniform-growth equivalent is searched only within this band; "
            "an implied growth outside it is reported NOT_SOLVABLE.",
            "dcf_engine.REVERSE_DCF_LOW / REVERSE_DCF_HIGH",
            "bounds what the market-expectations figure can report"),
        ModelConvention(
            "reverse_dcf_tolerance", "0.001",
            "relative convergence tolerance for the uniform-growth solve.",
            "dcf_engine.reverse_dcf tolerance default arg",
            "precision of the implied-growth figure"),
        ModelConvention(
            "sbc_treatment", "full-value cash cost; shares held flat",
            "SBC is subtracted from FCFF at full value and the diluted share "
            "count is NOT grown for future issuance (ADR 0002) - doing both "
            "would double-count.",
            "bridge.py - FCFF assembly (fcff = ... - sbc); shares held flat",
            "lowers FCFF; alternative treatments (add back + dilute) would raise it"),
        ModelConvention(
            "net_cash_wacc_clamp", "debt_value = max(net_debt, 0)",
            "a net-cash filer's debt weight is clamped to zero for Hamada "
            "relevering (undefined for negative leverage). Disclosed in "
            "wacc.notes when it fires (ISSUES.md #17, #25).",
            "wacc.py - debt_value = max(net_debt, 0.0)",
            "net-cash filers get no leverage benefit in WACC"),
        _APPLICABILITY_RULES,
    )


@dataclass(frozen=True)
class RobustnessFinding:
    key: str
    severity: Severity
    sensitivity: Sensitivity
    headline: str
    detail: str
    interpretation: str
    numbers: dict[str, float] = field(default_factory=dict)
    category: "FailureCategory | None" = None       # P5.12 institutional taxonomy


class Applicability(str, Enum):
    """P5.1-closure - is this valuation economically USABLE? A categorical
    applicability status, NOT a confidence score. Derived by explicit rules
    from evidence already computed (see _applicability)."""
    USABLE = "USABLE"
    USABLE_WITH_LIMITATIONS = "USABLE_WITH_LIMITATIONS"
    LIMITED_APPLICABILITY = "LIMITED_APPLICABILITY"
    NOT_SOLVABLE = "NOT_SOLVABLE"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class RobustnessReport:
    doc_id: str
    assessed: bool
    findings: tuple[RobustnessFinding, ...]
    anchor_table: tuple[AnchorValuation, ...] = ()
    primary_driver: str = ""
    notes: tuple[str, ...] = ()
    not_assessed_reason: str = ""
    model_conventions: tuple[ModelConvention, ...] = ()
    applicability: Applicability = Applicability.USABLE
    applicability_reasons: tuple[str, ...] = ()
    limitation_families: tuple[str, ...] = ()
    headline_conclusion: str = ""

    @staticmethod
    def not_assessed(doc_id: str, reason: str) -> "RobustnessReport":
        return RobustnessReport(
            doc_id=doc_id, assessed=False, findings=(),
            notes=(f"VALUATION ROBUSTNESS: NOT ASSESSED - {reason}. The "
                   "valuation above is unaffected.",),
            not_assessed_reason=reason,
            applicability=Applicability.NOT_SOLVABLE)

    def get(self, key: str) -> RobustnessFinding | None:
        return next((f for f in self.findings if f.key == key), None)

    @property
    def high_severity(self) -> tuple[RobustnessFinding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.HIGH)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _rerun_at(inputs: DCFInputs, base_cash_flow: float) -> tuple[float | None, str]:
    """Run the PURE engine on a COPY with only base_cash_flow replaced."""
    trial = DCFInputs(
        cash_flow_type=inputs.cash_flow_type,
        base_cash_flow=base_cash_flow,
        growth_rates=list(inputs.growth_rates),
        terminal_growth=inputs.terminal_growth,
        discount_rate=inputs.discount_rate,
        net_debt=inputs.net_debt,
        shares_outstanding=inputs.shares_outstanding,
        assumptions=[],
    )
    try:
        return run_dcf(trial).value_per_share, ""
    except DCFConsistencyError as exc:
        return None, str(exc)


def _spread(values: list[float]) -> tuple[float, float, float] | None:
    """(low, high, spread_over_midpoint) for a list of per-share values."""
    if len(values) < 2:
        return None
    lo, hi = min(values), max(values)
    mid = (lo + hi) / 2
    if mid == 0:
        return lo, hi, math.inf
    return lo, hi, abs(hi - lo) / abs(mid)


# --------------------------------------------------------------------------- #
# 1. FCFF anchor sensitivity
# --------------------------------------------------------------------------- #
def _anchor_sensitivity(
    inputs: DCFInputs, fcff_by_period: dict[str, float] | None
) -> tuple[list[AnchorValuation], RobustnessFinding]:
    latest_vps, latest_rej = _rerun_at(inputs, inputs.base_cash_flow)
    table: list[AnchorValuation] = [AnchorValuation(
        "latest", "the base case - the most recent disclosed year's FCFF",
        inputs.base_cash_flow, latest_vps, latest_rej)]

    if not fcff_by_period or len(fcff_by_period) < 2:
        return table, RobustnessFinding(
            key="ANCHOR_SENSITIVITY", severity=Severity.INFO,
            sensitivity=Sensitivity.NOT_APPLICABLE,
            headline="ANCHOR SENSITIVITY: not assessed",
            detail=("fewer than two disclosed FCFF years are reconstructable, "
                    "so the valuation cannot be re-run under alternative "
                    "anchors."),
            interpretation=("the base case rests on one year of FCFF with no "
                            "in-model check of how much that choice matters. "
                            "This is a known limitation, not a clean bill."),
            numbers={"periods": float(len(fcff_by_period or {}))})

    series = dict(sorted(fcff_by_period.items()))
    vals = list(series.values())
    stats = {
        "historical_mean": (mean(vals),
                            "arithmetic mean of every disclosed FCFF year (a "
                            "STATISTIC, not an economic normalisation)"),
        "historical_median": (median(vals),
                              "median of every disclosed FCFF year (a "
                              "STATISTIC; robust to one outlying year, wrong "
                              "if the business changed level)"),
    }
    for name, (fcff, basis) in stats.items():
        vps, rej = _rerun_at(inputs, fcff)
        table.append(AnchorValuation(name, basis, fcff, vps, rej))
    for period, fcff in series.items():
        vps, rej = _rerun_at(inputs, fcff)
        table.append(AnchorValuation(
            period, f"the DCF anchored entirely on {period}'s reconstructed FCFF",
            fcff, vps, rej))

    priced = [a.value_per_share for a in table if a.value_per_share is not None]
    sp = _spread(priced)
    if sp is None:
        sens, sev = Sensitivity.NOT_SOLVABLE, Severity.HIGH
        headline = "ANCHOR SENSITIVITY: NOT_SOLVABLE"
        detail = ("no alternative anchor produced a valid DCF - every "
                  "historical year violates a consistency guard.")
    else:
        lo, hi, spread = sp
        if spread > ANCHOR_SPREAD_HIGH:
            sens, sev = Sensitivity.HIGH, Severity.HIGH
        elif spread > ANCHOR_SPREAD_MEDIUM:
            sens, sev = Sensitivity.MEDIUM, Severity.MEDIUM
        else:
            sens, sev = Sensitivity.LOW, Severity.LOW
        headline = f"ANCHOR SENSITIVITY: {sens.value}"
        detail = (f"value/share spans {lo:,.2f} to {hi:,.2f} across anchors "
                  f"(latest / mean / median / each disclosed year), a spread of "
                  f"{spread:.0%} of the midpoint. Latest-basis: "
                  f"{latest_vps:,.2f}." if latest_vps is not None else
                  f"value/share spans {lo:,.2f} to {hi:,.2f} across alternative "
                  f"anchors ({spread:.0%} of midpoint); the latest-basis DCF "
                  f"itself was rejected: {latest_rej}")
    return table, RobustnessFinding(
        key="ANCHOR_SENSITIVITY", severity=sev, sensitivity=sens,
        headline=headline, detail=detail,
        interpretation=(
            "no single anchor is objectively correct. "
            + ("A large share of the valuation is the analyst's choice of "
               "which year (or statistic) represents run-rate FCFF, not a "
               "business fact - averaging does not resolve this and can widen "
               "it (ISSUES.md #29)."
               if sens is Sensitivity.HIGH else
               "The anchor choice moves the answer, but less than the "
               "business assumptions do." if sens is Sensitivity.MEDIUM else
               "The valuation is not dominated by the anchor choice on the "
               "disclosed history.")),
        numbers={"low": sp[0] if sp else math.nan,
                 "high": sp[1] if sp else math.nan,
                 "spread": sp[2] if sp else math.nan,
                 "latest": latest_vps if latest_vps is not None else math.nan})


# --------------------------------------------------------------------------- #
# 2. terminal value dependence
# --------------------------------------------------------------------------- #
def _terminal_value_dependence(result: DCFResult) -> RobustnessFinding:
    tv = result.terminal_pct
    if not math.isfinite(tv):
        return RobustnessFinding(
            key="TERMINAL_VALUE_DEPENDENCE", severity=Severity.HIGH,
            sensitivity=Sensitivity.NOT_SOLVABLE,
            headline="TERMINAL VALUE DEPENDENCE: NOT_SOLVABLE",
            detail="terminal_pct is not finite.",
            interpretation="the split between forecast and tail could not be "
                           "computed.", numbers={"terminal_pct": tv})
    if tv > TV_DEPENDENCE_EXTREME:
        sens, sev = Sensitivity.HIGH, Severity.HIGH
        note = ("the explicit 10-year forecast is effectively rounding error; "
                "this is a Gordon-perpetuity valuation wearing a DCF's "
                "clothes.")
    elif tv > TV_DEPENDENCE_HIGH:
        sens, sev = Sensitivity.HIGH, Severity.MEDIUM
        note = ("most of the value is in the perpetuity, so the terminal "
                "growth rate and discount rate matter more than any forecast "
                "year.")
    elif tv > 0.6:
        sens, sev = Sensitivity.MEDIUM, Severity.LOW
        note = "a normal-to-high tail share for a 10-year DCF."
    else:
        sens, sev = Sensitivity.LOW, Severity.INFO
        note = "the explicit forecast carries a meaningful share of the value."
    return RobustnessFinding(
        key="TERMINAL_VALUE_DEPENDENCE", severity=sev, sensitivity=sens,
        headline=f"TERMINAL VALUE DEPENDENCE: {sens.value}",
        detail=(f"PV(terminal) is {tv:.0%} of enterprise value "
                f"(PV explicit {result.pv_explicit:,.0f}, PV terminal "
                f"{result.pv_terminal:,.0f})."),
        interpretation=note,
        numbers={"terminal_pct": tv, "pv_explicit": result.pv_explicit,
                 "pv_terminal": result.pv_terminal})


# --------------------------------------------------------------------------- #
# 3. assumption sensitivity (reads the tornado the pipeline already built)
# --------------------------------------------------------------------------- #
def _assumption_sensitivity(
    tornado_rows: list[dict], base_vps: float
) -> tuple[RobustnessFinding, str]:
    rows = [r for r in tornado_rows if r.get("swing") is not None]
    if not rows:
        return (RobustnessFinding(
            key="ASSUMPTION_SENSITIVITY", severity=Severity.INFO,
            sensitivity=Sensitivity.NOT_APPLICABLE,
            headline="ASSUMPTION SENSITIVITY: not assessed",
            detail="no tornado row produced a valid swing.",
            interpretation="the assumptions could not be perturbed within "
                           "their stated bounds without violating a guard.",
            numbers={}), "")
    rows = sorted(rows, key=lambda r: r["swing"], reverse=True)
    top = rows[0]
    ranked = "; ".join(
        f"{r['param']} {r['swing_pct']:.0%}" for r in rows[:5])
    dominant = top["swing_pct"] > 0.5 and (
        len(rows) == 1 or top["swing"] > 2 * rows[1]["swing"])
    sev = Severity.HIGH if top["swing_pct"] > 1.0 else (
        Severity.MEDIUM if top["swing_pct"] > 0.5 else Severity.LOW)
    return (RobustnessFinding(
        key="ASSUMPTION_SENSITIVITY", severity=sev,
        sensitivity=(Sensitivity.HIGH if top["swing_pct"] > 0.5
                     else Sensitivity.MEDIUM if top["swing_pct"] > 0.25
                     else Sensitivity.LOW),
        headline=f"PRIMARY VALUE DRIVER: {top['param']}",
        detail=(f"moving {top['param']} across its stated bound swings "
                f"value/share by {top['swing']:,.2f} "
                f"({top['swing_pct']:.0%} of the {base_vps:,.2f} base). "
                f"Ranked: {ranked}."),
        interpretation=(
            f"the valuation is controlled by {top['param']}"
            + (" - it dwarfs every other assumption, so the debate is about "
               "that one input" if dominant else
               ", though other assumptions also move it materially") + "."),
        numbers={r["param"]: r["swing_pct"] for r in rows}), top["param"])


# --------------------------------------------------------------------------- #
# 4. reverse-DCF consistency (round trip)
# --------------------------------------------------------------------------- #
def _reverse_dcf_consistency(
    inputs: DCFInputs, market_price: float | None, implied_growth: float | None
) -> RobustnessFinding:
    if market_price is None:
        return RobustnessFinding(
            key="REVERSE_DCF_CONSISTENCY", severity=Severity.INFO,
            sensitivity=Sensitivity.NOT_APPLICABLE,
            headline="REVERSE DCF: not run (no market price supplied)",
            detail="", interpretation="", numbers={})
    if implied_growth is None:
        return RobustnessFinding(
            key="REVERSE_DCF_CONSISTENCY", severity=Severity.MEDIUM,
            sensitivity=Sensitivity.NOT_SOLVABLE,
            headline="REVERSE DCF: NOT_SOLVABLE",
            detail=(f"no uniform annual growth rate in the search range "
                    f"reproduces the market price of {market_price:,.2f}."),
            interpretation=("the market price cannot be explained by growth "
                            "alone under the model's other assumptions - it "
                            "may need a different anchor, margin path, or "
                            "discount rate. No implied growth is reported."),
            numbers={"market_price": market_price})
    n = len(inputs.growth_rates)
    trial = DCFInputs(
        cash_flow_type=inputs.cash_flow_type, base_cash_flow=inputs.base_cash_flow,
        growth_rates=[implied_growth] * n, terminal_growth=inputs.terminal_growth,
        discount_rate=inputs.discount_rate, net_debt=inputs.net_debt,
        shares_outstanding=inputs.shares_outstanding, assumptions=[])
    try:
        rt = run_dcf(trial).value_per_share
    except DCFConsistencyError as exc:
        return RobustnessFinding(
            key="REVERSE_DCF_CONSISTENCY", severity=Severity.HIGH,
            sensitivity=Sensitivity.NOT_SOLVABLE,
            headline="REVERSE DCF: INCONSISTENT (round-trip rejected)",
            detail=(f"the implied growth {implied_growth:.1%} fed back into the "
                    f"forward engine violates a guard: {exc}"),
            interpretation="forward and reverse DCF disagree; the implied "
                           "growth figure should not be relied on.",
            numbers={"implied_growth": implied_growth, "market_price": market_price})
    err = abs(rt - market_price) / abs(market_price) if market_price else math.inf
    ok = err <= REVERSE_DCF_TOLERANCE
    return RobustnessFinding(
        key="REVERSE_DCF_CONSISTENCY",
        severity=Severity.INFO if ok else Severity.HIGH,
        sensitivity=Sensitivity.LOW if ok else Sensitivity.NOT_SOLVABLE,
        headline=("REVERSE DCF: consistent" if ok else
                  "REVERSE DCF: INCONSISTENT"),
        detail=(f"implied uniform growth {implied_growth:.1%}; fed back it "
                f"values {rt:,.2f}/share against a market price of "
                f"{market_price:,.2f} (round-trip error {err:.2%}, tolerance "
                f"{REVERSE_DCF_TOLERANCE:.0%})."),
        interpretation=(
            "the implied-growth figure is conditional on the SAME anchor, "
            "WACC and terminal assumptions as the forward DCF - it is a "
            "restatement of the price under those assumptions, not an "
            "independent check." if ok else
            "the round trip does not close; the reported implied growth is "
            "unreliable."),
        numbers={"implied_growth": implied_growth, "round_trip_vps": rt,
                 "market_price": market_price, "round_trip_error": err})


# --------------------------------------------------------------------------- #
# 5. value-bridge integrity (EV -> equity -> per share, and scale sanity)
# --------------------------------------------------------------------------- #
def _value_bridge_integrity(
    inputs: DCFInputs, result: DCFResult
) -> RobustnessFinding:
    problems: list[str] = []
    ev = result.enterprise_or_equity_value
    expected_equity = (ev - inputs.net_debt if inputs.cash_flow_type == "FCFF"
                       else ev)
    if not math.isclose(result.equity_value, expected_equity, rel_tol=1e-9,
                        abs_tol=1e-6):
        problems.append(
            f"equity_value {result.equity_value:,.2f} != EV {ev:,.2f} - "
            f"net_debt {inputs.net_debt:,.2f} = {expected_equity:,.2f}")
    expected_vps = result.equity_value / inputs.shares_outstanding
    if not math.isclose(result.value_per_share, expected_vps, rel_tol=1e-9,
                        abs_tol=1e-6):
        problems.append(
            f"value_per_share {result.value_per_share:,.4f} != equity "
            f"{result.equity_value:,.2f} / shares {inputs.shares_outstanding:,.2f}")
    for label, v in (("EV", ev), ("equity", result.equity_value),
                     ("value_per_share", result.value_per_share)):
        if not math.isfinite(v):
            problems.append(f"{label} is not finite ({v})")

    # scale sanity. EV/FCFF is scale-invariant, so it flags a growth/rate
    # mistake, not a unit error. The per-share value and net-debt/EV ratios
    # catch a shares / net-debt scale error.
    ratio = ev / inputs.base_cash_flow if inputs.base_cash_flow else math.inf
    scale_reasons: list[str] = []
    if math.isfinite(ratio) and not (
            EV_TO_FCFF_SANE_LOW <= abs(ratio) <= EV_TO_FCFF_SANE_HIGH):
        scale_reasons.append(
            f"EV / base-FCFF = {ratio:,.1f}x, outside the "
            f"{EV_TO_FCFF_SANE_LOW:g}x-{EV_TO_FCFF_SANE_HIGH:g}x band")
    vps = result.value_per_share
    if math.isfinite(vps) and not (PER_SHARE_SANE_LOW <= abs(vps)
                                   <= PER_SHARE_SANE_HIGH):
        scale_reasons.append(
            f"value/share {vps:,.6g} is outside {PER_SHARE_SANE_LOW:g}-"
            f"{PER_SHARE_SANE_HIGH:g} - shares are likely in a different unit "
            "scale from FCFF")
    if math.isfinite(ev) and ev != 0 and abs(inputs.net_debt) > \
            NET_DEBT_TO_EV_SANE * abs(ev):
        scale_reasons.append(
            f"net debt {inputs.net_debt:,.0f} is {abs(inputs.net_debt/ev):,.0f}x "
            "enterprise value - a likely scale error")
    scale_flag = bool(scale_reasons)

    if problems:
        return RobustnessFinding(
            key="VALUE_BRIDGE_INTEGRITY", severity=Severity.HIGH,
            sensitivity=Sensitivity.NOT_SOLVABLE,
            headline="VALUE BRIDGE: BROKEN",
            detail="; ".join(problems),
            interpretation="the EV -> equity -> per-share arithmetic does not "
                           "reconcile; the per-share figure is not trustworthy.",
            numbers={"ev": ev, "equity": result.equity_value,
                     "vps": result.value_per_share})
    if scale_flag:
        return RobustnessFinding(
            key="VALUE_BRIDGE_INTEGRITY", severity=Severity.HIGH,
            sensitivity=Sensitivity.NOT_SOLVABLE,
            headline="VALUE BRIDGE: SCALE ANOMALY",
            detail="; ".join(scale_reasons) + ".",
            interpretation="check that FCFF, net debt and shares are all in "
                           "the same unit scale before using this valuation "
                           "(ISSUES.md #15).",
            numbers={"ev_to_fcff": ratio, "value_per_share": vps})
    return RobustnessFinding(
        key="VALUE_BRIDGE_INTEGRITY", severity=Severity.INFO,
        sensitivity=Sensitivity.LOW,
        headline="VALUE BRIDGE: consistent",
        detail=(f"equity = EV {ev:,.0f} - net debt {inputs.net_debt:,.0f}; "
                f"per share = equity / {inputs.shares_outstanding:,.0f} shares. "
                f"EV/base-FCFF = {ratio:,.1f}x."),
        interpretation="the arithmetic reconciles and the magnitudes are "
                       "internally consistent.",
        numbers={"ev_to_fcff": ratio})


# --------------------------------------------------------------------------- #
# 6. historical regime / comparability of the FCFF series
# --------------------------------------------------------------------------- #
def _historical_regime(fcff_by_period: dict[str, float] | None) -> RobustnessFinding:
    if not fcff_by_period or len(fcff_by_period) < 3:
        return RobustnessFinding(
            key="HISTORICAL_REGIME", severity=Severity.INFO,
            sensitivity=Sensitivity.NOT_APPLICABLE,
            headline="HISTORICAL REGIME: not assessed (< 3 FCFF years)",
            detail="", interpretation="with fewer than three disclosed FCFF "
            "years the series cannot be checked for comparability; a single "
            "anchor is unavoidable and its representativeness is untested.",
            numbers={"periods": float(len(fcff_by_period or {}))})
    series = dict(sorted(fcff_by_period.items()))
    vals = list(series.values())
    signs = {(-1 if v < 0 else 1 if v > 0 else 0) for v in vals}
    mixed_sign = (1 in signs and -1 in signs)
    rising = all(b > a for a, b in zip(vals, vals[1:]))
    falling = all(b < a for a, b in zip(vals, vals[1:]))
    prior, latest = vals[:-1], vals[-1]
    jump = (abs(latest - median(prior)) / abs(median(prior))
            if median(prior) else math.inf)
    tight = (all(p != 0 for p in prior)
             and (max(prior) - min(prior)) / abs(median(prior)) <= 0.20)
    regime_break = tight and jump >= 1.0

    flags = []
    if mixed_sign:
        flags.append("the series changes sign")
    if rising or falling:
        flags.append(f"monotonically {'rising' if rising else 'falling'} "
                     "across every disclosed year")
    if regime_break:
        flags.append(f"prior years sit in a tight band and the latest is "
                     f"{jump:+.0%} off their median")

    if not flags:
        return RobustnessFinding(
            key="HISTORICAL_REGIME", severity=Severity.LOW,
            sensitivity=Sensitivity.LOW,
            headline="HISTORICAL REGIME: series looks comparable",
            detail="FCFF by year: " + ", ".join(
                f"{p}={v:,.0f}" for p, v in series.items())
            + ". No sign change, monotonic trend, or level break detected.",
            interpretation="the disclosed FCFF years are plausibly draws from "
                           "one regime, so a single-anchor DCF is less exposed "
                           "to a comparability problem. This is NOT a "
                           "statement that the level is right.",
            numbers={"latest_vs_prior_median": jump})
    sev = Severity.HIGH if (mixed_sign or regime_break) else Severity.MEDIUM
    return RobustnessFinding(
        key="HISTORICAL_REGIME", severity=sev, sensitivity=Sensitivity.HIGH,
        headline="HISTORICAL REGIME: series may NOT be comparable across time",
        detail="FCFF by year: " + ", ".join(
            f"{p}={v:,.0f}" for p, v in series.items())
        + ". " + "; ".join(flags) + ".",
        interpretation=("anchoring a ten-year DCF on any one of these years - "
                        "or a statistic over them - assumes they measure the "
                        "same business. The numbers cannot confirm that; a "
                        "structural change and one unusual year look identical "
                        "in a list of figures (ISSUES.md #29). Treat the "
                        "anchor as a scenario input, not a fact."),
        numbers={"latest_vs_prior_median": jump})


# --------------------------------------------------------------------------- #
# 6b. history comparability taxonomy (P5.4) - a deterministic limitation
# framework, NOT a regime classifier. It never claims "a new regime"; it
# states which deterministic conditions reduce comparability.
# --------------------------------------------------------------------------- #
def _history_comparability(
    fcff_by_period: dict[str, float] | None,
    growth_rates_range: tuple[float, float] | None,
    reconstruction_note: str,
) -> RobustnessFinding:
    conditions: list[str] = []
    n = len(fcff_by_period or {})
    if n < 2:
        status = "NO_DETERMINABLE_CONCLUSION"
        conditions.append(f"only {n} reconstructable FCFF year(s) - cannot be "
                          "checked for comparability")
    else:
        series = dict(sorted(fcff_by_period.items()))
        vals = list(series.values())
        yrs = [int(p[2:]) for p in series if p[:2].upper() == "FY" and p[2:].isdigit()]
        if yrs and (max(yrs) - min(yrs) + 1) != len(yrs):
            conditions.append("a fiscal year is missing from the disclosed span")
        if any(v < 0 for v in vals) and any(v > 0 for v in vals):
            conditions.append("FCFF changes sign across the series")
        for a, b in zip(vals, vals[1:]):
            if a != 0 and abs(b - a) / abs(a) > 1.0:
                conditions.append("a year-over-year FCFF change exceeds 100%")
                break
        if n < 3:
            conditions.append("fewer than three FCFF years - a pattern cannot "
                              "be established")
        if growth_rates_range and growth_rates_range[1] - growth_rates_range[0] > 0.15:
            conditions.append(
                f"the year-over-year revenue growth band spans "
                f"{(growth_rates_range[1] - growth_rates_range[0]):.0%} - a "
                "growth-regime shift within the disclosed history")
        if reconstruction_note:
            conditions.append("historical FCFF was reconstructed using an "
                              "assumption, not fully observed facts "
                              f"({reconstruction_note[:80]})")
        if len(conditions) >= 2 or any("sign" in c for c in conditions):
            status = "HIGH_CONCERN"
        elif conditions:
            status = "LIMITED"
        else:
            status = "NO_DETERMINABLE_CONCERN"

    sev = (Severity.HIGH if status == "HIGH_CONCERN"
           else Severity.MEDIUM if status == "LIMITED"
           else Severity.INFO)
    body = ("; ".join(conditions) if conditions
            else "no deterministic comparability condition triggered")
    return RobustnessFinding(
        key="HISTORY_COMPARABILITY", severity=sev,
        sensitivity=(Sensitivity.HIGH if status == "HIGH_CONCERN"
                     else Sensitivity.MEDIUM if status == "LIMITED"
                     else Sensitivity.LOW),
        headline=f"HISTORY COMPARABILITY: {status}",
        detail=body + ".",
        interpretation=(
            "the disclosed FCFF/revenue history exhibits characteristics that "
            "reduce comparability across time, so a statistic over these years "
            "(latest, mean, median) rests on an assumption the numbers cannot "
            "confirm. This is NOT a claim that the business entered a new "
            "regime - only that the series is not clearly one regime."
            if status != "NO_DETERMINABLE_CONCERN" else
            "no deterministic condition reducing comparability was detected. "
            "This is not a statement that the anchor level is right."),
        numbers={"conditions": float(len(conditions)),
                 "periods": float(n)},
        category=FailureCategory.ECONOMIC_MODEL_FAILURE
        if status == "HIGH_CONCERN" else None)


# --------------------------------------------------------------------------- #
# 6c. WACC input quality (P5.6) - mathematical validity is separate from
# market-input INTEGRITY. This never clamps and never picks a new WACC.
# --------------------------------------------------------------------------- #
def _wacc_input_quality(market: dict, inputs: DCFInputs) -> RobustnessFinding:
    if not market:
        return RobustnessFinding(
            key="WACC_INPUT_QUALITY", severity=Severity.INFO,
            sensitivity=Sensitivity.NOT_APPLICABLE,
            headline="WACC INPUT QUALITY: not assessed (market inputs not supplied)",
            detail="", interpretation="", numbers={})

    def _v(name):
        m = market.get(name)
        return (getattr(m, "value", None),
                (getattr(m, "source", "") or "") + " "
                + (getattr(m, "rationale", "") or ""),
                getattr(m, "as_of", "") or "")

    rf_v, _rf_s, rf_as = _v("risk_free_rate")
    erp_v, _erp_s, erp_as = _v("equity_risk_premium")
    beta_v, _beta_s, _ = _v("unlevered_industry_beta")
    _sp_v, spread_s, _ = _v("debt_spread")
    _crp_v, crp_s, _ = _v("country_risk_premium")

    blocked: list[str] = []
    limited: list[str] = []
    unverified: list[str] = []

    for label, val in (("risk_free_rate", rf_v), ("equity_risk_premium", erp_v),
                       ("unlevered_industry_beta", beta_v)):
        if val is None:
            blocked.append(f"{label} is missing")
        elif not isinstance(val, (int, float)) or not math.isfinite(val):
            blocked.append(f"{label} is non-finite")

    if rf_v is not None and math.isfinite(rf_v):
        if rf_v < 0:
            blocked.append("risk_free_rate is negative")
        elif rf_v > WACC_RF_EXTREME_HIGH:
            limited.append(f"risk_free_rate {rf_v:.1%} is implausibly high")
    if erp_v is not None and math.isfinite(erp_v) and not (
            WACC_ERP_EXTREME_LOW <= erp_v <= WACC_ERP_EXTREME_HIGH):
        limited.append(f"equity_risk_premium {erp_v:.1%} is outside "
                       f"{WACC_ERP_EXTREME_LOW:.0%}-{WACC_ERP_EXTREME_HIGH:.0%}")
    if beta_v is not None and math.isfinite(beta_v) and not (
            WACC_BETA_EXTREME_LOW <= beta_v <= WACC_BETA_EXTREME_HIGH):
        limited.append(f"unlevered beta {beta_v:.2f} is outside "
                       f"{WACC_BETA_EXTREME_LOW}-{WACC_BETA_EXTREME_HIGH}")

    # WACC <= terminal growth is a mathematical block (the engine already
    # enforces it); surface it here too for a complete picture.
    if inputs.discount_rate <= inputs.terminal_growth:
        blocked.append(f"WACC {inputs.discount_rate:.2%} <= terminal growth "
                       f"{inputs.terminal_growth:.2%}")

    # explicitly-marked weak inputs (the data model tells us)
    for label, src in (("debt_spread", spread_s), ("country_risk_premium", crp_s)):
        if "unverified" in src.lower():
            unverified.append(f"{label} source is marked UNVERIFIED FOR THIS FILER")
        elif "judgment" in src.lower() or "judgement" in src.lower():
            limited.append(f"{label} is an undisclosed analyst judgement")

    # date mismatch between risk-free and ERP
    if rf_as and erp_as and rf_as[:7] != erp_as[:7]:
        limited.append(f"risk_free as_of {rf_as} and ERP as_of {erp_as} are "
                       "different market states (a known mismatch)")

    if blocked:
        status, sev, sens = "BLOCKED", Severity.HIGH, Sensitivity.NOT_SOLVABLE
        cat = FailureCategory.MARKET_DATA_FAILURE
        body = "; ".join(blocked)
        interp = ("WACC is mathematically invalid or a required input is "
                  "missing/non-finite. The valuation should be treated as "
                  "BLOCKED.")
    elif unverified:
        status, sev, sens = "INSUFFICIENT_EVIDENCE", Severity.MEDIUM, Sensitivity.MEDIUM
        cat = FailureCategory.INSUFFICIENT_EVIDENCE
        body = "; ".join(unverified + limited)
        interp = ("WACC is mathematically usable but at least one input is "
                  "explicitly UNVERIFIED for this filer. Treat the discount "
                  "rate - and everything downstream of it - as provisional.")
    elif limited:
        status, sev, sens = "LIMITED", Severity.MEDIUM, Sensitivity.MEDIUM
        cat = FailureCategory.MARKET_DATA_FAILURE
        body = "; ".join(limited)
        interp = ("WACC is mathematically usable but built on stale, extreme, "
                  "or undisclosed-judgement inputs. The discount rate is the "
                  "second-largest driver of the valuation; read it as an "
                  "estimate with material uncertainty, not a fact.")
    else:
        status, sev, sens = "OK", Severity.INFO, Sensitivity.LOW
        cat = None
        body = "all WACC inputs present, finite, in range, dated consistently"
        interp = "no input-integrity concern detected for WACC."

    return RobustnessFinding(
        key="WACC_INPUT_QUALITY", severity=sev, sensitivity=sens,
        headline=f"WACC INPUT QUALITY: {status}",
        detail=f"WACC = {inputs.discount_rate:.2%}. " + body + ".",
        interpretation=interp,
        numbers={"wacc": inputs.discount_rate,
                 "n_blocked": float(len(blocked)),
                 "n_limited": float(len(limited)),
                 "n_unverified": float(len(unverified))},
        category=cat)


# --------------------------------------------------------------------------- #
# 7. DCF method appropriateness (negative / near-zero base FCFF)
# --------------------------------------------------------------------------- #
def _method_limitation(inputs: DCFInputs, result: DCFResult) -> RobustnessFinding | None:
    if inputs.base_cash_flow < 0:
        return RobustnessFinding(
            key="VALUATION_METHOD_LIMITATION", severity=Severity.HIGH,
            sensitivity=Sensitivity.HIGH,
            headline="VALUATION METHOD LIMITATION: negative base FCFF",
            detail=(f"the base-case FCFF is {inputs.base_cash_flow:,.0f} "
                    f"(negative). The DCF still returns a number "
                    f"({result.value_per_share:,.2f}/share) because the growth "
                    "path and terminal value are applied mechanically."),
            interpretation=("a Gordon-growth DCF on a negative cash flow "
                            "compounds a loss; the output is arithmetic, not a "
                            "valuation. A multi-stage recovery model or a "
                            "different method is required, or the valuation "
                            "should be declared unavailable."),
            numbers={"base_cash_flow": inputs.base_cash_flow,
                     "value_per_share": result.value_per_share})
    return None


# --------------------------------------------------------------------------- #
# 8. negative / zero equity value (P5.1-closure Part 2)
# --------------------------------------------------------------------------- #
def _negative_equity(inputs: DCFInputs, result: DCFResult) -> RobustnessFinding | None:
    ev = result.enterprise_or_equity_value
    eq = result.equity_value
    if eq > 1e-6:
        return None
    if abs(eq) <= 1e-6:
        return RobustnessFinding(
            key="NEGATIVE_EQUITY_VALUE", severity=Severity.HIGH,
            sensitivity=Sensitivity.HIGH,
            headline="EQUITY VALUE ~ ZERO: enterprise value equals net debt",
            detail=(f"EV {ev:,.0f} - net debt {inputs.net_debt:,.0f} = "
                    f"{eq:,.0f}. Common-equity value is at the break-even point."),
            interpretation=("MATHEMATICALLY VALID, ECONOMICALLY LIMITED: at "
                            "these assumptions the whole enterprise is worth "
                            "roughly what it owes. The per-share figure is not "
                            "an ordinary intrinsic-value estimate."),
            numbers={"ev": ev, "net_debt": inputs.net_debt, "equity": eq},
            category=FailureCategory.ECONOMIC_MODEL_FAILURE)
    return RobustnessFinding(
        key="NEGATIVE_EQUITY_VALUE", severity=Severity.HIGH,
        sensitivity=Sensitivity.HIGH,
        headline="NEGATIVE EQUITY VALUE: enterprise value is below net debt",
        detail=(f"EV {ev:,.0f} - net debt {inputs.net_debt:,.0f} = equity "
                f"{eq:,.0f} ({result.value_per_share:,.2f}/share). The "
                "arithmetic is unchanged and correct; the result is negative "
                "because debt exceeds the discounted cash the firm produces."),
        interpretation=(
            "MATHEMATICALLY VALID, ECONOMICALLY LIMITED. EV is below net debt, "
            "so common-equity value is negative under current assumptions. "
            "This is NOT an ordinary bear-case intrinsic value: it says the "
            "capital structure, not just the growth outlook, is the binding "
            "constraint. Read it as 'equity is underwater on these inputs', "
            "not as a price target."),
        numbers={"ev": ev, "net_debt": inputs.net_debt, "equity": eq,
                 "value_per_share": result.value_per_share},
        category=FailureCategory.ECONOMIC_MODEL_FAILURE)


# --------------------------------------------------------------------------- #
# 9. valuation applicability (P5.1-closure Parts 5-10) - a categorical
# USABILITY status, NOT a confidence score. Rules are explicit and consume
# only evidence already computed. Correlated findings are grouped into
# ECONOMICALLY DISTINCT FAMILIES so one root cause cannot escalate twice.
# --------------------------------------------------------------------------- #
_APPLICABILITY_RULES = ModelConvention(
    "valuation_applicability_rules",
    "USABLE / USABLE_WITH_LIMITATIONS / LIMITED_APPLICABILITY",
    "LIMITED_APPLICABILITY when a distinct limitation FAMILY is in a "
    "materially-undermining state: (a) cash-flow representativeness - "
    "ANCHOR_SENSITIVITY HIGH *and* HISTORY_COMPARABILITY HIGH_CONCERN, or a "
    "negative base FCFF; (b) capital structure - negative equity value; "
    "(c) arithmetic integrity - a broken or scale-anomalous value bridge; "
    "(d) market-input evidence - WACC_INPUT_QUALITY INSUFFICIENT_EVIDENCE; "
    "(e) reverse-DCF - an inconsistent round trip. "
    "USABLE_WITH_LIMITATIONS when >=1 distinct family carries a MEDIUM "
    "concern (WACC LIMITED, TV dependence HIGH, anchor HIGH without "
    "HIGH_CONCERN history, reconstructed history) but none reaches the "
    "LIMITED bar. USABLE when no family flags a material concern.",
    "robustness._applicability",
    "sets ValuationRun.robustness.applicability; NEVER changes the DCF")


# Which finding key belongs to which economically-distinct limitation family.
# This is the SINGLE SOURCE of the family grouping (P4.6 convergence-family
# principle, reused): _applicability reads family names ONLY from here, never
# as literals, so several findings that map to one family (anchor + regime +
# comparability -> cash_flow_representativeness; five WACC sub-reasons -> one
# market_input_evidence) collapse to ONE family and cannot escalate
# applicability more than once.
_LIMITATION_FAMILY = {
    "ANCHOR_SENSITIVITY": "cash_flow_representativeness",
    "HISTORICAL_REGIME": "cash_flow_representativeness",
    "HISTORY_COMPARABILITY": "cash_flow_representativeness",
    "VALUATION_METHOD_LIMITATION": "cash_flow_representativeness",
    "ASSUMPTION_SENSITIVITY": "cash_flow_representativeness",
    "NEGATIVE_EQUITY_VALUE": "capital_structure",
    "VALUE_BRIDGE_INTEGRITY": "arithmetic_integrity",
    "WACC_INPUT_QUALITY": "market_input_evidence",
    "TERMINAL_VALUE_DEPENDENCE": "terminal_value",
    "REVERSE_DCF_CONSISTENCY": "reverse_dcf",
}


def _family(key: str) -> str:
    """The economically-distinct limitation family a finding key belongs to.

    KeyError on an unmapped key is deliberate: a new finding must be placed
    in a family explicitly, not silently treated as its own new concern.
    """
    return _LIMITATION_FAMILY[key]


def _applicability(findings: list[RobustnessFinding]) -> tuple[
        "Applicability", tuple[str, ...], tuple[str, ...], str]:
    by = {f.key: f for f in findings}
    limited_families: set[str] = set()
    medium_families: set[str] = set()
    reasons: list[str] = []

    anchor = by.get("ANCHOR_SENSITIVITY")
    hist = by.get("HISTORY_COMPARABILITY")
    anchor_high = anchor is not None and anchor.sensitivity is Sensitivity.HIGH
    hist_high_concern = hist is not None and hist.headline.endswith("HIGH_CONCERN")

    if anchor_high and hist_high_concern:
        # anchor sensitivity, historical regime and history comparability are
        # three MANIFESTATIONS of one instability - the family map folds all
        # three to the same name so the cluster escalates applicability once,
        # not three times (P4.6 convergence-family principle, Part 10).
        for _k in ("ANCHOR_SENSITIVITY", "HISTORY_COMPARABILITY",
                   "HISTORICAL_REGIME"):
            limited_families.add(_family(_k))
        reasons.append("the latest-FCFF anchor is a dominant assumption "
                       "(ANCHOR_SENSITIVITY HIGH) AND historical cash-flow "
                       "comparability is limited (HISTORY_COMPARABILITY "
                       "HIGH_CONCERN)")
    elif anchor_high:
        medium_families.add(_family("ANCHOR_SENSITIVITY"))
        reasons.append("the anchor choice is a large driver "
                       "(ANCHOR_SENSITIVITY HIGH) but the history does not "
                       "flag a comparability concern")

    if by.get("VALUATION_METHOD_LIMITATION") is not None:
        limited_families.add(_family("VALUATION_METHOD_LIMITATION"))
        reasons.append("base FCFF is negative - a Gordon perpetuity is not an "
                       "appropriate instrument")

    neq = by.get("NEGATIVE_EQUITY_VALUE")
    if neq is not None:
        limited_families.add(_family("NEGATIVE_EQUITY_VALUE"))
        reasons.append("equity value is negative or ~zero: EV is at or below "
                       "net debt")

    vb = by.get("VALUE_BRIDGE_INTEGRITY")
    if vb is not None and vb.severity is Severity.HIGH:
        limited_families.add(_family("VALUE_BRIDGE_INTEGRITY"))
        reasons.append(f"the value bridge is not clean ({vb.headline})")

    wq = by.get("WACC_INPUT_QUALITY")
    if wq is not None:
        if wq.headline.endswith("INSUFFICIENT_EVIDENCE") or wq.headline.endswith("BLOCKED"):
            limited_families.add(_family("WACC_INPUT_QUALITY"))
            reasons.append("a WACC input is unverified or missing "
                           f"({wq.headline})")
        elif wq.headline.endswith("LIMITED"):
            medium_families.add(_family("WACC_INPUT_QUALITY"))
            reasons.append("WACC rests on stale / extreme / undisclosed-"
                           "judgement inputs (WACC_INPUT_QUALITY LIMITED)")

    rc = by.get("REVERSE_DCF_CONSISTENCY")
    if rc is not None and "INCONSISTENT" in rc.headline:
        limited_families.add(_family("REVERSE_DCF_CONSISTENCY"))
        reasons.append("the forward/reverse round trip does not close")

    tv = by.get("TERMINAL_VALUE_DEPENDENCE")
    if tv is not None and tv.sensitivity is Sensitivity.HIGH:
        medium_families.add(_family("TERMINAL_VALUE_DEPENDENCE"))
        reasons.append(f"{tv.headline} - the perpetuity, not the forecast, "
                       "drives the value")

    if limited_families:
        state = Applicability.LIMITED_APPLICABILITY
    elif medium_families:
        state = Applicability.USABLE_WITH_LIMITATIONS
    else:
        state = Applicability.USABLE
        reasons.append("no limitation family flags a material concern")

    families = tuple(sorted(limited_families | medium_families))
    return state, tuple(reasons), families, ""


# --------------------------------------------------------------------------- #
# orchestrator
# --------------------------------------------------------------------------- #
def assess_robustness(run) -> RobustnessReport:
    """Read a finished ValuationRun and report how robust the valuation is.

    Never mutates ``run``. Re-runs the pure engine on copies only.
    """
    doc_id = getattr(run, "doc_id", "")
    result: DCFResult | None = getattr(run, "result", None)
    bridged = getattr(run, "bridged", None)
    inputs: DCFInputs | None = getattr(bridged, "inputs", None)
    if result is None or inputs is None:
        return RobustnessReport.not_assessed(
            doc_id, "no completed DCF result to assess")

    bound = getattr(bridged, "base_cash_flow_bound", None) or {}
    fcff_by_period = (bound.get("fcff_by_period")
                      if isinstance(bound, dict) and bound.get("available")
                      else None)
    reconstruction_note = (bound.get("note", "")
                           if isinstance(bound, dict) else "")
    tornado_ranges = getattr(bridged, "tornado_ranges", {}) or {}
    gshift = tornado_ranges.get("growth_rates_shift")
    growth_band = (abs(gshift[1]) + abs(gshift[0])) if gshift else None
    growth_pair = ((0.0, growth_band) if growth_band is not None else None)
    market = getattr(run, "market", {}) or {}
    forecast_years = getattr(run, "forecast_years", len(inputs.growth_rates))

    findings: list[RobustnessFinding] = []
    anchor_table, anchor_finding = _anchor_sensitivity(inputs, fcff_by_period)
    findings.append(anchor_finding)
    findings.append(_terminal_value_dependence(result))
    assum_finding, primary = _assumption_sensitivity(
        list(getattr(run, "tornado_rows", []) or []), result.value_per_share)
    findings.append(assum_finding)
    findings.append(_reverse_dcf_consistency(
        inputs, getattr(run, "market_price", None),
        getattr(run, "implied_growth", None)))
    findings.append(_value_bridge_integrity(inputs, result))
    findings.append(_historical_regime(fcff_by_period))
    findings.append(_history_comparability(
        fcff_by_period, growth_pair, reconstruction_note))
    findings.append(_wacc_input_quality(market, inputs))
    ml = _method_limitation(inputs, result)
    if ml is not None:
        findings.append(ml)
    neq = _negative_equity(inputs, result)
    if neq is not None:
        findings.append(neq)

    applicability, appl_reasons, families, _ = _applicability(findings)

    # P5.1-closure Part 16 - the central economic truth, machine-readable and
    # euphemism-free. Set only when the cash-flow family is the binding
    # limitation, so it names the actual reason rather than "medium confidence".
    conclusion = ""
    if applicability is Applicability.LIMITED_APPLICABILITY:
        if "cash_flow_representativeness" in families and _negative_equity(
                inputs, result) is None and inputs.base_cash_flow >= 0:
            conclusion = (
                "The valuation is mathematically valid, but the choice of the "
                "latest FCFF year is a dominant economic assumption and "
                "historical cash-flow comparability is limited.")
        elif "capital_structure" in families:
            conclusion = (
                "The valuation is mathematically valid, but enterprise value "
                "is at or below net debt, so common-equity value is negative "
                "under current assumptions.")
        elif inputs.base_cash_flow < 0:
            conclusion = (
                "The valuation is mathematically computable, but base FCFF is "
                "negative, so a Gordon perpetuity is not an economically "
                "appropriate instrument here.")
        else:
            conclusion = ("The valuation is mathematically valid but its "
                          "applicability is limited: " + appl_reasons[0] + ".")
    elif applicability is Applicability.USABLE_WITH_LIMITATIONS:
        conclusion = ("The valuation is mathematically valid and usable, with "
                      "stated limitations: " + "; ".join(appl_reasons) + ".")
    else:
        conclusion = ("The valuation is mathematically valid and no limitation "
                      "family flags a material economic concern.")

    notes = [
        "Robustness is diagnostic only: nothing here changed FCFF, WACC, the "
        "discount rate, terminal growth, EV, equity value or value per share.",
        f"VALUATION APPLICABILITY: {applicability.value}"
        + (f" ({len(families)} limitation famil"
           + ("y" if len(families) == 1 else "ies")
           + ": " + ", ".join(families) + ")" if families else ""),
        conclusion,
    ]
    high = [f for f in findings if f.severity is Severity.HIGH]
    if high:
        notes.append("HIGH-severity robustness findings: "
                     + ", ".join(f.key for f in high)
                     + ". The point estimate should be read as one scenario, "
                     "not a target.")
    return RobustnessReport(
        doc_id=doc_id, assessed=True, findings=tuple(findings),
        anchor_table=tuple(anchor_table), primary_driver=primary,
        notes=tuple(notes),
        applicability=applicability, applicability_reasons=appl_reasons,
        limitation_families=families, headline_conclusion=conclusion,
        model_conventions=model_conventions(inputs, forecast_years))
