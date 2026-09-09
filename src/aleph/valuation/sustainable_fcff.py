"""P6 - SUSTAINABLE / NORMALIZED FCFF FRAMEWORK.

STATUS: EXPERIMENTAL - NOT WIRED INTO THE BASE DCF. Diagnostic + scenario
only. The live valuation still anchors on the latest reconstructed FCFF
(bridge.py); promotion of anything here to the base case requires an ADR
(see ISSUES.md #33, P6).

WHAT THIS ANSWERS. Not "what number looks reasonable" but: can Aleph derive
a DEFENSIBLE sustainable FCFF from evidence already in the filings, while
keeping structural change distinct from a temporary distortion? Where the
evidence does not support it, the output is SUSTAINABLE_FCFF:
INSUFFICIENT_EVIDENCE - never a prettier point estimate.

SEVEN DISTINCT OBJECTS, never collapsed into one field:
  1 reported cash flow          - CFO, as the statement prints it
  2 reconstructed FCFF          - bridge's CFO + i(1-t) - capex - SBC
  3 normalized FCFF             - (2) with a SOURCED, FORMULA-BASED adjustment
  4 sustainable FCFF            - an evidence-supported run-rate RANGE
  5 transition-period FCFF      - a period the evidence says is mid-inflection
  6 analyst assumption          - a judgement an analyst entered explicitly
  7 model convention            - a method choice held across filers

METHOD. The decomposition is deterministic. For each disclosed period it
takes the WORKING-CAPITAL contribution to CFO as the sum of the
"change in <account>" reconciliation lines the extractor already pulls, and
separates CFO into (CFO - working capital) and (working capital). It then
VALIDATES that net income + every non-cash add-back + working capital
reproduces reported CFO within tolerance, and REFUSES the decomposition for
that period otherwise (fail closed). No LLM decides what is recurring or
one-off. No regression, no score, no smoothing. A range is built only from
explicit economic interpretations; otherwise INSUFFICIENT_EVIDENCE.

ISOLATION. Imports stdlib + dcf_engine + infra.units + (lazily) bridge only.
It receives the finished ValuationRun - its facts, ranges, bridged inputs
and per-period FCFF - and re-runs the PURE engine on COPIES for the scenario
layer. It never mutates the run and nothing it produces re-enters the base
valuation.
"""
from __future__ import annotations

import math
import re
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from statistics import median

from .dcf_engine import DCFConsistencyError, DCFInputs, run_dcf
from ..infra.units import resolve_scale

__all__ = [
    "EvidenceLevel",
    "AdjustmentClass",
    "RegimeStatus",
    "SustainableStatus",
    "FCFFAdjustment",
    "PeriodFCFF",
    "SustainableFCFF",
    "ScenarioValuation",
    "decompose_history",
    "classify_regime",
    "build_sustainable_range",
    "assess_sustainable_fcff",
    "sustainable_scenario_valuation",
    "RECON_TOL_FRAC",
    "RECON_TOL_ABS",
    "TIGHT_BAND_FRAC",
    "SPIKE_FRAC",
    "STRUCTURAL_MIN_PERIODS",
]

# --------------------------------------------------------------------------- #
# thresholds - conventions, each with a stated rationale. They gate a
# categorical label, never a number, and never the base DCF.
# --------------------------------------------------------------------------- #
# net income + non-cash add-backs + working capital must reproduce reported
# CFO to within this tolerance, or the decomposition is refused for that
# period. Rationale: the extractor is asked for EVERY reconciliation line; a
# residual above this means a line is missing or misclassified, and a
# decomposition that does not add up must not be used. The quantity actually
# depended on downstream - the sum of the "change in <account>" lines - is
# unambiguous to identify; this check confirms the extractor captured the
# whole reconciliation around it.
RECON_TOL_FRAC = 0.035         # 3.5% of the period's CFO
RECON_TOL_ABS = 75.0          # or $75m, whichever is larger

# A disclosed FCFF series whose spread is within this fraction of its median
# is treated as ONE established level (structural), not a trend to project.
TIGHT_BAND_FRAC = 0.25

