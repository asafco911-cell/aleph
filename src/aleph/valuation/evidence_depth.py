"""P8 - EVIDENCE DEPTH, MULTI-PERIOD ACCOUNTING & CASH-FLOW DATA QUALITY.

STATUS: EXPERIMENTAL - NOT WIRED INTO THE BASE DCF, and it does NOT promote
P6 or P7. It reads a finished ValuationRun (facts, ranges, per-period FCFF),
classifies the evidence that is actually there, and reports where it runs
out. Nothing here changes a valuation number or a P6/P7 rule.

THE QUESTION. Not "which formula" but: does Aleph have enough verified,
multi-period accounting evidence to support the economic conclusions it is
being asked to make? The honest answer is allowed to be "the filing does
not disclose enough to know."

WHAT IT DOES.
  - Maps every extracted cash-flow reconciliation caption to a normalized
    category (NON_CASH_RECONCILIATION / WORKING_CAPITAL[subcategory] /
    OPERATING_CASH_ITEM / ... / UNCLASSIFIED) with explicit sign semantics
    and a mapping confidence. A caption that cannot be mapped confidently is
    UNCLASSIFIED, never a guess.
  - Builds a period x component coverage matrix with an evidence status per
    cell (OBSERVED / VERIFIED / OVERRIDDEN / INFERRED / MISSING / AMBIGUOUS
    / CONFLICTING) and an "economically usable" flag with explicit criteria.
  - Reconciles CFO = NI + non-cash + working capital per period and RETAINS
    the residual - the residual is evidence, not noise.
  - Reports whether a maintenance/growth capex split is disclosed
    (CAPEX_SPLIT_SUPPORTED / NOT_SUPPORTED) - never estimated.
  - Tiers one-off cash evidence: EXPLICIT / CORROBORATING / PATTERN_ONLY /
    NONE. Only EXPLICIT or CORROBORATING may support a normalization
    adjustment; PATTERN_ONLY may only inform REGIME_UNCERTAIN.
  - Grades each period FULLY_EVIDENCED / PARTIALLY_EVIDENCED /
    INFERRED_COMPONENTS / RECONCILIATION_FAILED / INSUFFICIENT_EVIDENCE.

NO LLM in the classification. No ML. No inference of undisclosed facts. No
company-specific hacks. No widening a tolerance until things pass.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import Enum

from ..infra.units import resolve_scale

__all__ = [
    "Category",
    "WCSubcategory",
    "SignSemantics",
    "MappingConfidence",
    "EvidenceStatus",
    "ReconciliationStatus",
    "PeriodScore",
    "CapexSplitStatus",
    "OneOffTier",
    "UncertaintyVerdict",
    "CaptionMapping",
    "EvidenceCell",
    "PeriodEvidence",
    "CapexEvidence",
    "OneOffEvidence",
    "EvidenceDepthReport",
    "map_reconciliation_caption",
    "wc_sign_semantics",
    "assess_evidence_depth",
    "RECON_TOL_FRAC",
    "RECON_TOL_ABS",
]

# Reconciliation tolerance - inherited from P6, NOT widened here.
RECON_TOL_FRAC = 0.035
RECON_TOL_ABS = 75.0


class Category(str, Enum):
    NON_CASH_RECONCILIATION = "NON_CASH_RECONCILIATION"
    WORKING_CAPITAL = "WORKING_CAPITAL"
    OPERATING_CASH_ITEM = "OPERATING_CASH_ITEM"
    CFO_SUBTOTAL = "CFO_SUBTOTAL"
    CASH_BALANCE = "CASH_BALANCE"
    CAPEX = "CAPEX"
    SBC = "SBC"
    NET_INCOME = "NET_INCOME"
    NON_OPERATING = "NON_OPERATING"
    UNCLASSIFIED = "UNCLASSIFIED"


class WCSubcategory(str, Enum):
    ACCOUNTS_RECEIVABLE = "ACCOUNTS_RECEIVABLE"
    ACCOUNTS_PAYABLE = "ACCOUNTS_PAYABLE"
    ACCRUED_LIABILITIES = "ACCRUED_LIABILITIES"
    PREPAID_EXPENSES = "PREPAID_EXPENSES"
    DEFERRED_REVENUE = "DEFERRED_REVENUE"
    INSURANCE_RESERVES = "INSURANCE_RESERVES"
    OPERATING_LEASE = "OPERATING_LEASE"
    FUNDS_HELD = "FUNDS_HELD"
    INVENTORY = "INVENTORY"
    OTHER_OPERATING_ASSET = "OTHER_OPERATING_ASSET"
    OTHER_OPERATING_LIABILITY = "OTHER_OPERATING_LIABILITY"
    WC_UNCLASSIFIED = "WC_UNCLASSIFIED"


class SignSemantics(str, Enum):
    # The disclosed number IS the cash-flow effect (the CFO reconciliation
    # presents an AR increase as a negative). Summing is valid as-is.
    CASH_EFFECT = "CASH_EFFECT"
    # The disclosed number is a balance-sheet delta and would need a sign
    # flip to become a cash effect. Not expected on the CFO target.
    BALANCE_DELTA = "BALANCE_DELTA"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class MappingConfidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class EvidenceStatus(str, Enum):
    OBSERVED = "OBSERVED"
    VERIFIED = "VERIFIED"
    OVERRIDDEN = "OVERRIDDEN"
    INFERRED = "INFERRED"
    MISSING = "MISSING"
    AMBIGUOUS = "AMBIGUOUS"
    CONFLICTING = "CONFLICTING"


class ReconciliationStatus(str, Enum):
    RECONCILED = "RECONCILED"
    RECONCILIATION_FAILED = "RECONCILIATION_FAILED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class PeriodScore(str, Enum):
    FULLY_EVIDENCED = "FULLY_EVIDENCED"
    PARTIALLY_EVIDENCED = "PARTIALLY_EVIDENCED"
    INFERRED_COMPONENTS = "INFERRED_COMPONENTS"
    RECONCILIATION_FAILED = "RECONCILIATION_FAILED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class CapexSplitStatus(str, Enum):
    CAPEX_SPLIT_SUPPORTED = "CAPEX_SPLIT_SUPPORTED"
    CAPEX_SPLIT_NOT_SUPPORTED = "CAPEX_SPLIT_NOT_SUPPORTED"


class OneOffTier(str, Enum):
    EXPLICIT = "EXPLICIT"
    CORROBORATING = "CORROBORATING"
    PATTERN_ONLY = "PATTERN_ONLY"
    NONE = "NONE"


class UncertaintyVerdict(str, Enum):
    YES_MATERIAL = "YES_MATERIAL"
    YES_PARTIAL = "YES_PARTIAL"
    NO_DISCLOSURE_BOUND = "NO_DISCLOSURE_BOUND"


# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CaptionMapping:
    source_caption: str
    category: Category
    wc_subcategory: WCSubcategory | None
    sign_semantics: SignSemantics
    mapping_confidence: MappingConfidence
    rationale: str


@dataclass(frozen=True)
class EvidenceCell:
    period: str
    component: str
    category: str
    status: EvidenceStatus
    economically_usable: bool
    source_caption: str
    unit: str
    quality_limitation: str


@dataclass(frozen=True)
class PeriodEvidence:
    period: str
    fiscal_year: int | None
    period_type: str                    # "ANNUAL" | "UNKNOWN" | ...
    score: PeriodScore
    cfo_reported: float | None
    cfo_reconstructed: float | None
    residual: float | None
    reconciliation_status: ReconciliationStatus
    wc_by_subcategory: dict            # {subcategory.value: amount}
    unclassified_wc: dict             # {caption: amount}
    components_by_status: dict         # {status.value: [component, ...]}
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapexEvidence:
    status: CapexSplitStatus
    total_by_period: dict
    disclosed_lines: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class OneOffEvidence:
    tier: OneOffTier
    explicit_items: tuple[str, ...]
    corroborating_items: tuple[str, ...]
    pattern_items: tuple[str, ...]
    note: str


@dataclass(frozen=True)
class EvidenceDepthReport:
    doc_id: str
    periods: tuple[str, ...]
    oldest_period: str
    newest_period: str
    caption_mappings: tuple[CaptionMapping, ...]
    coverage: tuple[EvidenceCell, ...]
    period_evidence: tuple[PeriodEvidence, ...]
    capex_evidence: CapexEvidence
    one_off_evidence: OneOffEvidence
    # P6 impact - the same numbers, richer lineage
    p6_wc_total_by_period: dict
    p8_wc_component_sum_by_period: dict
    p6_p8_wc_agree: bool
    reduces_uncertainty: UncertaintyVerdict
    reduces_uncertainty_reason: str
    notes: tuple[str, ...] = field(default_factory=tuple)


# --------------------------------------------------------------------------- #
# Phase 4 / 7 / 10 - deterministic caption -> category mapping
# --------------------------------------------------------------------------- #
_CFO_SUBTOTAL = re.compile(r"provided by (\(used in\) )?operating activities|"
                           r"used in operating activities", re.I)
_CASH_BALANCE = re.compile(r"beginning of period|end of period|"
                           r"net (increase|decrease|change)\b.*\bin cash", re.I)
_CAPEX = re.compile(r"purchases of property|property and equipment|scooter fleet|"
                    r"capital expenditure", re.I)
_SBC = re.compile(r"stock-based compensation|share-based compensation", re.I)
_NET_INCOME = re.compile(r"^net (income|loss)\b", re.I)
_INVESTING_FINANCING = re.compile(r"investing activities|financing activities|"
                                  r"proceeds from|repayment of|dividends paid|"
                                  r"repurchase of", re.I)

# working-capital markers: the CFO reconciliation presents these as the CASH
# effect already (an AR increase is shown negative).
_WC_MARK = re.compile(r"\bchanges?\s+in\b|\(change\)|\bfunds\s+held\b|"
                      r"\bfunds\s+receivable\b", re.I)

_WC_SUBCATS = (
    (WCSubcategory.ACCOUNTS_RECEIVABLE, re.compile(r"receivable", re.I)),
    (WCSubcategory.ACCOUNTS_PAYABLE, re.compile(r"payable", re.I)),
    (WCSubcategory.INSURANCE_RESERVES, re.compile(r"insurance", re.I)),
    (WCSubcategory.DEFERRED_REVENUE, re.compile(r"deferred revenue|unearned", re.I)),
    (WCSubcategory.PREPAID_EXPENSES, re.compile(r"prepaid", re.I)),
    (WCSubcategory.OPERATING_LEASE, re.compile(r"operating lease|right-of-use|"
                                              r"lease liabilit", re.I)),
    (WCSubcategory.FUNDS_HELD, re.compile(r"funds held|funds receivable", re.I)),
    (WCSubcategory.INVENTORY, re.compile(r"inventor", re.I)),
    (WCSubcategory.ACCRUED_LIABILITIES, re.compile(r"accrued", re.I)),
    (WCSubcategory.OTHER_OPERATING_LIABILITY, re.compile(r"other (current )?liabilit",
                                                        re.I)),
    (WCSubcategory.OTHER_OPERATING_ASSET, re.compile(r"other (current )?assets|"
                                                    r"other operating assets", re.I)),
)

# non-cash reconciliation add-backs (not "change in" lines)
_NONCASH = re.compile(
    r"depreciation|amortization|amortisation|deferred (income )?tax|unrealized|"
    r"unrealised|impairment|accretion|bad debt|provision for|write-?off|"
    r"write-?down|revaluation|equity method|non-marketable|"
    r"gain\b|loss (on|from)|disposal|divestiture|lease termination|"
    r"foreign currency|other adjustments|other \(adjustments", re.I)


def map_reconciliation_caption(name: str, target_key: str = "cash_flows"
                               ) -> CaptionMapping:
    """Map one extracted caption to a normalized category. Deterministic;
    UNCLASSIFIED when the evidence is weak, never a guess."""
    n = re.sub(r"\s+", " ", name or "").strip()
    low = n.lower()

    if target_key != "cash_flows":
        return CaptionMapping(n, Category.NON_OPERATING, None,
                              SignSemantics.NOT_APPLICABLE, MappingConfidence.LOW,
                              "not a cash-flow reconciliation line")

    if _CFO_SUBTOTAL.search(low):
        return CaptionMapping(n, Category.CFO_SUBTOTAL, None,
                              SignSemantics.NOT_APPLICABLE, MappingConfidence.HIGH,
                              "the CFO subtotal itself")
    if _CASH_BALANCE.search(low):
        return CaptionMapping(n, Category.CASH_BALANCE, None,
                              SignSemantics.NOT_APPLICABLE, MappingConfidence.HIGH,
                              "a cash balance / net-change-in-cash line, not a "
                              "reconciliation add-back")
    if _INVESTING_FINANCING.search(low):
        return CaptionMapping(n, Category.NON_OPERATING, None,
                              SignSemantics.NOT_APPLICABLE, MappingConfidence.HIGH,
                              "an investing/financing line the extractor also pulled")
    if _NET_INCOME.match(low):
        return CaptionMapping(n, Category.NET_INCOME, None,
                              SignSemantics.CASH_EFFECT, MappingConfidence.HIGH,
                              "the reconciliation starting point")
    if _CAPEX.search(low):
        return CaptionMapping(n, Category.CAPEX, None, SignSemantics.CASH_EFFECT,
                              MappingConfidence.HIGH, "capital expenditure")
    if _SBC.search(low):
        return CaptionMapping(n, Category.SBC, None, SignSemantics.CASH_EFFECT,
                              MappingConfidence.HIGH,
                              "stock-based compensation add-back")

    if _WC_MARK.search(low):
        sub = WCSubcategory.WC_UNCLASSIFIED
        conf = MappingConfidence.LOW
        why = "a working-capital change line, subcategory not recognised"
        for cat, rx in _WC_SUBCATS:
            if rx.search(low):
                sub, conf = cat, MappingConfidence.HIGH
                why = f"working-capital change: {cat.value.lower().replace('_', ' ')}"
                break
        return CaptionMapping(n, Category.WORKING_CAPITAL, sub,
                              SignSemantics.CASH_EFFECT, conf, why)

    if _NONCASH.search(low):
        return CaptionMapping(n, Category.NON_CASH_RECONCILIATION, None,
                              SignSemantics.CASH_EFFECT, MappingConfidence.HIGH,
                              "a non-cash reconciliation add-back (already inside "
                              "reported CFO)")

    return CaptionMapping(n, Category.UNCLASSIFIED, None, SignSemantics.CASH_EFFECT,
                          MappingConfidence.LOW,
                          "no confident mapping - reported as UNCLASSIFIED, not "
                          "forced into a bucket")


# --------------------------------------------------------------------------- #
# Phase 5 - sign integrity
# --------------------------------------------------------------------------- #
_ASSET_SUBCATS = {
    WCSubcategory.ACCOUNTS_RECEIVABLE, WCSubcategory.PREPAID_EXPENSES,
    WCSubcategory.INVENTORY, WCSubcategory.OTHER_OPERATING_ASSET,
    WCSubcategory.FUNDS_HELD,
}


def wc_sign_semantics(subcat: WCSubcategory, cash_effect: float) -> dict:
    """Given a working-capital line's CASH EFFECT as the CFO reconciliation
    presents it, return the cash direction and the implied balance-sheet
    direction. These are NOT the same thing: an AR increase (balance up) is
    a cash OUTFLOW (cash effect negative)."""
    if cash_effect == 0:
        cash_dir = "NEUTRAL"
    else:
        cash_dir = "INFLOW" if cash_effect > 0 else "OUTFLOW"
    if subcat in _ASSET_SUBCATS:
        # operating asset: cash inflow <=> the asset balance decreased
        balance_dir = ("DECREASE" if cash_effect > 0 else
                       "INCREASE" if cash_effect < 0 else "UNCHANGED")
    else:
        # operating liability: cash inflow <=> the liability balance increased
        balance_dir = ("INCREASE" if cash_effect > 0 else
                       "DECREASE" if cash_effect < 0 else "UNCHANGED")
    return {"cash_effect": cash_effect, "cash_direction": cash_dir,
            "implied_balance_direction": balance_dir,
            "sign_semantics": SignSemantics.CASH_EFFECT.value}


# --------------------------------------------------------------------------- #
# fact plumbing
# --------------------------------------------------------------------------- #
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _fiscal_year(period: str) -> int | None:
    m = re.match(r"FY(\d{4})$", (period or "").strip(), re.I)
    return int(m.group(1)) if m else None


def _period_type(period: str) -> str:
    p = (period or "").strip().upper()
    if re.match(r"FY\d{4}$", p):
        return "ANNUAL"
    if re.match(r"Q[1-4]", p):
        return "QUARTERLY"
    if "YTD" in p or "SIX MONTHS" in p or "NINE MONTHS" in p:
        return "YTD"
    return "UNKNOWN"


def _cf_facts_by_period(facts) -> dict:
    out: dict = {}
    for f in facts:
        if f.source and f.source.target_key == "cash_flows" and f.period:
            out.setdefault(f.period, []).append(f)
    return out


# Phase 13 - a non-USD currency must not silently flow into a USD series.
_NON_USD_CURRENCY = re.compile(r"\b(EUR|GBP|JPY|CNY|RMB|CAD|AUD|CHF|SEK|BRL|INR|MXN)\b",
                               re.I)


def _scaled(f) -> float | None:
    unit = getattr(f, "unit", None)
    if unit and _NON_USD_CURRENCY.search(unit):
        return None          # a non-USD currency line is dropped, not converted
    s = resolve_scale(unit)
    return None if s is None else f.value * s


def _pick_ni(cf_by_period) -> dict:
    out: dict = {}
    for period, fs in cf_by_period.items():
        ni = [f for f in fs if _NET_INCOME.match(_norm(f.name).lower())]
        if not ni:
            continue
        pref = [f for f in ni if "non-controlling" in f.name.lower()
                or "including" in f.name.lower()]
        v = _scaled((pref or ni)[0])
        if v is not None:
            out[period] = v
    return out


# --------------------------------------------------------------------------- #
# Phase 9 - one-off evidence discovery (from verbatim quotes, no LLM)
# --------------------------------------------------------------------------- #
_ONE_OFF_LANG = re.compile(
    r"one-?time|non-?recurring|unusual|restructuring|litigation|settlement|"
    r"insurance recovery|tax refund|divestiture|acquisition-related|"
    r"special (payment|charge|item)|gain on sale|impairment|"
    r"lease termination|revaluation", re.I)


def _one_off_evidence(facts, fcff_by_period) -> OneOffEvidence:
    explicit: set[str] = set()
    for f in facts:
        if not f.source or f.source.target_key != "cash_flows":
            continue
        text = f"{_norm(f.name)} :: {getattr(f, 'quote', '')}"
        if _ONE_OFF_LANG.search(text):
            explicit.add(_norm(f.name))
    # corroborating: an explicit event caption AND a non-trivial cash figure
    # on that same line. On the CFO target these are all non-cash add-backs
    # already inside CFO, so they do not become a CASH one-off.
    corroborating: set[str] = set()
    for f in facts:
        if not f.source or f.source.target_key != "cash_flows":
            continue
        nm = _norm(f.name)
        if _ONE_OFF_LANG.search(nm) and abs(_scaled(f) or 0.0) > 1.0:
            m = map_reconciliation_caption(nm)
            if m.category is Category.OPERATING_CASH_ITEM:
                corroborating.add(nm)
    pattern: list[str] = []
    if fcff_by_period and len(fcff_by_period) >= 2:
        vals = [fcff_by_period[p] for p in sorted(fcff_by_period)]
        if any(a < 0 for a in vals) and any(a > 0 for a in vals):
            pattern.append("the reconstructed FCFF series changes sign")
        for a, b in zip(vals, vals[1:]):
            if a != 0 and abs(b - a) / abs(a) > 1.0:
                pattern.append("a year-over-year FCFF change exceeds 100%")
                break
    tier = (OneOffTier.CORROBORATING if corroborating else
            OneOffTier.EXPLICIT if explicit else
            OneOffTier.PATTERN_ONLY if pattern else OneOffTier.NONE)
    note = (
        "EXPLICIT one-off language appears only on NON-CASH reconciliation "
        "add-backs (impairments, gains/losses on sale, revaluations, lease "
        "terminations) which are already inside reported CFO - none is a "
        "one-time CASH item. No CORROBORATING cash one-off. Pattern evidence "
        "may inform REGIME_UNCERTAIN only; it never creates an adjustment.")
    return OneOffEvidence(tier, tuple(sorted(explicit)),
                          tuple(sorted(corroborating)), tuple(pattern), note)


# --------------------------------------------------------------------------- #
# Phase 8 - capex split evidence
# --------------------------------------------------------------------------- #
_MAINT_GROWTH = re.compile(
    r"(maintenance|growth|replacement|expansion|sustaining)\s+"
    r"cap(ex|ital expenditure)|capacity (expansion|investment)", re.I)


def _capex_evidence(facts) -> CapexEvidence:
    lines: dict = {}
    total_by_period: dict = {}
    split_hits: list[str] = []
    for f in facts:
        if not f.source or f.source.target_key != "cash_flows":
            continue
        nm = _norm(f.name)
        if _CAPEX.search(nm.lower()):
            base = re.sub(r"\s+FY\d{4}$", "", nm)
            lines.setdefault(base, 0)
            lines[base] += 1
            v = _scaled(f)
            if v is not None and f.period:
                total_by_period[f.period] = total_by_period.get(f.period, 0.0) + abs(v)
        if _MAINT_GROWTH.search(nm) or _MAINT_GROWTH.search(getattr(f, "quote", "")):
            split_hits.append(nm)
    distinct = sorted(lines)
    # a split is only "supported" if two DISTINCT capex lines are disclosed
    # per period AND at least one names a maintenance/growth category
    supported = len(distinct) >= 2 and bool(split_hits)
    return CapexEvidence(
        CapexSplitStatus.CAPEX_SPLIT_SUPPORTED if supported
        else CapexSplitStatus.CAPEX_SPLIT_NOT_SUPPORTED,
        total_by_period, tuple(distinct),
        ("two or more capex lines disclosed, one naming a maintenance/growth "
         "split" if supported else
         f"only {len(distinct)} capex line(s) disclosed "
         f"({', '.join(distinct) or 'none'}); no maintenance/growth/replacement "
         "split is a separate disclosed number. A split would be estimated, "
         "not evidenced - NOT_SUPPORTED."))


# --------------------------------------------------------------------------- #
# Phase 6 + 3 + 14 - per-period reconciliation + evidence status + score
# --------------------------------------------------------------------------- #
def _range_status(ranges, name) -> EvidenceStatus:
    r = ranges.get(name)
    if r is None:
        return EvidenceStatus.MISSING
    if r.status == "blocked":
        rat = (r.rationale or "").upper()
        if "AMBIG" in rat:
            return EvidenceStatus.AMBIGUOUS
        if "CONFLICT" in rat:
            return EvidenceStatus.CONFLICTING
        return EvidenceStatus.MISSING
    if r.status == "overridden":
        return EvidenceStatus.OVERRIDDEN
    return EvidenceStatus.VERIFIED


def _period_reconciliation(period, cf_facts, ni_by_period):
    cfo = capex = sbc = None
    ni = ni_by_period.get(period)
    noncash = 0.0
    wc_by_sub: dict = {}
    unclassified: dict = {}
    wc_total = 0.0
    for f in cf_facts:
        v = _scaled(f)
        if v is None:
            continue
        m = map_reconciliation_caption(_norm(f.name))
        if m.category is Category.CFO_SUBTOTAL:
            cfo = v
        elif m.category is Category.CAPEX:
            capex = abs(v)
        elif m.category is Category.SBC:
            sbc = abs(v)
            noncash += v
        elif m.category is Category.NON_CASH_RECONCILIATION:
            noncash += v
        elif m.category is Category.WORKING_CAPITAL:
            wc_total += v
            key = (m.wc_subcategory or WCSubcategory.WC_UNCLASSIFIED).value
            wc_by_sub[key] = wc_by_sub.get(key, 0.0) + v
            if m.mapping_confidence is MappingConfidence.LOW:
                unclassified[_norm(f.name)] = round(v, 3)
        elif m.category is Category.UNCLASSIFIED:
            # a cash-flow caption the mapper will not force into a bucket; it
            # is NOT summed into the reconciliation and it downgrades the
            # period's score. The residual it leaves is retained as evidence.
            unclassified[_norm(f.name)] = round(v, 3)
        # NET_INCOME / CASH_BALANCE / NON_OPERATING: excluded

    if cfo is None or ni is None:
        return (None, None, None, ReconciliationStatus.INSUFFICIENT_EVIDENCE,
                wc_by_sub, unclassified, capex, sbc)
    reconstructed = ni + noncash + wc_total
    residual = cfo - reconstructed
    tol = max(RECON_TOL_FRAC * abs(cfo), RECON_TOL_ABS)
    status = (ReconciliationStatus.RECONCILED if abs(residual) <= tol
              else ReconciliationStatus.RECONCILIATION_FAILED)
    return (cfo, reconstructed, residual, status, wc_by_sub, unclassified,
            capex, sbc)


def assess_evidence_depth(run) -> EvidenceDepthReport:
    doc_id = getattr(run, "doc_id", "")
    facts = list(getattr(run, "facts", []) or [])
    ranges = getattr(run, "ranges", {}) or {}
    bridged = getattr(run, "bridged", None)
    bound = getattr(bridged, "base_cash_flow_bound", None) or {}
    fcff_by_period = dict(bound.get("fcff_by_period") or {}) \
        if isinstance(bound, dict) and bound.get("available") else {}

    cf_by_period = _cf_facts_by_period(facts)
    ni_by_period = _pick_ni(cf_by_period)
    periods = sorted(cf_by_period)
    ann = [p for p in periods if _period_type(p) == "ANNUAL"]

    # caption mappings (deduplicated by base caption)
    seen: set[str] = set()
    mappings: list[CaptionMapping] = []
    for f in facts:
        if not f.source or f.source.target_key != "cash_flows":
            continue
        base = re.sub(r"\s+FY\d{4}$", "", _norm(f.name))
        if base in seen:
            continue
        seen.add(base)
        mappings.append(map_reconciliation_caption(base))
    mappings.sort(key=lambda m: (m.category.value, m.source_caption))

    # per-period reconciliation + coverage cells + score
    per_period: list[PeriodEvidence] = []
    coverage: list[EvidenceCell] = []
    p6_wc: dict = {}
    p8_wc_sum: dict = {}
    for p in periods:
        (cfo, recon, resid, rstat, wc_by_sub, unclassified, capex, sbc) = \
            _period_reconciliation(p, cf_by_period[p], ni_by_period)
        p8_wc_sum[p] = round(sum(wc_by_sub.values()), 6)

        # a component's evidence status: the derived range's status when it
        # exists (VERIFIED / OVERRIDDEN / AMBIGUOUS / CONFLICTING), downgraded
        # to INFERRED when the range has no observation for THIS period; when
        # no range exists at all, fall back to whether a fact for this period
        # was actually found on the cash-flow statement.
        # the CFO reconciliation itself is NI + non-cash + working capital =
        # CFO; interest lives on the operations target and is P6's concern,
        # not this scorecard's. Core components are the four extracted on the
        # cash-flow statement.
        fact_present = {
            "operating_cash_flow": cfo is not None,
            "capex": capex is not None,
            "stock_based_compensation": sbc is not None,
            "net_income": p in ni_by_period,
        }
        comp_status: dict = {}
        for comp, rng_name in (("operating_cash_flow", "operating_cash_flow"),
                               ("capex", "capex"),
                               ("stock_based_compensation", "stock_based_compensation"),
                               ("net_income", None)):
            r = ranges.get(rng_name) if rng_name else None
            if r is not None:
                st = _range_status(ranges, rng_name)
                has_p = any(o.period == p for o in r.observations)
                if st is EvidenceStatus.VERIFIED and not has_p:
                    st = EvidenceStatus.INFERRED
                lim = ("" if has_p or st is EvidenceStatus.OVERRIDDEN
                       else "no per-period observation; value carried from an "
                       "override / latest period")
            elif fact_present[comp]:
                st, lim = EvidenceStatus.OBSERVED, ""
            else:
                st, lim = EvidenceStatus.MISSING, f"no {comp} line for this period"
            comp_status.setdefault(st.value, []).append(comp)
            usable = st in (EvidenceStatus.OBSERVED, EvidenceStatus.VERIFIED,
                            EvidenceStatus.OVERRIDDEN)
            coverage.append(EvidenceCell(
                p, comp, "core", st, usable,
                _range_caption(ranges, rng_name), _range_unit(ranges, rng_name), lim))

        for sub, amt in sorted(wc_by_sub.items()):
            coverage.append(EvidenceCell(
                p, f"wc:{sub}", "working_capital", EvidenceStatus.OBSERVED,
                sub != WCSubcategory.WC_UNCLASSIFIED.value,
                sub, "USD (period scale)",
                "" if sub != WCSubcategory.WC_UNCLASSIFIED.value
                else "caption did not map to a known WC subcategory"))

        # period score. INSUFFICIENT is reserved for: not an annual period,
        # the CFO reconciliation cannot even be attempted (no CFO subtotal or
        # no net income), or a conflicting/ambiguous derivation. A merely
        # MISSING peripheral line (e.g. no separate capex line) or an
        # UNCLASSIFIED caption is PARTIALLY_EVIDENCED, not INSUFFICIENT.
        statuses = {EvidenceStatus(k) for k in comp_status}
        if _period_type(p) != "ANNUAL":
            score = PeriodScore.INSUFFICIENT_EVIDENCE
        elif rstat is ReconciliationStatus.RECONCILIATION_FAILED:
            score = PeriodScore.RECONCILIATION_FAILED
        elif rstat is ReconciliationStatus.INSUFFICIENT_EVIDENCE \
                or EvidenceStatus.CONFLICTING in statuses \
                or EvidenceStatus.AMBIGUOUS in statuses:
            score = PeriodScore.INSUFFICIENT_EVIDENCE
        elif EvidenceStatus.INFERRED in statuses:
            score = PeriodScore.INFERRED_COMPONENTS
        elif EvidenceStatus.MISSING in statuses or unclassified:
            score = PeriodScore.PARTIALLY_EVIDENCED
        else:
            score = PeriodScore.FULLY_EVIDENCED

        notes = []
        if unclassified:
            notes.append(f"{len(unclassified)} working-capital caption(s) "
                         "UNCLASSIFIED: " + "; ".join(unclassified))
        if rstat is ReconciliationStatus.RECONCILIATION_FAILED:
            notes.append(f"CFO reconciliation residual {resid:,.0f} exceeds "
                         "tolerance - retained as evidence, not discarded")

        per_period.append(PeriodEvidence(
            period=p, fiscal_year=_fiscal_year(p), period_type=_period_type(p),
            score=score, cfo_reported=cfo, cfo_reconstructed=recon,
            residual=resid, reconciliation_status=rstat,
            wc_by_subcategory={k: round(v, 3) for k, v in wc_by_sub.items()},
            unclassified_wc={k: round(v, 3) for k, v in unclassified.items()},
            components_by_status=comp_status, notes=tuple(notes)))

    # P6 impact: P6's wc_total is Sigma("change in" lines); P8's is the sum of
    # the SAME lines now labelled by subcategory. They must agree.
    try:
        from .bridge import _per_period_fcff  # noqa: F401  (proves import path)
    except Exception:  # noqa: BLE001
        pass
    for p in periods:
        wc = 0.0
        for f in cf_by_period[p]:
            v = _scaled(f)
            if v is None:
                continue
            if map_reconciliation_caption(_norm(f.name)).category is Category.WORKING_CAPITAL:
                wc += v
        p6_wc[p] = round(wc, 6)
    agree = all(abs(p6_wc.get(p, 0.0) - p8_wc_sum.get(p, 0.0)) < 1e-3
                for p in periods)

    capex_ev = _capex_evidence(facts)
    one_off = _one_off_evidence(facts, fcff_by_period)

    # Phase 23 honesty verdict. "reduces uncertainty" is about resolving
    # structural-vs-temporary, NOT about label richness. Component labelling
    # is a real gain in ATTRIBUTION but not in RESOLUTION when the filing
    # still discloses only three annual years, no capex split, and no
    # corroborating one-off CASH event.
    n_annual = len(ann)
    any_failed = any(pe.reconciliation_status is ReconciliationStatus.RECONCILIATION_FAILED
                     for pe in per_period)
    any_unclassified = any(pe.unclassified_wc for pe in per_period)
    has_cash_one_off = bool(one_off.corroborating_items)
    if capex_ev.status is CapexSplitStatus.CAPEX_SPLIT_NOT_SUPPORTED \
            and not has_cash_one_off and n_annual < 4:
        verdict = UncertaintyVerdict.NO_DISCLOSURE_BOUND
        vreason = (
            "richer extraction adds component labels, sign semantics and "
            "provenance to the SAME numbers P6 already used - a real gain in "
            "ATTRIBUTION - but it adds no years, no capex split, and no "
            "corroborating one-off CASH event. The working-capital recurrence "
            "question (is the insurance-reserve / accrued-liability build "
            "recurring float or timing?) is disclosure-bound: the filings do "
            "not separate the two. Regime stays REGIME_UNCERTAIN.")
    elif not any_failed and not any_unclassified and n_annual >= 4 and not has_cash_one_off:
        verdict = UncertaintyVerdict.YES_PARTIAL
        vreason = ("every disclosed annual period reconciles and every "
                   "working-capital caption maps to a known subcategory across "
                   ">=4 years; the component attribution is materially stronger, "
                   "though still short of fully resolving structural vs temporary.")
    elif has_cash_one_off or (not any_failed and not any_unclassified and n_annual >= 5):
        verdict = UncertaintyVerdict.YES_MATERIAL
        vreason = ("a corroborated one-off cash event and/or a deep clean "
                   "annual history is available; the regime question can be "
                   "materially narrowed.")
    else:
        verdict = UncertaintyVerdict.YES_PARTIAL
        vreason = ("component-level working-capital labelling and per-period "
                   "evidence status are now explicit, which sharpens the "
                   "attribution without resolving the regime question.")

    notes = (
        "EXPERIMENTAL: this layer classifies evidence; it changes no "
        "valuation number and promotes neither P6 nor P7.",
        f"{n_annual} annual period(s); {'all reconcile' if not any_failed else 'a reconciliation failed'}.",
        "P6 working-capital totals are unchanged - P8 only labels the same "
        "reconciliation lines by subcategory and records their provenance.",
    )
    return EvidenceDepthReport(
        doc_id=doc_id, periods=tuple(periods),
        oldest_period=periods[0] if periods else "",
        newest_period=periods[-1] if periods else "",
        caption_mappings=tuple(mappings), coverage=tuple(coverage),
        period_evidence=tuple(per_period), capex_evidence=capex_ev,
        one_off_evidence=one_off, p6_wc_total_by_period=p6_wc,
        p8_wc_component_sum_by_period=p8_wc_sum, p6_p8_wc_agree=agree,
        reduces_uncertainty=verdict, reduces_uncertainty_reason=vreason,
        notes=notes)


def _range_caption(ranges, name):
    if name is None:
        return "net income (incl. NCI)"
    r = ranges.get(name)
    if r is None or not r.observations:
        return name
    return r.observations[-1].fact_name


def _range_unit(ranges, name):
    if name is None:
        return "USD (period scale)"
    r = ranges.get(name)
    return (r.unit if r is not None else "unknown")
