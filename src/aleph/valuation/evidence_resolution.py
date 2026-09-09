"""P10.5 - EVIDENCE RESOLUTION, WORKING-CAPITAL ECONOMIC CLASSIFICATION &
UNRESOLVED-DIVERGENCE AUDIT.

STATUS: EXPERIMENTAL. Observational / evidentiary only. It is NOT imported by
pipeline.py, it changes NO live valuation number, it promotes nothing, and
NONE of its functions takes a market price - the signatures make price
leakage impossible, not merely unlikely.

THE QUESTION P10 left open: can Aleph resolve the remaining LIVE / P6 / P9
disagreements from the filing evidence that already exists, or is the
uncertainty genuinely DISCLOSURE_BOUND? A DISCLOSURE_BOUND answer is a
successful analytical output here, not a failure.

WHAT IT DOES (reads a finished ValuationRun; re-uses P6/P8/P9/P10 primitives):
  - a per-line WORKING-CAPITAL evidence map (caption -> normalized category,
    cash direction, signed amount, recurrence evidence, economic
    interpretation, disclosure status), built on P8's caption mapper;
  - a multi-dimension PERSISTENCE profile per WC line (latest / prior /
    median / mean / sign consistency / magnitude stability / revenue-, CFO-
    and FCFF-scaled history) - never collapsed into one score;
  - an INSURANCE / self-insurance FLOAT audit: recurring vs temporary vs
    ambiguous vs disclosure-bound;
  - a CFO reconciliation ATTRIBUTION table - which disclosed captions carry
    the cash movement, which recur, which are timing;
  - the UBER_FY2024 "$2,374m latest vs ~$400m median" hypothesis test;
  - LYFT's operating-cash basis with working capital removed;
  - a complete deterministic sequential bridge LIVE -> P9 for any filer,
    separating ARITHMETICALLY_RECONCILED from ECONOMICALLY_EXPLAINED;
  - a tax-evidence ladder (statutory / effective-disclosed / cash-tax /
    normalized / disclosure-bound) - the 21% convention is NOT changed, only
    graded;
  - FACT vs ECONOMIC_INTERPRETATION vs MODEL_ASSUMPTION tagging;
  - a small DISCLOSURE_BOUNDARY engine (RESOLVED / PARTIALLY_RESOLVED /
    DISCLOSURE_BOUND).

NO LLM. NO ML. NO new valuation model. NO new score. NO BUY/SELL. NO change
to the LIVE DCF. NO promotion of P6/P9/P10.
"""
from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "RecurrenceEvidence",
    "DisclosureStatus",
    "InsuranceVerdict",
    "PersistenceClass",
    "TaxEvidenceClass",
    "TaxNormalizationVerdict",
    "EpistemicClass",
    "BoundaryVerdict",
    "HypothesisStatus",
    "EconomicallyExplained",
    "WorkingCapitalEvidence",
    "PersistenceProfile",
    "InsuranceAudit",
    "CFOAttributionRow",
    "CFOAttribution",
    "HypothesisTest",
    "BridgeStep",
    "SequentialBridge",
    "TaxEvidence",
    "EpistemicTag",
    "DisclosureBoundary",
    "EvidenceResolutionReport",
    "working_capital_evidence_map",
    "persistence_profiles",
    "insurance_float_audit",
    "cfo_attribution",
    "wc_level_hypotheses",
    "operating_basis_without_wc",
    "sequential_bridge_live_to_p9",
    "tax_evidence",
    "epistemic_tags",
    "disclosure_boundaries",
    "assess_evidence_resolution",
    "STATUTORY_TAX",
    "MULTI_YEAR_MIN",
    "STABLE_MAGNITUDE_FRAC",
    "VOLATILE_MAGNITUDE_FRAC",
    "SIGN_CONSISTENCY_RECURRENT",
    "IMMATERIAL_FCFF_FRAC",
]

# The held-identical model convention (LIVE + P9). NOT changed here - graded.
STATUTORY_TAX = 0.21

# --- deterministic classification thresholds, each with a stated rationale --- #
# A recurring level cannot be claimed from one observation; two like-signed
# observations are a "single-year" pattern; three or more are "multi-year".
MULTI_YEAR_MIN = 3
# magnitude stability = min(|v|)/max(|v|) over the like-signed periods.
# >= this: the level is stable enough to call persistent.
STABLE_MAGNITUDE_FRAC = 0.50
# below this: the level swings by more than ~5x - "high variance".
VOLATILE_MAGNITUDE_FRAC = 0.20
# fraction of periods that must share the modal sign to be "recurrent" at all.
SIGN_CONSISTENCY_RECURRENT = 0.66
# a bridge residual within this fraction of LIVE FCFF is immaterial.
IMMATERIAL_FCFF_FRAC = 0.02


class RecurrenceEvidence(str, Enum):
    EXPLICIT_RECURRING = "EXPLICIT_RECURRING"
    EXPLICIT_ONE_OFF = "EXPLICIT_ONE_OFF"
    MULTI_YEAR_REPEATED = "MULTI_YEAR_REPEATED"
    SINGLE_YEAR_OBSERVATION = "SINGLE_YEAR_OBSERVATION"
    ECONOMICALLY_AMBIGUOUS = "ECONOMICALLY_AMBIGUOUS"
    NOT_DISCLOSED = "NOT_DISCLOSED"


class DisclosureStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    DISCLOSURE_BOUND = "DISCLOSURE_BOUND"


class InsuranceVerdict(str, Enum):
    RECURRING_SUPPORTED = "RECURRING_SUPPORTED"
    TEMPORARY_SUPPORTED = "TEMPORARY_SUPPORTED"
    MIXED_SUPPORTED = "MIXED_SUPPORTED"
    AMBIGUOUS = "AMBIGUOUS"
    DISCLOSURE_BOUND = "DISCLOSURE_BOUND"


class PersistenceClass(str, Enum):
    STRONGLY_PERSISTENT = "STRONGLY_PERSISTENT"
    PERSISTENT_BUT_VOLATILE = "PERSISTENT_BUT_VOLATILE"
    RECURRENT_WITH_HIGH_VARIANCE = "RECURRENT_WITH_HIGH_VARIANCE"
    NON_PERSISTENT = "NON_PERSISTENT"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"


class TaxEvidenceClass(str, Enum):
    STATUTORY_ONLY = "STATUTORY_ONLY"
    EFFECTIVE_DISCLOSED = "EFFECTIVE_DISCLOSED"
    CASH_TAX_SUPPORTED = "CASH_TAX_SUPPORTED"
    NORMALIZED_TAX_SUPPORTED = "NORMALIZED_TAX_SUPPORTED"


class TaxNormalizationVerdict(str, Enum):
    NORMALIZED_TAX_SUPPORTED = "NORMALIZED_TAX_SUPPORTED"
    TAX_NORMALIZATION_DISCLOSURE_BOUND = "TAX_NORMALIZATION_DISCLOSURE_BOUND"


class EpistemicClass(str, Enum):
    FACT = "FACT"                                   # disclosed / mechanically derived
    ECONOMIC_INTERPRETATION = "ECONOMIC_INTERPRETATION"
    MODEL_ASSUMPTION = "MODEL_ASSUMPTION"


class BoundaryVerdict(str, Enum):
    RESOLVED = "RESOLVED"
    PARTIALLY_RESOLVED = "PARTIALLY_RESOLVED"
    DISCLOSURE_BOUND = "DISCLOSURE_BOUND"


class HypothesisStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    RULED_OUT = "RULED_OUT"
    UNTESTABLE = "UNTESTABLE"


class EconomicallyExplained(str, Enum):
    FULLY = "FULLY"
    PARTIAL = "PARTIAL"
    NO = "NO"


# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class WorkingCapitalEvidence:
    company: str
    filing: str
    period: str
    caption: str
    normalized_category: str
    cash_flow_direction: str            # INFLOW / OUTFLOW / NEUTRAL
    absolute_amount: float
    signed_amount: float
    evidence_level: str                 # FACT (always here - a disclosed line)
    recurrence_evidence: RecurrenceEvidence
    economic_interpretation: str
    disclosure_status: DisclosureStatus
    source_reference: str


@dataclass(frozen=True)
class PersistenceProfile:
    name: str
    periods: tuple[str, ...]
    latest: float | None
    prior: float | None
    median: float | None
    mean: float | None
    sign_consistency: float | None      # fraction sharing the modal sign
    magnitude_stability: float | None   # min|v| / max|v| over modal-sign periods
    revenue_scaled_history: tuple[float, ...]
    cfo_scaled_history: tuple[float, ...]
    fcff_scaled_history: tuple[float, ...]
    classification: PersistenceClass
    rule: str


@dataclass(frozen=True)
class InsuranceAudit:
    company: str
    changes_by_period: dict
    sign_consistency: float | None
    years_like_signed: int
    magnitude_stability: float | None
    mechanism_disclosed: bool
    rollforward_disclosed: bool
    verdict: InsuranceVerdict
    rationale: str


@dataclass(frozen=True)
class CFOAttributionRow:
    category: str
    raw_amount: float
    signed_amount: float
    fcff_impact: float
    revenue_scaled: float | None
    evidence_level: str
    recurrence: RecurrenceEvidence


@dataclass(frozen=True)
class CFOAttribution:
    period: str
    cfo: float | None
    rows: tuple[CFOAttributionRow, ...]
    majority_categories: tuple[str, ...]
    residual: float | None


@dataclass(frozen=True)
class HypothesisTest:
    hypothesis: str
    supporting_evidence: tuple[str, ...]
    contradicting_evidence: tuple[str, ...]
    status: HypothesisStatus


@dataclass(frozen=True)
class BridgeStep:
    order: int
    name: str
    start: float
    delta: float
    end: float
    kind: str                           # ACCOUNTING / TAX / WORKING_CAPITAL / METHODOLOGY / RESIDUAL
    note: str


@dataclass(frozen=True)
class SequentialBridge:
    doc_id: str
    live_fcff: float | None
    p9_base_fcff: float | None
    steps: tuple[BridgeStep, ...]
    residual: float | None
    residual_kind: str
    arithmetically_reconciled: bool
    economically_explained: EconomicallyExplained
    dominant_cause: str
    methodology_pct_of_fcff: float | None
    note: str


@dataclass(frozen=True)
class TaxEvidence:
    company: str
    statutory: float
    effective_by_period: dict
    cash_taxes_paid_disclosed: bool
    deferred_tax_by_period: dict
    normalized_rate_derivable: bool
    classification: TaxEvidenceClass
    normalization_verdict: TaxNormalizationVerdict
    rationale: str


@dataclass(frozen=True)
class EpistemicTag:
    item: str
    epistemic_class: EpistemicClass
    basis: str


@dataclass(frozen=True)
class DisclosureBoundary:
    question: str
    available_evidence: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    possible_hypotheses: tuple[str, ...]
    hypotheses_ruled_out: tuple[str, ...]
    hypotheses_remaining: tuple[str, ...]
    verdict: BoundaryVerdict


@dataclass(frozen=True)
class EvidenceResolutionReport:
    doc_id: str
    wc_map: tuple[WorkingCapitalEvidence, ...]
    persistence: tuple[PersistenceProfile, ...]
    insurance: InsuranceAudit
    cfo_attribution: tuple[CFOAttribution, ...]
    wc_level_hypotheses: tuple[HypothesisTest, ...]
    operating_basis_without_wc: dict
    bridge: SequentialBridge
    tax: TaxEvidence
    epistemic_tags: tuple[EpistemicTag, ...]
    boundaries: tuple[DisclosureBoundary, ...]
    model_consequence: dict
    architectural_decision: str
    verdict: str
    notes: tuple[str, ...] = field(default_factory=tuple)


# --------------------------------------------------------------------------- #
# fact plumbing (re-uses P8's caption mapper - the single source of truth)
# --------------------------------------------------------------------------- #
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _scaled(f) -> float | None:
    from ..infra.units import resolve_scale
    s = resolve_scale(getattr(f, "unit", None))
    return None if s is None else f.value * s


_RECURRING_LANG = re.compile(
    r"\brecurring\b|each (year|period|quarter)|annually|every (year|period)|"
    r"in the ordinary course|consistent with (prior|historical)", re.I)
_ONE_OFF_LANG = re.compile(
    r"one-?time|non-?recurring|unusual|restructuring|settlement|"
    r"insurance recovery|tax refund|divestiture|special (payment|charge|item)|"
    r"gain on sale|impairment|lease termination|revaluation", re.I)


def _revenue(run) -> dict:
    out: dict = {}
    for f in getattr(run, "facts", []) or []:
        if (f.source and f.source.target_key == "operations" and f.period
                and _norm(f.name).lower().startswith("total revenue")):
            v = _scaled(f)
            if v is not None:
                out.setdefault(f.period, v)
    return out


def _cfo_by_period(run) -> dict:
    r = (getattr(run, "ranges", {}) or {}).get("operating_cash_flow")
    if r is None:
        return {}
    from ..infra.units import resolve_scale
    s = resolve_scale(r.unit)
    return {o.period: (o.value * s if s is not None else o.value)
            for o in r.observations}


def _fcff_by_period(run) -> dict:
    bound = getattr(getattr(run, "bridged", None), "base_cash_flow_bound", None) or {}
    if isinstance(bound, dict) and bound.get("available"):
        return dict(bound.get("fcff_by_period") or {})
    return {}


def _wc_facts(run):
    """Every extracted cash-flow line P8 maps to WORKING_CAPITAL, grouped by
    base caption -> {period: (signed_millions, subcategory, quote)}."""
    from .evidence_depth import map_reconciliation_caption, Category
    out: dict = {}
    for f in getattr(run, "facts", []) or []:
        if not f.source or f.source.target_key != "cash_flows" or not f.period:
            continue
        m = map_reconciliation_caption(_norm(f.name))
        if m.category is not Category.WORKING_CAPITAL:
            continue
        v = _scaled(f)
        if v is None:
            continue
        base = re.sub(r"\s+FY\d{4}$", "", _norm(f.name))
        sub = (m.wc_subcategory.value if m.wc_subcategory else "WC_UNCLASSIFIED")
        out.setdefault(base, {})[f.period] = (v, sub, getattr(f, "quote", "") or "")
    return out


# --------------------------------------------------------------------------- #
# deterministic recurrence + persistence rules (pure - mutation targets)
# --------------------------------------------------------------------------- #
def _modal_sign(values) -> int:
    pos = sum(1 for v in values if v > 0)
    neg = sum(1 for v in values if v < 0)
    return 1 if pos >= neg else -1


def _sign_consistency(values) -> float | None:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    s = _modal_sign(vals)
    return sum(1 for v in vals if (v > 0) == (s > 0) and v != 0) / len(vals)


def _magnitude_stability(values) -> float | None:
    vals = [abs(v) for v in values if v is not None and v != 0]
    s = _modal_sign([v for v in values if v is not None])
    like = [abs(v) for v in values if v is not None and v != 0 and (v > 0) == (s > 0)]
    use = like or vals
    if not use or max(use) == 0:
        return None
    return min(use) / max(use)