# A single period more than this fraction from the median of the others,
# with the others themselves tight, is an isolated spike (temporary-looking).
SPIKE_FRAC = 1.00

# Fewer disclosed FCFF years than this: a pattern cannot be established.
STRUCTURAL_MIN_PERIODS = 3


class EvidenceLevel(str, Enum):
    OBSERVED = "OBSERVED"          # a disclosed per-period fact
    OVERRIDDEN = "OVERRIDDEN"      # an analyst override with a stated value
    INFERRED = "INFERRED"          # e.g. a flat interest value applied to all years
    MISSING = "MISSING"            # no fact and no fallback

    @property
    def rank(self) -> int:
        return {"OBSERVED": 0, "OVERRIDDEN": 1, "INFERRED": 2, "MISSING": 3}[self.value]


class AdjustmentClass(str, Enum):
    OPERATING_CASH_BEFORE_WC = "OPERATING_CASH_BEFORE_WC"   # CFO - working capital
    WORKING_CAPITAL = "WORKING_CAPITAL"                     # sum of change-in-<account>
    INTEREST_TAX_SHIELD = "INTEREST_TAX_SHIELD"             # i * (1 - tax)
    CAPEX = "CAPEX"
    SBC = "SBC"


class RegimeStatus(str, Enum):
    EVIDENCE_CONSISTENT_WITH_TEMPORARY = "EVIDENCE_CONSISTENT_WITH_TEMPORARY"
    EVIDENCE_CONSISTENT_WITH_STRUCTURAL_CHANGE = "EVIDENCE_CONSISTENT_WITH_STRUCTURAL_CHANGE"
    REGIME_UNCERTAIN = "REGIME_UNCERTAIN"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"


class SustainableStatus(str, Enum):
    SUPPORTED_RANGE = "SUPPORTED_RANGE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FCFFAdjustment:
    """One sourced line in the FCFF reconstruction for one period. The full
    period FCFF must be reconstructable exactly by summing these."""
    adjustment_id: str
    period: str
    classification: AdjustmentClass
    amount: float                       # millions, signed as it enters FCFF
    unit: str
    formula: str
    source_facts: tuple[str, ...]
    evidence_level: EvidenceLevel
    economic_rationale: str
    analyst_judgment: bool = False
    model_convention: bool = False


@dataclass(frozen=True)
class PeriodFCFF:
    period: str
    cfo: float
    interest_tax_shield: float
    capex: float                        # positive magnitude
    sbc: float                          # positive magnitude
    operating_cash_before_wc: float     # CFO - working_capital_total
    working_capital_total: float        # sum of change-in-<account> lines
    reconstructed_fcff: float           # == bridge's number for this period
    fcff_ex_working_capital: float      # reconstructed_fcff - working_capital_total
    components: tuple[FCFFAdjustment, ...]
    evidence: dict[str, str]            # component -> EvidenceLevel.value
    reconciles: bool
    residual: float                     # CFO - (NI + non-cash + WC); ~0 when reconciles

    @property
    def worst_evidence(self) -> EvidenceLevel:
        levels = [EvidenceLevel(v) for v in self.evidence.values()]
        return max(levels, key=lambda e: e.rank) if levels else EvidenceLevel.MISSING


@dataclass(frozen=True)
class ScenarioValuation:
    label: str                         # "current" | "sustainable_low" | ...
    base_fcff: float
    value_per_share: float | None
    rejected: str = ""
    delta_vs_current: float | None = None


@dataclass(frozen=True)
class SustainableFCFF:
    doc_id: str
    status: SustainableStatus
    regime: RegimeStatus
    periods: tuple[PeriodFCFF, ...]
    latest_period: str
    latest_reconstructed_fcff: float
    low: float | None
    central: float | None
    high: float | None
    low_basis: str
    central_basis: str
    high_basis: str
    reasons: tuple[str, ...]
    ledger: tuple[FCFFAdjustment, ...]
    reconciliation_ok: bool
    double_count_ok: bool
    notes: tuple[str, ...] = ()

    @staticmethod
    def insufficient(doc_id, regime, reasons, *, periods=(), ledger=(),
                     latest_period="", latest_fcff=math.nan,
                     reconciliation_ok=False, double_count_ok=True):
        return SustainableFCFF(
            doc_id=doc_id, status=SustainableStatus.INSUFFICIENT_EVIDENCE,
            regime=regime, periods=tuple(periods), latest_period=latest_period,
            latest_reconstructed_fcff=latest_fcff,
            low=None, central=None, high=None,
            low_basis="", central_basis="", high_basis="",
            reasons=tuple(reasons), ledger=tuple(ledger),
            reconciliation_ok=reconciliation_ok, double_count_ok=double_count_ok,
            notes=("SUSTAINABLE_FCFF: INSUFFICIENT_EVIDENCE - the framework "
                   "did not manufacture a range. The base DCF is unaffected.",))


# --------------------------------------------------------------------------- #
# fact plumbing
# --------------------------------------------------------------------------- #
_WC_MARKERS = (
    re.compile(r"\bchanges?\s+in\b", re.I),
    re.compile(r"\(change\)", re.I),
    re.compile(r"\bfunds\s+held\b", re.I),          # payment-processor float (DASH)
    re.compile(r"\bfunds\s+receivable\b", re.I),
)
# Lines on the cash-flow target that are NOT part of the net-income-to-CFO
# reconciliation add-backs: the CFO subtotal itself, cash balances, the
# net-change-in-cash line, capex (an investing line the extractor also
# pulls), and any investing/financing caption. SBC is deliberately NOT here -
# it is a genuine non-cash add-back and must count toward the reconciliation.
_NOT_A_RECON_LINE = (
    re.compile(r"provided by (\(used in\) )?operating activities", re.I),
    re.compile(r"used in operating activities", re.I),
    re.compile(r"beginning of period|end of period", re.I),
    re.compile(r"net (increase|decrease|change)\b.*\bin cash", re.I),
    re.compile(r"purchases of property|property and equipment|scooter fleet", re.I),
    re.compile(r"investing activities|financing activities", re.I),
    re.compile(r"payments for operating lease liabilities", re.I),
)


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", name or "").strip()


def _scaled(fact) -> float | None:
    s = resolve_scale(getattr(fact, "unit", None))
    return None if s is None else fact.value * s


def _by_period(facts, *, target_key, want):
    out: dict[str, list] = {}
    for f in facts:
        if not f.source or f.source.target_key != target_key or f.period is None:
            continue
        if want(_norm(f.name)):
            out.setdefault(f.period, []).append(f)
    return out


def _pick_net_income(facts) -> dict[str, float]:
    """Net income INCLUDING non-controlling interests, per period, scaled to
    millions - the figure the CFO reconciliation actually starts from."""
    incl = _by_period(
        facts, target_key="cash_flows",
        want=lambda n: "net income" in n.lower() or "net loss" in n.lower())
    result: dict[str, float] = {}
    for period, fs in incl.items():
        pref = [f for f in fs if "non-controlling" in f.name.lower()
                or "including" in f.name.lower()]
        chosen = pref[0] if pref else fs[0]
        v = _scaled(chosen)
        if v is not None:
            result[period] = v
    if result:
        return result
    ops = _by_period(
        facts, target_key="operations",
        want=lambda n: n.lower().startswith("total net income")
        or n.lower().startswith("total net loss")
        or "including non-controlling" in n.lower()
        or "including redeemable non-controlling" in n.lower())
    for period, fs in ops.items():
        v = _scaled(fs[0])
        if v is not None:
            result[period] = v
    return result


def _reconciliation_lines(facts):
    def keep(name: str) -> bool:
        low = name.lower()
        if any(rx.search(low) for rx in _NOT_A_RECON_LINE):
            return False
        if low.startswith("net income") or low.startswith("net loss"):
            return False
        return True
    return _by_period(facts, target_key="cash_flows", want=keep)


def _is_wc(name: str) -> bool:
    return any(rx.search(name) for rx in _WC_MARKERS)