def classify_recurrence(values, quotes=()) -> RecurrenceEvidence:
    """Deterministic. Explicit language wins; then the multi-year sign / repeat
    pattern; else single-year or ambiguous."""
    text = " ".join(quotes)
    if _ONE_OFF_LANG.search(text):
        return RecurrenceEvidence.EXPLICIT_ONE_OFF
    if _RECURRING_LANG.search(text):
        return RecurrenceEvidence.EXPLICIT_RECURRING
    vals = [v for v in values if v is not None and math.isfinite(v)]
    if not vals:
        return RecurrenceEvidence.NOT_DISCLOSED
    sc = _sign_consistency(vals) or 0.0
    if len(vals) >= MULTI_YEAR_MIN and sc == 1.0:
        return RecurrenceEvidence.MULTI_YEAR_REPEATED
    if len(vals) >= 2 and sc == 1.0:
        return RecurrenceEvidence.SINGLE_YEAR_OBSERVATION
    if sc < SIGN_CONSISTENCY_RECURRENT:
        return RecurrenceEvidence.ECONOMICALLY_AMBIGUOUS
    # like-signed majority but not unanimous, >=3 periods
    return (RecurrenceEvidence.MULTI_YEAR_REPEATED if len(vals) >= MULTI_YEAR_MIN
            else RecurrenceEvidence.SINGLE_YEAR_OBSERVATION)


def classify_persistence(values) -> tuple[PersistenceClass, str]:
    vals = [v for v in values if v is not None and math.isfinite(v)]
    if len(vals) < MULTI_YEAR_MIN:
        return (PersistenceClass.INSUFFICIENT_HISTORY,
                f"fewer than {MULTI_YEAR_MIN} periods")
    sc = _sign_consistency(vals) or 0.0
    ms = _magnitude_stability(vals) or 0.0
    if sc < SIGN_CONSISTENCY_RECURRENT:
        return (PersistenceClass.NON_PERSISTENT,
                f"sign consistency {sc:.0%} < {SIGN_CONSISTENCY_RECURRENT:.0%}")
    if sc == 1.0 and ms >= STABLE_MAGNITUDE_FRAC:
        return (PersistenceClass.STRONGLY_PERSISTENT,
                f"same sign every period, magnitude stable "
                f"(min/max {ms:.2f} >= {STABLE_MAGNITUDE_FRAC})")
    if sc == 1.0 and ms >= VOLATILE_MAGNITUDE_FRAC:
        return (PersistenceClass.PERSISTENT_BUT_VOLATILE,
                f"same sign every period, magnitude min/max {ms:.2f} "
                f"in [{VOLATILE_MAGNITUDE_FRAC}, {STABLE_MAGNITUDE_FRAC})")
    return (PersistenceClass.RECURRENT_WITH_HIGH_VARIANCE,
            f"like-signed {sc:.0%} of periods, magnitude min/max {ms:.2f} "
            f"< {VOLATILE_MAGNITUDE_FRAC}" if sc == 1.0 else
            f"like-signed {sc:.0%} (>= {SIGN_CONSISTENCY_RECURRENT:.0%}) but a "
            "sign flip and/or wide magnitude spread")


# --------------------------------------------------------------------------- #
# Section A - working-capital evidence map
# --------------------------------------------------------------------------- #
_CAT_INTERPRETATION = {
    "INSURANCE_RESERVES": "self-insurance float: claim liabilities accrue as "
    "trips occur and pay out over multiple years; a growing trip base makes the "
    "reserve balance - and its positive cash contribution - structural, not a "
    "one-off, though the sustainable LEVEL is not separately disclosed",
    "ACCRUED_LIABILITIES": "accrued operating costs not yet paid; a timing "
    "buffer that scales loosely with activity",
    "ACCOUNTS_RECEIVABLE": "customer / partner receivables; a use of cash when "
    "the business grows, largely a timing item",
    "ACCOUNTS_PAYABLE": "supplier payment timing; small and mean-reverting here",
    "PREPAID_EXPENSES": "prepaid costs and other operating assets; a use of "
    "cash, timing-driven and volatile",
    "OPERATING_LEASE": "the ROU-asset amortisation minus lease-liability "
    "paydown; near-offsetting and immaterial",
    "DEFERRED_REVENUE": "cash collected ahead of revenue recognition; genuine "
    "float while the subscriber / booking base grows",
    "FUNDS_HELD": "customer funds in transit; pure timing, nets to ~zero over a "
    "full period",
}


def working_capital_evidence_map(run) -> list[WorkingCapitalEvidence]:
    from .evidence_depth import wc_sign_semantics, WCSubcategory
    company = re.sub(r"_FY\d{4}$", "", getattr(run, "doc_id", "")) or "?"
    filing = getattr(run, "doc_id", "")
    rev = _revenue(run)
    out: list[WorkingCapitalEvidence] = []
    for base, per in sorted(_wc_facts(run).items()):
        periods = sorted(per)
        series = [per[p][0] for p in periods]
        quotes = [per[p][2] for p in periods]
        rec = classify_recurrence(series, quotes)
        for p in periods:
            signed, sub, quote = per[p]
            try:
                sem = wc_sign_semantics(WCSubcategory(sub), signed)
                direction = sem["cash_direction"]
            except ValueError:
                direction = ("INFLOW" if signed > 0 else
                             "OUTFLOW" if signed < 0 else "NEUTRAL")
            interp = _CAT_INTERPRETATION.get(sub, "a working-capital timing item")
            if rec in (RecurrenceEvidence.MULTI_YEAR_REPEATED,
                       RecurrenceEvidence.EXPLICIT_RECURRING):
                ds = (DisclosureStatus.SUPPORTED if sub in ("INSURANCE_RESERVES",
                      "DEFERRED_REVENUE", "ACCRUED_LIABILITIES")
                      else DisclosureStatus.PARTIALLY_SUPPORTED)
            elif rec in (RecurrenceEvidence.EXPLICIT_ONE_OFF,):
                ds = DisclosureStatus.SUPPORTED
            elif rec is RecurrenceEvidence.SINGLE_YEAR_OBSERVATION:
                ds = DisclosureStatus.PARTIALLY_SUPPORTED
            else:
                ds = DisclosureStatus.DISCLOSURE_BOUND
            out.append(WorkingCapitalEvidence(
                company=company, filing=filing, period=p, caption=base,
                normalized_category=sub, cash_flow_direction=direction,
                absolute_amount=round(abs(signed), 3),
                signed_amount=round(signed, 3), evidence_level="FACT",
                recurrence_evidence=rec, economic_interpretation=interp,
                disclosure_status=ds,
                source_reference=f"cash-flow reconciliation; quote: {quote[:80]}"))
    return out


# --------------------------------------------------------------------------- #
# Section B - persistence profiles
# --------------------------------------------------------------------------- #
def persistence_profiles(run) -> list[PersistenceProfile]:
    rev = _revenue(run)
    cfo = _cfo_by_period(run)
    fcff = _fcff_by_period(run)
    wc = _wc_facts(run)

    # per-caption series + a synthetic "wc_total" line
    series_by_name: dict[str, dict] = {}
    for base, per in wc.items():
        series_by_name[base] = {p: per[p][0] for p in per}
    total: dict = {}
    for per in wc.values():
        for p, (v, _, _) in per.items():
            total[p] = total.get(p, 0.0) + v
    series_by_name["wc_total"] = total

    out: list[PersistenceProfile] = []
    for name, per in sorted(series_by_name.items()):
        periods = tuple(sorted(per))
        vals = [per[p] for p in periods]
        if not vals:
            continue
        cls, rule = classify_persistence(vals)
        def scaled(d):
            return tuple(round(per[p] / d[p], 4) if p in d and d[p] else math.nan
                         for p in periods)
        out.append(PersistenceProfile(
            name=name, periods=periods,
            latest=round(vals[-1], 3), prior=round(vals[-2], 3) if len(vals) > 1 else None,
            median=round(statistics.median(vals), 3),
            mean=round(statistics.fmean(vals), 3),
            sign_consistency=(round(_sign_consistency(vals), 3)
                              if _sign_consistency(vals) is not None else None),
            magnitude_stability=(round(_magnitude_stability(vals), 3)
                                 if _magnitude_stability(vals) is not None else None),
            revenue_scaled_history=scaled(rev),
            cfo_scaled_history=scaled(cfo),
            fcff_scaled_history=scaled(fcff),
            classification=cls, rule=rule))
    return out