# --------------------------------------------------------------------------- #
# PHASE 3 + 4 - per-period FCFF decomposition with provenance
# --------------------------------------------------------------------------- #
def decompose_history(ranges, tax, facts, fcff_by_period):
    """Reconstruct FCFF for every disclosed period AND split CFO into
    operating-cash-before-working-capital and the working-capital change,
    from the extracted reconciliation lines. Every component is a sourced
    FCFFAdjustment; the period FCFF is exactly their sum.
    """
    def obs(name):
        r = ranges.get(name)
        return {} if r is None else {o.period: (o.value, o.unit or "")
                                     for o in r.observations}

    def scaled(name):
        out = {}
        for p, (v, u) in obs(name).items():
            s = resolve_scale(u)
            if s is not None:
                out[p] = v * s
        return out

    cfo_p = scaled("operating_cash_flow")
    capex_p = scaled("capex")
    sbc_p = scaled("stock_based_compensation")
    interest_p = scaled("interest_expense")

    interest_range = ranges.get("interest_expense")
    interest_inferred = False
    if not interest_p and interest_range is not None and interest_range.base is not None:
        from .bridge import to_millions
        flat = abs(to_millions(interest_range))
        interest_p = {p: flat for p in cfo_p}
        interest_inferred = True

    ni_p = _pick_net_income(facts)
    recon_p = _reconciliation_lines(facts)

    periods = sorted(set(fcff_by_period))
    out, ledger = [], []

    for p in periods:
        cfo = cfo_p.get(p)
        capex = abs(capex_p[p]) if p in capex_p else None
        sbc = abs(sbc_p[p]) if p in sbc_p else None
        interest = abs(interest_p.get(p, 0.0))
        shield = interest * (1.0 - tax)

        ev = {
            "cfo": (EvidenceLevel.OBSERVED if cfo is not None else EvidenceLevel.MISSING).value,
            "capex": (EvidenceLevel.OBSERVED if capex is not None else EvidenceLevel.MISSING).value,
            "sbc": (EvidenceLevel.OBSERVED if sbc is not None else EvidenceLevel.MISSING).value,
            "interest": (EvidenceLevel.INFERRED if interest_inferred
                         else EvidenceLevel.OBSERVED if p in interest_p
                         else EvidenceLevel.MISSING).value,
        }

        lines = recon_p.get(p, [])
        wc_lines, noncash_lines = [], []
        for f in lines:
            v = _scaled(f)
            if v is None:
                continue
            (wc_lines if _is_wc(_norm(f.name)) else noncash_lines).append((f, v))
        wc_total = sum(v for _, v in wc_lines)
        noncash_total = sum(v for _, v in noncash_lines)
        ni = ni_p.get(p)

        recon_fcff = fcff_by_period[p]
        cfo_before_wc = (cfo - wc_total) if cfo is not None else math.nan

        if cfo is None or ni is None:
            reconciles, residual = False, math.nan
            ev["reconciliation"] = EvidenceLevel.MISSING.value
        else:
            residual = cfo - (ni + noncash_total + wc_total)
            tol = max(RECON_TOL_FRAC * abs(cfo), RECON_TOL_ABS)
            reconciles = abs(residual) <= tol
            ev["reconciliation"] = (EvidenceLevel.OBSERVED if reconciles
                                    else EvidenceLevel.MISSING).value

        fcff_ex_wc = (recon_fcff - wc_total) if math.isfinite(cfo_before_wc) else math.nan

        comps = []
        if reconciles and capex is not None and sbc is not None:
            comps = [
                FCFFAdjustment(
                    f"{p}:opcash_before_wc", p, AdjustmentClass.OPERATING_CASH_BEFORE_WC,
                    cfo_before_wc, "USD millions",
                    "reported CFO - sum(working-capital change lines)",
                    ("net cash provided by operating activities",
                     "(less) " + str(len(wc_lines)) + " working-capital change lines"),
                    EvidenceLevel.OBSERVED,
                    "cash the operations produced before any working-capital "
                    "swing; the part least exposed to timing"),
                FCFFAdjustment(
                    f"{p}:working_capital", p, AdjustmentClass.WORKING_CAPITAL,
                    wc_total, "USD millions",
                    "sum(change-in-<account> reconciliation lines)",
                    tuple(sorted({_norm(f.name) for f, _ in wc_lines})) or ("(none disclosed)",),
                    EvidenceLevel.OBSERVED,
                    "net working-capital release (+) or build (-); a timing "
                    "item whose run-rate depends on growth, not a profit"),
                FCFFAdjustment(
                    f"{p}:interest_tax_shield", p, AdjustmentClass.INTEREST_TAX_SHIELD,
                    shield, "USD millions", "abs(interest_expense) * (1 - tax)",
                    ("interest expense",), EvidenceLevel(ev["interest"]),
                    "removes the financing charge so FCFF is firm-level; the "
                    "tax rate is a held-identical model convention",
                    model_convention=True),
                FCFFAdjustment(
                    f"{p}:capex", p, AdjustmentClass.CAPEX, -capex, "USD millions",
                    "-abs(purchases of property and equipment)",
                    ("purchases of property and equipment",),
                    EvidenceLevel.OBSERVED,
                    "cash reinvestment; no maintenance/growth split is "
                    "disclosed by any filer in scope"),
                FCFFAdjustment(
                    f"{p}:sbc", p, AdjustmentClass.SBC, -sbc, "USD millions",
                    "-abs(stock-based compensation)", ("stock-based compensation",),
                    EvidenceLevel.OBSERVED,
                    "full cash cost (ADR 0002); unchanged from the live P5 "
                    "treatment - its CFO add-back sits inside opcash_before_wc",
                    model_convention=True),
            ]
            ledger.extend(comps)

        out.append(PeriodFCFF(
            period=p, cfo=cfo if cfo is not None else math.nan,
            interest_tax_shield=shield,
            capex=capex if capex is not None else math.nan,
            sbc=sbc if sbc is not None else math.nan,
            operating_cash_before_wc=cfo_before_wc,
            working_capital_total=wc_total,
            reconstructed_fcff=recon_fcff, fcff_ex_working_capital=fcff_ex_wc,
            components=tuple(comps), evidence=ev,
            reconciles=reconciles, residual=residual))

    return out, ledger