# --------------------------------------------------------------------------- #
# Section C - insurance / self-insurance float audit
# --------------------------------------------------------------------------- #
def insurance_float_audit(run) -> InsuranceAudit:
    company = re.sub(r"_FY\d{4}$", "", getattr(run, "doc_id", "")) or "?"
    changes: dict = {}
    quotes: list[str] = []
    for base, per in _wc_facts(run).items():
        if not any(s == "INSURANCE_RESERVES" for _, (_, s, _) in per.items()):
            continue
        for p, (v, _, q) in per.items():
            changes[p] = changes.get(p, 0.0) + v
            quotes.append(q)
    if not changes:
        return InsuranceAudit(company, {}, None, 0, None, False, False,
                              InsuranceVerdict.DISCLOSURE_BOUND,
                              "no insurance-reserve reconciliation line extracted")
    periods = sorted(changes)
    vals = [changes[p] for p in periods]
    sc = _sign_consistency(vals)
    ms = _magnitude_stability(vals)
    s = _modal_sign(vals)
    like = sum(1 for v in vals if (v > 0) == (s > 0))
    text = " ".join(quotes)
    mechanism = bool(re.search(r"claim|self-?insur|reserve for|loss", text, re.I))
    rollforward = bool(re.search(r"roll-?forward|beginning balance|paid|incurred|"
                                 r"development", text, re.I))

    if _ONE_OFF_LANG.search(text):
        v, why = (InsuranceVerdict.TEMPORARY_SUPPORTED,
                  "explicit one-off language on the insurance line")
    elif sc is None or len(vals) < 2:
        v, why = (InsuranceVerdict.DISCLOSURE_BOUND,
                  "fewer than two disclosed insurance-reserve cash changes")
    elif sc < 1.0:
        v, why = (InsuranceVerdict.AMBIGUOUS,
                  f"the insurance-reserve cash change flips sign within the "
                  f"disclosed window (sign consistency {sc:.0%}); a recurring "
                  "float is not established from this history")
    elif len(vals) >= MULTI_YEAR_MIN and (ms or 0) >= STABLE_MAGNITUDE_FRAC:
        v, why = (InsuranceVerdict.RECURRING_SUPPORTED,
                  f"positive every one of {len(vals)} disclosed years and the "
                  f"level is stable (min/max {ms:.2f}); consistent with a "
                  "structural self-insurance float")
    else:
        v, why = (InsuranceVerdict.MIXED_SUPPORTED,
                  f"positive every one of {len(vals)} disclosed years - the "
                  "DIRECTION recurs - but the magnitude swings "
                  f"(min/max {ms:.2f}); the sustainable LEVEL is disclosure-bound")
    return InsuranceAudit(
        company=company, changes_by_period={k: round(x, 1) for k, x in changes.items()},
        sign_consistency=(round(sc, 3) if sc is not None else None),
        years_like_signed=like,
        magnitude_stability=(round(ms, 3) if ms is not None else None),
        mechanism_disclosed=mechanism, rollforward_disclosed=rollforward,
        verdict=v, rationale=why)


# --------------------------------------------------------------------------- #
# Section (CFO reconciliation attribution)
# --------------------------------------------------------------------------- #
def cfo_attribution(run) -> list[CFOAttribution]:
    from .evidence_depth import map_reconciliation_caption, Category
    rev = _revenue(run)
    cfo_p = _cfo_by_period(run)
    fcff_p = _fcff_by_period(run)
    wc = _wc_facts(run)

    by_period_cat: dict = {}
    quotes_by_cat: dict = {}
    for base, per in wc.items():
        for p, (v, sub, q) in per.items():
            by_period_cat.setdefault(p, {}).setdefault(sub, 0.0)
            by_period_cat[p][sub] += v
            quotes_by_cat.setdefault(sub, []).append(q)
    # net income + non-cash add-backs, so CFO = NET_INCOME + NON_CASH + Sigma(WC)
    # reconciles and the residual is a genuine "unattributed" figure, not NI.
    for f in getattr(run, "facts", []) or []:
        if not f.source or f.source.target_key != "cash_flows" or not f.period:
            continue
        m = map_reconciliation_caption(_norm(f.name))
        v = _scaled(f)
        if v is None:
            continue
        if m.category is Category.NET_INCOME:
            cur = by_period_cat.setdefault(f.period, {}).get("NET_INCOME")
            # prefer the "including non-controlling interests" variant if seen
            if cur is None or "non-controlling" in _norm(f.name).lower() \
                    or "including" in _norm(f.name).lower():
                by_period_cat[f.period]["NET_INCOME"] = v
        elif m.category in (Category.NON_CASH_RECONCILIATION, Category.SBC):
            by_period_cat.setdefault(f.period, {}).setdefault("NON_CASH", 0.0)
            by_period_cat[f.period]["NON_CASH"] += v

    out: list[CFOAttribution] = []
    for p in sorted(by_period_cat):
        cats = by_period_cat[p]
        rows = []
        for cat, amt in sorted(cats.items(), key=lambda kv: -abs(kv[1])):
            rec = classify_recurrence(
                [by_period_cat[q].get(cat, 0.0) for q in sorted(by_period_cat)
                 if cat in by_period_cat[q]],
                quotes_by_cat.get(cat, ()))
            rows.append(CFOAttributionRow(
                category=cat, raw_amount=round(abs(amt), 1),
                signed_amount=round(amt, 1),
                fcff_impact=round(amt, 1),
                revenue_scaled=(round(amt / rev[p], 4) if p in rev and rev[p] else None),
                evidence_level="FACT", recurrence=rec))
        _NON_WC = ("NON_CASH", "NET_INCOME")
        wc_move = sum(a for c, a in cats.items() if c not in _NON_WC)
        # majority: the WC categories that together explain >= 60% of |wc move|
        ranked = sorted(((c, a) for c, a in cats.items() if c not in _NON_WC),
                        key=lambda kv: -abs(kv[1]))
        acc, majority = 0.0, []
        for c, a in ranked:
            if abs(wc_move) and acc / abs(wc_move) >= 0.60:
                break
            majority.append(c)
            acc += abs(a)
        resid = None
        if p in cfo_p:
            # CFO - (NET_INCOME + NON_CASH + Sigma WC); ~0 when the period
            # reconciles - a genuine unattributed remainder, not net income.
            resid = round(cfo_p[p] - sum(cats.values()), 1)
        out.append(CFOAttribution(
            period=p, cfo=(round(cfo_p[p], 1) if p in cfo_p else None),
            rows=tuple(rows), majority_categories=tuple(majority), residual=resid))
    return out


# --------------------------------------------------------------------------- #
# Section D - the "latest WC contribution vs its multi-year median" test.
# For UBER_FY2024 that is the ~$2,374m latest vs the ~$335m (P6) / ~$462m (P9)
# median disconnect the P10 report flagged.
# --------------------------------------------------------------------------- #
def wc_level_hypotheses(run) -> list[HypothesisTest]:
    prof = {p.name: p for p in persistence_profiles(run)}
    tot = prof.get("wc_total")
    ins = prof.get("Change in accrued insurance reserves") or \
        prof.get("Change in insurance reserves")
    if tot is None or tot.latest is None or tot.median in (None, 0) \
            or len(tot.periods) < 2:
        return [HypothesisTest("working-capital level is classifiable", (), (),
                               HypothesisStatus.UNTESTABLE)]
    latest = tot.latest
    med = tot.median
    near = [v for v in (tot.prior, tot.median, latest)
            if v is not None and abs(v - latest) <= 0.25 * abs(latest)]
    hi_lo = (min(abs(v) for v in (latest, tot.prior, med) if v) /
             max(abs(v) for v in (latest, tot.prior, med) if v)) \
        if all(v is not None for v in (latest, tot.prior, med)) else 0.0
    # data-driven facts, not company-specific prose
    raw = _wc_total_series(run)
    all_pos = bool(raw) and all(v > 0 for v in raw.values())
    ins_series = _insurance_series(run)
    ins_all_pos = bool(ins_series) and all(v > 0 for v in ins_series.values())
    ins_present = bool(ins_series)
    one_off_lang = _one_off_present(run)

    tests = []
    tests.append(HypothesisTest(
        hypothesis=f"A. the latest WC contribution ({latest:,.0f}) recurs at that level",
        supporting_evidence=(),
        contradicting_evidence=(
            f"the WC total series is {_series_str(tot)} - the latest is "
            f"{latest / med:.1f}x the median; {len(near)} of "
            f"{len(tot.periods)} year(s) are within 25% of the latest level",),
        status=HypothesisStatus.RULED_OUT))
    rvals = [raw[p] for p in sorted(raw)]
    monotone_to_latest = len(rvals) >= 3 and (
        all(a <= b for a, b in zip(rvals, rvals[1:]))
        or all(a >= b for a, b in zip(rvals, rvals[1:])))
    b_contra = []
    if all_pos:
        b_contra.append("the WC total is the same sign in every disclosed year")
    if ins_all_pos:
        b_contra.append("the insurance-reserve sub-line is like-signed and "
                        "non-trivial every year - no reversal")
    if monotone_to_latest:
        b_contra.append(f"the WC total moves monotonically to the latest "
                        f"({_series_str(tot)}) - the latest is the end of a "
                        "trend, not an isolated spike")
    b_contra.append("P8 one-off tier attaches EXPLICIT language only to non-cash "
                    "impairments / revaluations, none of which is a WC line")
    tests.append(HypothesisTest(
        hypothesis=f"B. the latest WC contribution ({latest:,.0f}) is abnormal / one-off",
        supporting_evidence=(("explicit one-off language appears on a WC line",)
                             if one_off_lang else ()),
        contradicting_evidence=tuple(b_contra),
        status=(HypothesisStatus.SUPPORTED if one_off_lang else
                HypothesisStatus.RULED_OUT
                if (all_pos or monotone_to_latest or len(b_contra) >= 2)
                else HypothesisStatus.UNTESTABLE)))
    c_support = [f"WC total is like-signed in {tot.sign_consistency:.0%} of years"]
    if ins_present:
        c_support.append("insurance-reserve change is like-signed in all "
                         "disclosed years" if ins_all_pos else
                         "insurance-reserve change is mostly one-signed")
        c_support.append("mechanism: a self-insurance float scales with activity")
    c_support.append(f"magnitude min/max across latest/prior/median is "
                     f"{hi_lo:.2f} - wide")
    tests.append(HypothesisTest(
        hypothesis="C. the WC contribution recurs but the level is volatile",
        supporting_evidence=tuple(c_support), contradicting_evidence=(),
        status=(HypothesisStatus.SUPPORTED
                if (tot.sign_consistency or 0) >= SIGN_CONSISTENCY_RECURRENT
                else HypothesisStatus.UNTESTABLE)))
    tests.append(HypothesisTest(
        hypothesis="D. the filing does not permit classifying the sustainable LEVEL",
        supporting_evidence=(
            "no working-capital / insurance-reserve roll-forward or "
            "claims-development table extracted",
            "no explicit 'recurring operating float' statement extracted",
            f"only {len(tot.periods)} annual periods; P8 verdict is "
            "NO_DISCLOSURE_BOUND"),
        contradicting_evidence=(),
        status=HypothesisStatus.SUPPORTED))
    return tests


def _wc_total_series(run) -> dict:
    out: dict = {}
    for per in _wc_facts(run).values():
        for p, (v, _, _) in per.items():
            out[p] = out.get(p, 0.0) + v
    return out


def _insurance_series(run) -> dict:
    out: dict = {}
    for per in _wc_facts(run).values():
        for p, (v, sub, _) in per.items():
            if sub == "INSURANCE_RESERVES":
                out[p] = out.get(p, 0.0) + v
    return out


def _one_off_present(run) -> bool:
    for per in _wc_facts(run).values():
        for _p, (_v, _s, q) in per.items():
            if _ONE_OFF_LANG.search(q or ""):
                return True
    return False


def _series_str(p: PersistenceProfile) -> str:
    return ", ".join(f"{v:,.0f}" for v in
                     [x for x in (p.prior, p.median, p.latest) if x is not None])


# --------------------------------------------------------------------------- #
# Section F - LYFT operating cash basis with working capital removed
# --------------------------------------------------------------------------- #
def operating_basis_without_wc(run) -> dict:
    try:
        from .sustainable_fcff import assess_sustainable_fcff
        s = assess_sustainable_fcff(run)
    except Exception:  # noqa: BLE001
        return {"status": "UNAVAILABLE"}
    rows = [(p.period, round(p.fcff_ex_working_capital, 1),
             round(p.reconstructed_fcff, 1), round(p.working_capital_total, 1))
            for p in s.periods if math.isfinite(p.fcff_ex_working_capital)]
    if len(rows) < 2:
        return {"status": "INSUFFICIENT_HISTORY", "rows": rows}
    ex_wc = [r[1] for r in rows]
    n_nonpos = sum(1 for v in ex_wc if v <= 0)
    latest = ex_wc[-1]
    prior = ex_wc[-2]
    last_two_positive = latest > 0 and prior > 0
    improving = ex_wc[0] < ex_wc[-1]
    hyps = []
    hyps.append(HypothesisTest(
        "1. recurring positive operating cash generation independent of WC",
        supporting_evidence=((f"fcff-ex-WC positive in the last two disclosed "
                              f"years ({prior:,.0f}, {latest:,.0f})",)
                             if last_two_positive else ()),
        contradicting_evidence=((f"fcff-ex-WC = {', '.join(f'{v:,.0f}' for v in ex_wc)}; "
                                 f"{n_nonpos} of {len(ex_wc)} years <= 0",)
                                if not last_two_positive else
                                (f"only {sum(1 for v in ex_wc if v > 0)} of "
                                 f"{len(ex_wc)} disclosed years are positive",)),
        status=(HypothesisStatus.SUPPORTED if last_two_positive
                else HypothesisStatus.RULED_OUT)))
    hyps.append(HypothesisTest(
        "2. structurally negative / breakeven operating cash, financed by WC float",
        supporting_evidence=((f"fcff-ex-WC <= 0 in {n_nonpos} of {len(ex_wc)} "
                              "years; the positive FCFF is the WC contribution",)
                             if n_nonpos >= 2 else ()),
        contradicting_evidence=(() if n_nonpos >= 2 else
                                (f"fcff-ex-WC is positive in {len(ex_wc) - n_nonpos} "
                                 f"of {len(ex_wc)} years",)),
        status=HypothesisStatus.SUPPORTED if n_nonpos >= 2 else HypothesisStatus.RULED_OUT))
    hyps.append(HypothesisTest(
        "3. transitional operating economics (loss -> breakeven / positive ramp)",
        supporting_evidence=((f"fcff-ex-WC trajectory {', '.join(f'{v:,.0f}' for v in ex_wc)} "
                              "improves off the first disclosed year",)
                             if improving else ()),
        contradicting_evidence=(() if improving else
                                ("the fcff-ex-WC series does not improve across "
                                 "the disclosed window",)),
        status=HypothesisStatus.SUPPORTED if improving else HypothesisStatus.RULED_OUT))
    if last_two_positive:
        verdict = ("hypothesis 1 SUPPORTED: operating cash generation "
                   "independent of working capital is positive in the last two "
                   "disclosed years. Only 2 of 3 years are positive, so a "
                   "transitional read (3) is also live; 3 years cannot rule it "
                   "out.")
    else:
        verdict = ("NOT hypothesis 1: operating cash generation independent of "
                   "working capital is NOT demonstrably positive. The evidence "
                   "sits between (2) structurally breakeven-financed-by-float "
                   "and (3) a transitional ramp; 3 disclosed years cannot "
                   "separate them.")
    return {
        "status": "CLASSIFIED", "rows": rows,
        "fcff_ex_wc_history": ex_wc, "n_nonpositive": n_nonpos,
        "hypotheses": tuple(hyps), "verdict": verdict,
        "deterministic_anchor": (f"fcff_ex_working_capital <= 0 in {n_nonpos} of "
                                 f"{len(ex_wc)} disclosed years; latest = {latest:,.1f}")}