# --------------------------------------------------------------------------- #
# PHASE 5 - structural vs temporary, deterministic
# --------------------------------------------------------------------------- #
def classify_regime(periods):
    reasons = []
    usable = [p for p in periods if math.isfinite(p.reconstructed_fcff)]
    if len(usable) < STRUCTURAL_MIN_PERIODS:
        return RegimeStatus.INSUFFICIENT_HISTORY, [
            f"only {len(usable)} reconstructable FCFF year(s); "
            f"{STRUCTURAL_MIN_PERIODS} are needed to establish a pattern"]

    vals = [p.reconstructed_fcff for p in usable]
    if any(v < 0 for v in vals) and any(v > 0 for v in vals):
        reasons.append("the FCFF series changes sign - a loss-to-profit "
                       "inflection; structural improvement and an unfinished "
                       "ramp look identical here")
        return RegimeStatus.REGIME_UNCERTAIN, reasons

    if any(p.worst_evidence.rank >= EvidenceLevel.MISSING.rank for p in usable):
        reasons.append("at least one period has a missing or non-reconciling "
                       "component; the series is not homogeneous")
        return RegimeStatus.REGIME_UNCERTAIN, reasons

    med = median(vals)
    spread = (max(vals) - min(vals)) / abs(med) if med else math.inf
    if all(v != 0 for v in vals) and spread <= TIGHT_BAND_FRAC:
        reasons.append(f"the disclosed FCFF years sit within {spread:.0%} of "
                       "their median - one established level")
        return RegimeStatus.EVIDENCE_CONSISTENT_WITH_STRUCTURAL_CHANGE, reasons

    prior, last = vals[:-1], vals[-1]
    if len(prior) >= 2 and all(v != 0 for v in prior):
        pmed = median(prior)
        ptight = ((max(prior) - min(prior)) / abs(pmed) <= TIGHT_BAND_FRAC
                  if pmed else False)
        # UPWARD isolated spike only. An unusually GOOD latest year is the
        # anchor risk P6 exists to catch. An unusually BAD latest year already
        # makes the valuation conservative, and labelling it "temporary" would
        # be arguing the company is better than it looks - which the brief
        # forbids without filing evidence.
        if ptight and pmed and (last - pmed) / abs(pmed) > SPIKE_FRAC:
            reasons.append(f"the prior years cluster near {pmed:,.0f} and the "
                           f"latest is {(last - pmed) / abs(pmed):+.0%} above "
                           "that - an isolated move, not yet a trend")
            return RegimeStatus.EVIDENCE_CONSISTENT_WITH_TEMPORARY, reasons

    rising = all(b > a for a, b in zip(vals, vals[1:]))
    falling = all(b < a for a, b in zip(vals, vals[1:]))
    if rising or falling:
        reasons.append(
            f"FCFF moves monotonically {'up' if rising else 'down'} across "
            f"every disclosed year ({', '.join(f'{v:,.0f}' for v in vals)}); "
            "a persistent directional change, but the numbers cannot say "
            "whether the latest level is the new run-rate or a waypoint")
        return RegimeStatus.REGIME_UNCERTAIN, reasons

    reasons.append("no deterministic structural or temporary pattern is "
                   "identifiable in the disclosed FCFF series")
    return RegimeStatus.REGIME_UNCERTAIN, reasons