# --------------------------------------------------------------------------- #
# Section E - full deterministic sequential bridge LIVE -> P9
# --------------------------------------------------------------------------- #
def sequential_bridge_live_to_p9(run) -> SequentialBridge:
    doc_id = getattr(run, "doc_id", "")
    try:
        from .operating_model import (
            Scenario, build_operating_forecast, historical_drivers)
        from .sustainable_fcff import assess_sustainable_fcff
    except Exception as exc:  # noqa: BLE001
        return _bridge_unavailable(doc_id, f"import failed: {exc}")

    inputs = getattr(getattr(run, "bridged", None), "inputs", None)
    if inputs is None:
        return _bridge_unavailable(doc_id, "no bridged inputs")
    live_fcff = inputs.base_cash_flow

    f = build_operating_forecast(run, Scenario.BASE)
    if f.support.value == "INSUFFICIENT_EVIDENCE" or not f.years or f.base_fcff is None:
        return _bridge_unavailable(
            doc_id, "P9 produces no BASE forecast (INSUFFICIENT_EVIDENCE); "
            "there is no second model to bridge to")

    hd = {d.name: d for d in historical_drivers(run)}
    rev = hd["revenue"].latest or 0.0
    y0 = f.years[0]
    margin = y0.operating_margin or 0.0
    oi = rev * margin
    nopat = oi * (1 - STATUTORY_TAX)
    dna = (y0.dna / y0.revenue * rev) if y0.revenue else 0.0
    capex = (y0.capex / y0.revenue * rev) if y0.revenue else 0.0
    wc_p9 = (hd["wc_cash_effect_over_revenue"].median or 0.0) * rev
    p9_fcff = f.base_fcff

    s = assess_sustainable_fcff(run)
    latest = s.periods[-1] if s.periods else None
    wc_actual = latest.working_capital_total if latest else wc_p9
    fcff_ex_wc = latest.fcff_ex_working_capital if latest else (live_fcff - wc_actual)

    steps: list[BridgeStep] = []
    cur = live_fcff
    steps.append(BridgeStep(
        0, "LIVE base FCFF", cur, 0.0, cur, "ACCOUNTING",
        "latest reconstructed FCFF (CFO + interest*(1-t) - capex - SBC), as-is"))

    d1 = wc_p9 - wc_actual
    steps.append(BridgeStep(
        1, "working-capital normalization (actual -> P9 median ratio x revenue)",
        cur, d1, cur + d1, "WORKING_CAPITAL",
        f"LIVE embeds the actual {wc_actual:,.0f}; P9 BASE uses the "
        f"median cash-effect/revenue ratio x latest revenue = {wc_p9:,.0f}. "
        "P8: recurrence of the level is NOT disclosed"))
    cur += d1

    d2 = -(oi - nopat)
    steps.append(BridgeStep(
        2, "tax normalization (21% statutory on operating income)",
        cur, d2, cur + d2, "TAX",
        f"LIVE inherits the disclosed ~0% cash/effective rate; P9 applies "
        f"21% to operating income ({oi:,.0f}) -> tax drag {oi - nopat:,.0f}. "
        "This is a held-identical MODEL CONVENTION, not a disclosed rate"))
    cur += d2

    d3 = (oi + dna - capex) - fcff_ex_wc
    steps.append(BridgeStep(
        3, "accounting-basis residual (operating-income basis vs CFO-derived)",
        cur, d3, cur + d3, "METHODOLOGY",
        f"P9 builds pre-WC FCFF as operating income + D&A ({dna:,.0f}) - capex "
        f"({capex:,.0f}) = {oi + dna - capex:,.0f}; LIVE's CFO-derived "
        f"pre-WC FCFF is {fcff_ex_wc:,.0f}. The gap is tax-basis in nature - "
        "CFO nets the non-cash deferred-tax / DTA-release movement"))
    cur += d3

    residual = p9_fcff - cur
    steps.append(BridgeStep(
        4, "= P9 BASE FCFF", cur, residual, cur + residual, "RESIDUAL",
        f"unexplained remainder after the three named steps: {residual:,.1f}"))

    tol = max(2.0, IMMATERIAL_FCFF_FRAC * abs(live_fcff))
    arith = abs(residual) <= tol
    meth_pct = abs(d3) / abs(live_fcff) if live_fcff else None
    # ARITHMETICALLY_RECONCILED (the plug is ~0) is necessary but NOT
    # sufficient. ECONOMICALLY_EXPLAINED asks whether every material step has a
    # NAMED cause: the dominant move must be a named economic choice (TAX or
    # WORKING_CAPITAL), and the methodology residual (understood as tax-basis:
    # CFO nets the deferred-tax movement) must not dominate.
    #   FULLY  : reconciles, dominant is named, methodology < 2% of FCFF
    #   PARTIAL: reconciles, dominant is named, methodology < 25% (named in
    #            kind - tax-basis - but not line-itemised)
    #   NO     : does not reconcile, or the methodology chunk dominates
    dominant_is_named = max(abs(d1), abs(d2)) >= abs(d3)
    if arith and dominant_is_named and (meth_pct or 0) < 0.02:
        econ = EconomicallyExplained.FULLY
    elif arith and dominant_is_named and (meth_pct or 0) < 0.25:
        econ = EconomicallyExplained.PARTIAL
    else:
        econ = EconomicallyExplained.NO
    dominant = ("tax normalization (21% statutory)" if abs(d2) >= abs(d1)
                else "working-capital median vs latest")
    return SequentialBridge(
        doc_id=doc_id, live_fcff=round(live_fcff, 1),
        p9_base_fcff=round(p9_fcff, 1), steps=tuple(steps),
        residual=round(residual, 2),
        residual_kind=("IMMATERIAL (< max($2m, 2% of FCFF))" if arith
                       else "MATERIAL - investigate"),
        arithmetically_reconciled=arith, economically_explained=econ,
        dominant_cause=dominant,
        methodology_pct_of_fcff=(round(meth_pct, 4) if meth_pct is not None else None),
        note=("ARITHMETICALLY_RECONCILED and ECONOMICALLY_EXPLAINED are kept "
              "separate: a bridge that balances is not automatically explained. "
              f"Here the dominant move is {dominant}; the methodology residual "
              f"is {(meth_pct or 0):.1%} of LIVE FCFF and is tax-basis in "
              "nature (CFO nets the non-cash deferred-tax movement)."))


def _bridge_unavailable(doc_id, why) -> SequentialBridge:
    return SequentialBridge(
        doc_id=doc_id, live_fcff=None, p9_base_fcff=None, steps=(),
        residual=None, residual_kind="N/A",
        arithmetically_reconciled=False,
        economically_explained=EconomicallyExplained.NO,
        dominant_cause="n/a", methodology_pct_of_fcff=None, note=why)


# --------------------------------------------------------------------------- #
# Section G - tax evidence ladder (does NOT change the 21% convention)
# --------------------------------------------------------------------------- #
def tax_evidence(run) -> TaxEvidence:
    company = re.sub(r"_FY\d{4}$", "", getattr(run, "doc_id", "")) or "?"
    facts = getattr(run, "facts", []) or []

    def series(target, want):
        out = {}
        for f in facts:
            if not f.source or f.source.target_key != target or not f.period:
                continue
            n = _norm(f.name).lower()
            if want(n):
                out[f.period] = f.value
        return out

    eff = series("taxes", lambda n: "effective" in n and "tax rate" in n)
    deferred = series("cash_flows", lambda n: n.startswith("deferred income tax"))
    cash_paid = series("cash_flows", lambda n: "cash paid for income tax" in n
                       or "income taxes paid" in n or "taxes paid, net" in n)
    cash_paid |= series("operations", lambda n: "cash paid for income tax" in n)

    has_eff = len(eff) >= 1
    has_cash = len(cash_paid) >= 1
    # a normalized rate is derivable only if the disclosed effective rates are
    # themselves in a sane, tight band (they are not, for these filers).
    ev = [v for v in eff.values() if v is not None]
    normalized_ok = (len(ev) >= 2 and (max(ev) - min(ev) <= 10.0)
                     and all(0 <= v <= 40 for v in ev))

    if has_cash:
        klass = TaxEvidenceClass.CASH_TAX_SUPPORTED
    elif normalized_ok:
        klass = TaxEvidenceClass.NORMALIZED_TAX_SUPPORTED
    elif has_eff:
        klass = TaxEvidenceClass.EFFECTIVE_DISCLOSED
    else:
        klass = TaxEvidenceClass.STATUTORY_ONLY

    norm_verdict = (TaxNormalizationVerdict.NORMALIZED_TAX_SUPPORTED if normalized_ok
                    else TaxNormalizationVerdict.TAX_NORMALIZATION_DISCLOSURE_BOUND)
    if normalized_ok:
        rationale = ("disclosed effective rates sit in a tight band; 21% is "
                     "close to the evidenced rate.")
    elif has_eff:
        rationale = (
            f"disclosed effective rates {sorted((p, round(v, 1)) for p, v in eff.items())} "
            f"span {(max(ev) - min(ev)):.0f} points and are NOL / DTA-release "
            "distorted; no cash-taxes-paid line was extracted; deferred-tax "
            f"movements {sorted((p, round(v, 0)) for p, v in deferred.items())} "
            "are large and non-cash. A forward normalized rate cannot be "
            "derived - the 21% statutory convention stands as a held-identical "
            "MODEL ASSUMPTION over a DISCLOSURE_BOUND question, not as an "
            "estimate of the cash rate.")
    else:
        rationale = (
            "no effective tax rate and no cash-taxes-paid line were extracted "
            "for this filer; only the 21% statutory convention is available and "
            "it cannot be checked against the filer's own rate - the tax "
            "normalization question is DISCLOSURE_BOUND.")
    return TaxEvidence(
        company=company, statutory=STATUTORY_TAX,
        effective_by_period={p: round(v, 1) for p, v in eff.items() if v is not None},
        cash_taxes_paid_disclosed=has_cash,
        deferred_tax_by_period={p: round(v, 0) for p, v in deferred.items()
                                if v is not None},
        normalized_rate_derivable=normalized_ok,
        classification=klass, normalization_verdict=norm_verdict,
        rationale=rationale)


# --------------------------------------------------------------------------- #
# Section (FACT / INTERPRETATION / ASSUMPTION separation)
# --------------------------------------------------------------------------- #
def epistemic_tags(run) -> list[EpistemicTag]:
    ins = insurance_float_audit(run)
    br = sequential_bridge_live_to_p9(run)
    tags = [
        EpistemicTag(
            "per-period working-capital cash movements (each 'change in <account>' line)",
            EpistemicClass.FACT,
            "verbatim cash-flow reconciliation lines, unit-scaled"),
        EpistemicTag(
            "LIVE reconstructed FCFF for each disclosed period",
            EpistemicClass.FACT,
            "mechanical: CFO + interest*(1-tax) - capex - SBC from disclosed lines"),
        EpistemicTag(
            "the insurance-reserve cash contribution is a recurring operating float",
            EpistemicClass.ECONOMIC_INTERPRETATION,
            f"defensible from {ins.years_like_signed} like-signed years + the "
            "self-insurance mechanism; NOT explicitly labelled recurring in the "
            "extracted disclosure"),
        EpistemicTag(
            "the sustainable working-capital contribution equals its multi-year median",
            EpistemicClass.MODEL_ASSUMPTION,
            "P6 uses the median of dollar totals, P9 the median of revenue "
            "ratios; the filing does not determine either"),
        EpistemicTag(
            "the forward tax rate is 21% (statutory)",
            EpistemicClass.MODEL_ASSUMPTION,
            "held-identical convention; the disclosed effective rate is "
            "NOL-distorted and no cash-tax line exists"),
        EpistemicTag(
            "the latest year's FCFF is the run-rate (LIVE anchor)",
            EpistemicClass.MODEL_ASSUMPTION,
            "a method choice; P6/P9 exist precisely because it is not a fact"),
        EpistemicTag(
            (f"the LIVE<->P9 gap for {getattr(run, 'doc_id', '')} is dominated "
             f"by: {br.dominant_cause}") if br.live_fcff else
            f"the LIVE<->P9 gap for {getattr(run, 'doc_id', '')} is n/a - P9 "
            "produces no forecast for this filer",
            EpistemicClass.ECONOMIC_INTERPRETATION,
            (f"from the sequential bridge: the {br.dominant_cause} step is the "
             f"largest named delta; economically_explained={br.economically_explained.value}, "
             f"methodology residual {br.methodology_pct_of_fcff}")
            if br.live_fcff else "no second model to bridge to"),
    ]
    return tags