# --------------------------------------------------------------------------- #
# PHASE 13 - anti-double-counting
# --------------------------------------------------------------------------- #
def _double_count_ok(ledger):
    """The five component classes must be present at most once per period,
    and the components must sum to reconstructed FCFF (checked by the caller
    per period). A source fact may not appear in two classes that would both
    subtract it."""
    problems = []
    by_period = {}
    for a in ledger:
        by_period.setdefault(a.period, []).append(a)
    for period, adjs in by_period.items():
        classes = [a.classification for a in adjs]
        for c in set(classes):
            if classes.count(c) > 1:
                problems.append(f"{period}: {c.value} appears "
                                f"{classes.count(c)} times")
        # capex / SBC facts must not also be inside a positive component
        neg = {f.lower() for a in adjs
               if a.classification in (AdjustmentClass.CAPEX, AdjustmentClass.SBC)
               for f in a.source_facts}
        pos = {f.lower() for a in adjs
               if a.amount > 0 for f in a.source_facts}
        overlap = {x for x in neg & pos
                   if "property and equipment" in x or "stock-based" in x}
        if overlap:
            problems.append(f"{period}: {sorted(overlap)} both added and subtracted")
    return (not problems), problems


# --------------------------------------------------------------------------- #
# PHASE 6 - the sustainable FCFF range, or INSUFFICIENT_EVIDENCE
# --------------------------------------------------------------------------- #
def build_sustainable_range(periods, regime):
    reasons = []
    usable = [p for p in periods if math.isfinite(p.reconstructed_fcff)]

    if regime is RegimeStatus.INSUFFICIENT_HISTORY:
        return (SustainableStatus.INSUFFICIENT_EVIDENCE, None, None, None,
                "", "", "", ["fewer than three reconstructable FCFF years"])

    if not usable:
        return (SustainableStatus.INSUFFICIENT_EVIDENCE, None, None, None,
                "", "", "", ["no reconstructable FCFF period"])

    latest = usable[-1]
    if not math.isfinite(latest.fcff_ex_working_capital):
        return (SustainableStatus.INSUFFICIENT_EVIDENCE, None, None, None,
                "", "", "", ["fcff_ex_working_capital is not computable for "
                             "the latest period"])
    # A non-reconciling latest period always carries evidence['reconciliation']
    # == MISSING, so this one check also covers "the latest period's CFO does
    # not reconcile" - a separate `reconciles` clause was redundant.
    if latest.worst_evidence.rank >= EvidenceLevel.MISSING.rank:
        return (SustainableStatus.INSUFFICIENT_EVIDENCE, None, None, None,
                "", "", "", ["a material component of the latest period is "
                             "missing, or the latest period's CFO does not "
                             "reconcile to net income + non-cash + working "
                             "capital within tolerance"])

    ex_wc = latest.fcff_ex_working_capital
    as_reported = latest.reconstructed_fcff
    wc_series = [p.working_capital_total for p in usable if p.reconciles]
    # A "recurring" working-capital level cannot be claimed from one year.
    if len(wc_series) < 2:
        return (SustainableStatus.INSUFFICIENT_EVIDENCE, None, None, None,
                "", "", "", ["fewer than two disclosed periods reconcile, so a "
                             "recurring working-capital level cannot be "
                             "established; no range is produced"])
    wc_med = median(wc_series)

    # HIGH is always the latest year exactly as the filing supports it - the
    # framework never claims MORE than the disclosed FCFF. LOW strips the
    # working-capital contribution only when that is the more conservative
    # reading (a WC tailwind). CENTRAL rebuilds the latest year with the
    # working-capital contribution set to its multi-year MEDIAN, then clamps
    # into [LOW, HIGH].
    high = as_reported
    low = min(as_reported, ex_wc)
    central = min(max(ex_wc + wc_med, low), high)

    low_basis = (
        "LOW - conservative: the latest year's FCFF with its working-capital "
        "contribution removed, when that lowers the figure (a WC tailwind). "
        f"min(reconstructed_fcff, fcff_ex_working_capital)({latest.period}) = {low:,.0f}")
    central_basis = (
        "CENTRAL - evidence-supported: latest-year FCFF ex working capital "
        f"PLUS the MEDIAN disclosed working-capital contribution ({wc_med:,.0f}) "
        "across the reconstructable years; the recurring part of working "
        f"capital taken at its multi-year median, not the latest peak, then "
        f"clamped to [LOW, HIGH]. = {central:,.0f}")
    high_basis = (
        "HIGH - as disclosed: the latest year's reconstructed FCFF exactly as "
        f"the filing supports it, working capital included. "
        f"reconstructed_fcff({latest.period}) = {high:,.0f}")

    if regime is RegimeStatus.REGIME_UNCERTAIN:
        reasons.append("regime is REGIME_UNCERTAIN, so CENTRAL is an "
                       "interpretation, not a single answer; the LOW-HIGH "
                       "band is wide on purpose")
    if latest.evidence.get("interest") == EvidenceLevel.INFERRED.value:
        reasons.append("interest expense is a flat inferred value, not a "
                       "per-period disclosure; its tax shield is small but "
                       "note the dependency")
    if abs(high - low) < 1.0:
        reasons.append("the latest year's working capital was a net DRAG, not "
                       "a tailwind; no downward sustainable adjustment applies "
                       "and the range collapses to the as-reported FCFF")
    if wc_med < 0:
        reasons.append("the median historical working-capital movement is a "
                       "net USE of cash; no sustainable working-capital "
                       "tailwind is assumed in CENTRAL")

    return (SustainableStatus.SUPPORTED_RANGE, low, central, high,
            low_basis, central_basis, high_basis, reasons)