# --------------------------------------------------------------------------- #
# Section H - disclosure-boundary engine
# --------------------------------------------------------------------------- #
def disclosure_boundaries(run) -> list[DisclosureBoundary]:
    doc_id = getattr(run, "doc_id", "")
    ins = insurance_float_audit(run)
    ob = operating_basis_without_wc(run)
    br = sequential_bridge_live_to_p9(run)
    tax = tax_evidence(run)
    out: list[DisclosureBoundary] = []

    # Q1 - sustainable WC / insurance-float LEVEL
    if ins.verdict is not InsuranceVerdict.DISCLOSURE_BOUND and ins.changes_by_period:
        ruled = ("the level is a one-off / temporary distortion",)
        remaining = ("the contribution recurs but at a disclosure-bound LEVEL",)
        v = BoundaryVerdict.PARTIALLY_RESOLVED
    else:
        ruled = ()
        remaining = ("recurring float", "timing distortion", "mixture")
        v = BoundaryVerdict.DISCLOSURE_BOUND
    out.append(DisclosureBoundary(
        question=f"Is {doc_id}'s working-capital / insurance-float contribution "
        "sustainable, and at what level?",
        available_evidence=(
            "3 years of WC-total and insurance-reserve cash changes",
            f"insurance sign consistency {ins.sign_consistency}",
            "P8 subcategory split, all periods reconcile"),
        missing_evidence=(
            "insurance-reserve roll-forward / claims-development table",
            "explicit 'recurring operating float' statement",
            "more than 3 annual periods"),
        possible_hypotheses=("recurs at the latest level", "one-off",
                             "recurs but volatile level", "indeterminate level"),
        hypotheses_ruled_out=ruled, hypotheses_remaining=remaining, verdict=v))

    # Q2 - LYFT operating cash independent of WC
    if ob.get("status") == "CLASSIFIED":
        n = ob["n_nonpositive"]
        tot = len(ob["fcff_ex_wc_history"])
        out.append(DisclosureBoundary(
            question=f"Does {doc_id} generate positive operating cash flow "
            "independent of working capital?",
            available_evidence=(f"fcff-ex-WC = {ob['fcff_ex_wc_history']}",
                                f"{n} of {tot} years <= 0"),
            missing_evidence=("more than 3 annual periods",
                              "segment-level operating cash detail"),
            possible_hypotheses=("yes - recurring positive", "structurally negative",
                                 "transitional ramp"),
            hypotheses_ruled_out=("yes - recurring positive",),
            hypotheses_remaining=("structurally negative", "transitional ramp"),
            verdict=BoundaryVerdict.PARTIALLY_RESOLVED))

    # Q3 - normalized forward tax rate
    out.append(DisclosureBoundary(
        question=f"What normalized forward tax rate applies to {doc_id}?",
        available_evidence=(f"disclosed effective rates {tax.effective_by_period}",
                            f"deferred-tax movements {tax.deferred_tax_by_period}"),
        missing_evidence=("cash taxes paid", "a normalized / adjusted effective rate",
                          "NOL / valuation-allowance exhaustion schedule"),
        possible_hypotheses=("21% statutory", "the disclosed effective rate",
                             "near-0% cash rate"),
        hypotheses_ruled_out=(),
        hypotheses_remaining=("21% statutory", "the disclosed effective rate",
                              "near-0% cash rate"),
        verdict=(BoundaryVerdict.DISCLOSURE_BOUND
                 if tax.normalization_verdict is
                 TaxNormalizationVerdict.TAX_NORMALIZATION_DISCLOSURE_BOUND
                 else BoundaryVerdict.RESOLVED)))

    # Q4 - is the LIVE<->P9 divergence attributable?
    if br.live_fcff is not None:
        resolved = (br.arithmetically_reconciled
                    and br.economically_explained in (EconomicallyExplained.FULLY,
                                                      EconomicallyExplained.PARTIAL))
        out.append(DisclosureBoundary(
            question=f"Is the {doc_id} LIVE<->P9 divergence attributable to "
            "identified assumptions?",
            available_evidence=("a full sequential bridge that reconciles to "
                                f"within {br.residual}",
                                f"dominant cause: {br.dominant_cause}",
                                f"methodology residual {br.methodology_pct_of_fcff}"),
            missing_evidence=(() if resolved else ("a line-item deferred-tax bridge",)),
            possible_hypotheses=("tax normalization", "working-capital choice",
                                 "operating margin", "unexplained"),
            hypotheses_ruled_out=(("operating margin", "unexplained")
                                  if resolved else ()),
            hypotheses_remaining=(("tax normalization", "working-capital choice")
                                  if resolved else ("unexplained",)),
            verdict=(BoundaryVerdict.RESOLVED
                     if br.economically_explained is EconomicallyExplained.FULLY
                     else BoundaryVerdict.PARTIALLY_RESOLVED if resolved
                     else BoundaryVerdict.DISCLOSURE_BOUND)))
    return out


# --------------------------------------------------------------------------- #
# orchestrator
# --------------------------------------------------------------------------- #
def assess_evidence_resolution(run) -> EvidenceResolutionReport:
    doc_id = getattr(run, "doc_id", "")
    wc_map = working_capital_evidence_map(run)
    prof = persistence_profiles(run)
    ins = insurance_float_audit(run)
    cfo_attr = cfo_attribution(run)
    hyps = wc_level_hypotheses(run)
    ob = operating_basis_without_wc(run)
    br = sequential_bridge_live_to_p9(run)
    tax = tax_evidence(run)
    tags = epistemic_tags(run)
    bounds = disclosure_boundaries(run)

    # does P10's arbitrate() label this filer UNRESOLVED while the bridge shows
    # the divergence IS attributable? That - and only that - is the targeted fix.
    p10_outcome = ""
    try:
        from .model_governance import (
            assumption_register, model_applicability, arbitrate)
        reg = assumption_register(run)
        ap = model_applicability(run)
        p10_outcome = arbitrate(run, reg, ap)[0].value
    except Exception:  # noqa: BLE001
        p10_outcome = "UNKNOWN"
    bridge_attributes = (br.live_fcff is not None
                         and br.economically_explained in (EconomicallyExplained.FULLY,
                                                           EconomicallyExplained.PARTIAL))
    p10_lags = p10_outcome == "MODEL_DIVERGENCE_UNRESOLVED" and bridge_attributes

    model_consequence = {
        "LIVE": "UNCHANGED",
        "P6": "UNCHANGED",
        "P9": "UNCHANGED",
        "P10 governance": "UNCHANGED",
        "p10_arbitration_outcome": p10_outcome,
        "note": (("P10 arbitrate() labels this filer MODEL_DIVERGENCE_UNRESOLVED, "
                  "but the P10.5 sequential bridge attributes the LIVE<->P9 gap "
                  f"to: {br.dominant_cause}. That is a gap in P10's arbitration "
                  "reason-set (no tax-normalization branch), not a "
                  "model-methodology defect - a targeted 5-line fix, not a "
                  "redesign.") if p10_lags else
                 "P10 arbitrate() already attributes this filer's LIVE<->P9 "
                 "divergence; P10.5 adds the line-item bridge, nothing to fix."),
    }

    decision = ("P10.5_REQUIRES_TARGETED_EVIDENCE_FIX" if p10_lags
                else "KEEP_P10_AS_FINAL_GOVERNANCE_LAYER")

    # overall verdict. PROGRESS = a boundary that is RESOLVED or PARTIALLY_RESOLVED.
    dbound = any(b.verdict is BoundaryVerdict.DISCLOSURE_BOUND for b in bounds)
    progress = sum(1 for b in bounds if b.verdict in (BoundaryVerdict.RESOLVED,
                                                      BoundaryVerdict.PARTIALLY_RESOLVED))
    all_dbound = bool(bounds) and all(b.verdict is BoundaryVerdict.DISCLOSURE_BOUND
                                      for b in bounds)
    no_second_model = br.live_fcff is None
    if all_dbound or not bounds or (no_second_model and progress < 2):
        # no competing model, or nothing was even partially resolved
        verdict = "P10.5 DISCLOSURE-BOUND"
    elif not dbound and progress >= 1:
        verdict = "P10.5 SOLVED"
    else:
        verdict = "P10.5 PARTIALLY SOLVED"

    notes = (
        "EXPERIMENTAL. No LIVE number changed; no model promoted; no function "
        "here takes a market price.",
        f"insurance float: {ins.verdict.value}. tax: {tax.classification.value} / "
        f"{tax.normalization_verdict.value}. bridge: "
        f"{br.economically_explained.value if br.live_fcff else 'n/a'}.",
        "The remaining disagreement is PRIMARILY an evidence problem: the "
        "sustainable LEVEL of the working-capital / insurance float and the "
        "normalized tax rate are disclosure-bound - no model change resolves "
        "them. " + ("The one model-side gap is P10 arbitrate() lacking a "
                    "tax-normalization reason-branch (small, named)."
                    if p10_lags else
                    "P10's arbitration already attributes this filer's gap."),
    )
    return EvidenceResolutionReport(
        doc_id=doc_id, wc_map=tuple(wc_map), persistence=tuple(prof),
        insurance=ins, cfo_attribution=tuple(cfo_attr),
        wc_level_hypotheses=tuple(hyps), operating_basis_without_wc=ob,
        bridge=br, tax=tax, epistemic_tags=tuple(tags), boundaries=tuple(bounds),
        model_consequence=model_consequence, architectural_decision=decision,
        verdict=verdict, notes=notes)