# --------------------------------------------------------------------------- #
# orchestrator
# --------------------------------------------------------------------------- #
def assess_sustainable_fcff(run) -> SustainableFCFF:
    """Read a finished ValuationRun and produce the sustainable-FCFF analysis.
    Never mutates the run. Never feeds anything back into the base valuation.
    """
    doc_id = getattr(run, "doc_id", "")
    bridged = getattr(run, "bridged", None)
    bound = getattr(bridged, "base_cash_flow_bound", None) or {}
    if not (isinstance(bound, dict) and bound.get("available")):
        return SustainableFCFF.insufficient(
            doc_id, RegimeStatus.INSUFFICIENT_HISTORY,
            ("the pipeline could not reconstruct FCFF for two or more "
             "disclosed periods (bridge.base_cash_flow_bound unavailable)",))

    fcff_by_period = dict(bound.get("fcff_by_period") or {})
    ranges = getattr(run, "ranges", {}) or {}
    facts = list(getattr(run, "facts", []) or [])

    tax_r = ranges.get("effective_tax_rate")
    if tax_r is None or tax_r.base is None:
        return SustainableFCFF.insufficient(
            doc_id, RegimeStatus.INSUFFICIENT_HISTORY,
            ("no effective tax rate is available to build the interest shield",))
    tax = tax_r.base / 100.0 if tax_r.base > 1.0 else tax_r.base

    periods, ledger = decompose_history(ranges, tax, facts, fcff_by_period)
    latest_period = periods[-1].period if periods else ""
    latest_fcff = periods[-1].reconstructed_fcff if periods else math.nan

    # per-period ledger sum check (Phase 13)
    ledger_sums = True
    for p in periods:
        if p.components:
            s = sum(c.amount for c in p.components)
            if abs(s - p.reconstructed_fcff) > 1.0:
                ledger_sums = False
    double_count_ok, dc_problems = _double_count_ok(ledger)
    double_count_ok = double_count_ok and ledger_sums

    regime, regime_reasons = classify_regime(periods)

    # Informational: did EVERY disclosed period reconcile? The gate that
    # actually blocks a range - latest period reconciles, and at least two
    # periods reconcile so a recurring working-capital level can be formed -
    # lives in build_sustainable_range, where it is unit-tested directly.
    reconciliation_ok = bool(periods) and all(p.reconciles for p in periods) \
        and len(periods) >= 2

    if not double_count_ok:
        return SustainableFCFF.insufficient(
            doc_id, regime,
            tuple(regime_reasons) + ("double counting could not be ruled out: "
                                     + "; ".join(dc_problems or ["ledger does "
                                     "not sum to reconstructed FCFF"]),),
            periods=periods, ledger=ledger, latest_period=latest_period,
            latest_fcff=latest_fcff, reconciliation_ok=reconciliation_ok,
            double_count_ok=False)

    status, low, central, high, lb, cb, hb, range_reasons = \
        build_sustainable_range(periods, regime)

    if status is SustainableStatus.INSUFFICIENT_EVIDENCE:
        return SustainableFCFF.insufficient(
            doc_id, regime, tuple(regime_reasons) + tuple(range_reasons),
            periods=periods, ledger=ledger, latest_period=latest_period,
            latest_fcff=latest_fcff, reconciliation_ok=reconciliation_ok,
            double_count_ok=True)

    notes = [
        "EXPERIMENTAL: this range does NOT change the base DCF, which still "
        f"anchors on the latest reconstructed FCFF ({latest_fcff:,.0f}).",
        f"REGIME: {regime.value}.",
        "LOW / CENTRAL / HIGH are explicit economic interpretations, NOT a "
        "statistical confidence interval.",
    ]
    return SustainableFCFF(
        doc_id=doc_id, status=status, regime=regime, periods=tuple(periods),
        latest_period=latest_period, latest_reconstructed_fcff=latest_fcff,
        low=low, central=central, high=high,
        low_basis=lb, central_basis=cb, high_basis=hb,
        reasons=tuple(regime_reasons) + tuple(range_reasons),
        ledger=tuple(ledger), reconciliation_ok=True, double_count_ok=True,
        notes=tuple(notes))


# --------------------------------------------------------------------------- #
# PHASE 8 - sustainable-anchor scenario valuation (pure engine, on copies)
# --------------------------------------------------------------------------- #
def sustainable_scenario_valuation(inputs: DCFInputs, sust: SustainableFCFF):
    """Re-run the PURE DCF engine at the current anchor and at each
    sustainable-FCFF case. EVERYTHING except base_cash_flow is held fixed:
    WACC, terminal growth, horizon, growth fade, shares, net debt. The
    output isolates the valuation effect of the FCFF interpretation ALONE.
    """
    def value_at(base):
        trial = deepcopy(inputs)
        trial.base_cash_flow = base
        trial.assumptions = []
        try:
            return run_dcf(trial).value_per_share, ""
        except DCFConsistencyError as exc:
            return None, str(exc)

    cur_v, cur_rej = value_at(inputs.base_cash_flow)
    rows = [ScenarioValuation("current", inputs.base_cash_flow, cur_v, cur_rej, 0.0)]
    if sust.status is not SustainableStatus.SUPPORTED_RANGE:
        return rows
    for label, base in (("sustainable_low", sust.low),
                        ("sustainable_central", sust.central),
                        ("sustainable_high", sust.high)):
        v, rej = value_at(base)
        delta = (v - cur_v) if (v is not None and cur_v is not None) else None
        rows.append(ScenarioValuation(label, base, v, rej, delta))
    return rows
