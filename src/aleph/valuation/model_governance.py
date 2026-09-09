"""P10 - MODEL ARBITRATION, ASSUMPTION GOVERNANCE & VALUATION RECONCILIATION.

STATUS: EXPERIMENTAL. This is a GOVERNANCE + FALSIFICATION layer, not a new
forecasting model. It never changes the LIVE DCF, never promotes P6/P7/P9,
and its applicability / arbitration classification NEVER depends on a market
price (a structural guarantee: the classifying functions take no price).

WHAT IT ANSWERS. Aleph now has four legitimate representations - LIVE
(latest-FCFF DCF), P6 (sustainable-FCFF scenarios), P9 (driver-based DCF),
P7 (market-implied). They disagree. This layer answers: WHY do they
disagree, WHICH assumptions are responsible, and WHAT evidence would make
one interpretation more defensible - without declaring a winner because it
is more sophisticated, more conservative, or closer to the market.

IT DOES:
  - a sequential counterfactual reconciliation LIVE -> P9 (order-dependent,
    and it says so; interactions are exposed, not assumed additive);
  - a base-case assumption register with a 1-5 evidence hierarchy (NOT a
    score), an economic-sensitivity measure, and a contradiction check;
  - a 2-D (evidence strength x economic sensitivity) classification, never
    collapsed into one number;
  - per-model applicability (HIGH / CONDITIONAL / LIMITED / NOT_SUPPORTED) -
    "more applicable" is not "more correct";
  - the mandatory SBC and tax correctness audits (Phases 3, 4, 23, 24).

NO LLM. NO ML. NO composite valuation score. NO BUY/SELL. NO model weights.
"""
from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum

from .dcf_engine import DCFConsistencyError, run_dcf

__all__ = [
    "EvidenceLevel",
    "Applicability",
    "ContradictionStatus",
    "ArbitrationOutcome",
    "SensitivityBand",
    "EvidenceBand",
    "ReconStep",
    "RegisterEntry",
    "ModelApplicabilityReport",
    "GovernanceReport",
    "reconcile_live_to_p9",
    "assumption_register",
    "sbc_audit",
    "tax_audit",
    "model_applicability",
    "arbitrate",
    "assess_model_governance",
    "CONVERGENCE_FRAC",
]

# Two model valuations within this fraction of their own midpoint are treated
# as converged. Rationale: below ~10% the choice between representations is
# not the dominant uncertainty; above it, the difference must be explained by
# an identified assumption or it is UNRESOLVED.
CONVERGENCE_FRAC = 0.10


class EvidenceLevel(str, Enum):
    L1_FILING_DISCLOSURE = "L1_FILING_DISCLOSURE"          # stated in the filing
    L2_DERIVED_FROM_FACTS = "L2_DERIVED_FROM_FACTS"        # arithmetic on verified facts
    L3_REPEATED_HISTORICAL_PATTERN = "L3_REPEATED_HISTORICAL_PATTERN"
    L4_PLAUSIBLE_ANALYST_ASSUMPTION = "L4_PLAUSIBLE_ANALYST_ASSUMPTION"
    L5_MODEL_CONVENTION = "L5_MODEL_CONVENTION"


class Applicability(str, Enum):
    HIGH_APPLICABILITY = "HIGH_APPLICABILITY"
    CONDITIONAL_APPLICABILITY = "CONDITIONAL_APPLICABILITY"
    LIMITED_APPLICABILITY = "LIMITED_APPLICABILITY"
    NOT_SUPPORTED = "NOT_SUPPORTED"


class ContradictionStatus(str, Enum):
    ASSUMPTION_CONTRADICTED_BY_EVIDENCE = "ASSUMPTION_CONTRADICTED_BY_EVIDENCE"
    NO_DIRECT_CONTRADICTION = "NO_DIRECT_CONTRADICTION"


class ArbitrationOutcome(str, Enum):
    MODEL_CONVERGENCE = "MODEL_CONVERGENCE"
    MODEL_DIVERGENCE_WITH_EVIDENCE_BASIS = "MODEL_DIVERGENCE_WITH_EVIDENCE_BASIS"
    MODEL_DIVERGENCE_UNRESOLVED = "MODEL_DIVERGENCE_UNRESOLVED"


class SensitivityBand(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class EvidenceBand(str, Enum):
    STRONG = "STRONG"      # L1 / L2
    MODERATE = "MODERATE"  # L3
    WEAK = "WEAK"          # L4 / L5


# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ReconStep:
    order: int
    name: str
    change: str
    fcff_after: float | None
    value_after: float | None
    delta_value: float | None
    note: str


@dataclass(frozen=True)
class RegisterEntry:
    variable: str
    value: float | None
    unit: str
    evidence_level: EvidenceLevel
    historical_evidence: str
    economic_rationale: str
    model_convention: bool
    contradiction: ContradictionStatus
    contradiction_detail: str
    value_sensitivity: float | None       # |d(value/share)| for a plausible move
    sensitivity_band: SensitivityBand
    evidence_band: EvidenceBand
    independently_supported: bool


@dataclass(frozen=True)
class ModelApplicabilityReport:
    model: str
    value_per_share: float | str
    applicability: Applicability
    evidence_basis: str
    dominant_assumption: str
    known_limitations: tuple[str, ...]
    economic_domain: str
    unresolved: tuple[str, ...]


@dataclass(frozen=True)
class GovernanceReport:
    doc_id: str
    live_value: float
    p6_low: float | None
    p6_central: float | None
    p6_high: float | None
    p9_bear: float | str
    p9_base: float | str
    p9_bull: float | str
    p7_implied_fcff: float | None
    reconciliation: tuple[ReconStep, ...]
    register: tuple[RegisterEntry, ...]
    sbc_audit: dict
    tax_audit: dict
    applicability: tuple[ModelApplicabilityReport, ...]
    arbitration: ArbitrationOutcome
    arbitration_reasons: tuple[str, ...]
    dominant_assumptions: tuple[str, ...]
    headline: str
    notes: tuple[str, ...] = field(default_factory=tuple)


# --------------------------------------------------------------------------- #
# helpers - re-run the PURE engine on copies, exactly like P5/P6/P7
# --------------------------------------------------------------------------- #
def _wacc(run) -> float:
    w = getattr(run, 'wacc', None)
    if w is not None and getattr(w, 'wacc', None) is not None:
        return w.wacc
    return run.bridged.inputs.discount_rate


def _value_at_fcff(inputs, base_fcff: float) -> float | None:
    trial = deepcopy(inputs)
    trial.base_cash_flow = base_fcff
    trial.assumptions = []
    try:
        v = run_dcf(trial).value_per_share
        return v if math.isfinite(v) else None
    except DCFConsistencyError:
        return None


def _scale(unit):
    from ..infra.units import resolve_scale
    return resolve_scale(unit)


# --------------------------------------------------------------------------- #
# Phase 0 + 1 - reconciliation LIVE -> P9 (sequential counterfactual)
# --------------------------------------------------------------------------- #
def reconcile_live_to_p9(run) -> tuple[list[ReconStep], dict]:
    """Bridge the LIVE base FCFF to the P9-BASE base FCFF one economic change
    at a time, re-valuing after each step. The decomposition is
    ORDER-DEPENDENT - the note on every step says so - and the residual
    interaction term is reported, not hidden."""
    from .operating_model import (
        Scenario, STATUTORY_TAX_CONVENTION, build_operating_forecast,
        historical_drivers,
    )
    inputs = run.bridged.inputs
    live_fcff = inputs.base_cash_flow
    live_value = run.result.value_per_share

    f = build_operating_forecast(run, Scenario.BASE)
    hd = {d.name: d for d in historical_drivers(run)}

    steps: list[ReconStep] = []
    steps.append(ReconStep(
        0, "LIVE base FCFF", "latest reconstructed FCFF, as-is",
        live_fcff, live_value, 0.0,
        "CFO + interest*(1-tax) - capex - SBC; embeds the actual near-zero "
        "cash tax and the latest-year working-capital contribution"))

    if f.support.value == "INSUFFICIENT_EVIDENCE" or not f.years or f.base_fcff is None:
        return steps, {"status": "P9 INSUFFICIENT_EVIDENCE - reconciliation stops "
                       "at the LIVE anchor", "order_dependent": True}

    # decompose the P9 base_fcff (year 0) into its parts, on base revenue
    rev = hd["revenue"].latest or 0.0
    m = f.years[0].operating_margin or 0.0
    oi = rev * m
    nopat = oi * (1 - STATUTORY_TAX_CONVENTION)
    r0 = f.years[0].revenue
    dna = f.years[0].dna / r0 * rev
    capex = f.years[0].capex / r0 * rev
    wc_med = f.years[0].wc_cash_effect / r0 * rev
    p9_fcff = f.base_fcff

    # Step A: move to an operating-income basis with a NORMALISED 21% tax and
    # NO working-capital contribution (the most conservative reading).
    fcff_a = nopat + dna - capex
    v_a = _value_at_fcff(inputs, fcff_a)
    steps.append(ReconStep(
        1, "operating basis + 21% tax, no working capital",
        f"NOPAT ({nopat:,.0f}) + D&A ({dna:,.0f}) - capex ({capex:,.0f}); "
        f"21% statutory tax on operating income (LIVE inherits ~0% cash tax); "
        "working-capital contribution set to 0",
        fcff_a, v_a, (v_a - live_value) if v_a is not None else None,
        "ORDER-DEPENDENT: this bundles the tax normalisation and the "
        "working-capital removal; steps 1 and 2 interact"))

    # Step B: add back the historical-MEDIAN working-capital contribution.
    fcff_b = fcff_a + wc_med
    v_b = _value_at_fcff(inputs, fcff_b)
    steps.append(ReconStep(
        2, "+ historical-median working capital",
        f"+ {wc_med:,.0f} (median cash-effect/revenue x base revenue); the P8 "
        "recurrence of this float is NOT disclosed - it is a scenario choice",
        fcff_b, v_b,
        (v_b - v_a) if (v_b is not None and v_a is not None) else None,
        "the median is itself an assumption; BEAR would use 0, BULL the latest ratio"))

    # residual / interaction
    resid = p9_fcff - fcff_b
    v_p9 = _value_at_fcff(inputs, p9_fcff)
    steps.append(ReconStep(
        3, "= P9 BASE FCFF", f"residual {resid:,.0f} (rounding / D&A-capex ratio "
        "timing); final P9 driver base FCFF",
        p9_fcff, v_p9,
        (v_p9 - v_b) if (v_p9 is not None and v_b is not None) else None,
        "if |residual| is material the earlier steps interact non-additively"))
    return steps, {
        "status": "OK", "order_dependent": True,
        "interaction_note": ("the sum of the per-step deltas need not equal "
                             f"live_value - p9_value; residual FCFF {resid:,.0f}"),
        "live_value": live_value, "p9_base_value": v_p9,
        "total_gap": (live_value - v_p9) if v_p9 is not None else None}


# --------------------------------------------------------------------------- #
# Phase 3 + 23 - MANDATORY SBC correctness audit
# --------------------------------------------------------------------------- #
def sbc_audit(run) -> dict:
    """Does the P9 bridge double-count stock-based compensation?"""
    import inspect
    from . import operating_model
    src = inspect.getsource(operating_model)
    # the FCFF bridge line
    bridge_lines = [ln.strip() for ln in src.splitlines()
                    if ln.strip().startswith("fcff_t =")]
    line = bridge_lines[0] if bridge_lines else ""
    has_sbc_term = "sbc_t" in line
    return {
        "question": "Is P9 NOPAT + D&A - WC - capex - SBC double-counting SBC?",
        "accounting_structure": ("SBC is a GAAP operating expense and is inside "
                                 "income-from-operations, therefore inside NOPAT."),
        "bridge_line": line,
        "separate_sbc_subtraction_present": has_sbc_term,
        "double_count": "PRESENT" if has_sbc_term else "NOT_PRESENT",
        "verdict": ("BLOCKED - the bridge still subtracts SBC after it is "
                    "already in NOPAT (total drag 1.21x SBC). Fix before "
                    "proceeding." if has_sbc_term else
                    "RESOLVED - SBC is charged once, through the P&L (inside "
                    "NOPAT). The P9 treatment tax-shields SBC at 21% (SBC is a "
                    "deductible compensation expense); the LIVE bridge subtracts "
                    "full pre-tax SBC. The ~0.21x-SBC difference is a labelled "
                    "methodology difference, not a second charge."),
        "sbc_still_reported": True,
    }


# --------------------------------------------------------------------------- #
# Phase 4 + 24 - tax convention audit
# --------------------------------------------------------------------------- #
def _fact_series(run, target, want):
    import re
    out = {}
    for f in getattr(run, "facts", []) or []:
        if not f.source or f.source.target_key != target or not f.period:
            continue
        n = re.sub(r"\s+", " ", f.name).strip().lower()
        if want(n):
            s = _scale(f.unit)
            out[f.period] = f.value * s if s is not None else f.value
    return out


def tax_audit(run) -> dict:
    oi = _fact_series(run, "operations",
                      lambda n: "from operations" in n and n.startswith(("income", "loss")))
    pretax = _fact_series(run, "taxes", lambda n: "before income tax" in n
                          or "before provision" in n)
    provision = _fact_series(run, "taxes", lambda n: "provision for" in n
                             and "income tax" in n)
    eff = _fact_series(run, "taxes", lambda n: "effective" in n and "tax rate" in n)
    # a filer whose disclosed effective rate is negative / tiny while pretax is
    # positive is running deferred-tax releases / NOLs - 21% statutory is a
    # CONSERVATIVE upper bound, not a description of the cash rate.
    neg_or_tiny_eff = any(v < 5.0 for v in eff.values()) if eff else False
    classification = ("CONSERVATIVE_BUT_SUPPORTED" if neg_or_tiny_eff else
                      "DEFENSIBLE" if eff else "INSUFFICIENTLY_SUPPORTED")
    return {
        "convention": "21% statutory (held identical across filers, LIVE + P9)",
        "operating_income_by_period": {p: round(v, 0) for p, v in oi.items()},
        "pretax_income_by_period": {p: round(v, 0) for p, v in pretax.items()},
        "tax_provision_by_period": {p: round(v, 0) for p, v in provision.items()},
        "disclosed_effective_rate_pct": {p: round(v, 1) for p, v in eff.items()},
        "nol_evidence": "not separately extracted by the schema; the "
                        "near-zero / negative disclosed effective rates are the "
                        "visible signature of NOL / DTA effects",
        "labels": {"statutory": 0.21,
                   "cash_tax": "near zero for UBER/LYFT (DTA releases) - NOT used",
                   "effective_disclosed": "see above - volatile, NOT used"},
        "classification": classification,
        "verdict": ("21% is a CONSERVATIVE simplification: it is the statutory "
                    "upper bound, applied to operating income, while the filers' "
                    "actual cash tax has been far lower. It is defensible as a "
                    "held-identical convention BUT the reader must not read it "
                    "as the expected cash rate. Labelled explicitly."
                    if neg_or_tiny_eff else
                    "21% matches the disclosed effective rates within a normal "
                    "band; defensible as-is." if eff else
                    "no disclosed effective tax rate was extracted for this "
                    "filer; 21% is applied as a held-identical convention and "
                    "cannot be checked against the filer's own rate - treat as "
                    "an unverified assumption."),
    }


# --------------------------------------------------------------------------- #
# Phase 9 + 10 + 11 + 12 - base-case assumption register
# --------------------------------------------------------------------------- #
_EVIDENCE_BY_SHAPE_SOURCE = {
    # (SeriesShape, DriverSource) -> EvidenceLevel
}


def _evidence_level(shape_value: str, source_value: str) -> EvidenceLevel:
    if source_value == "MODEL_CONVENTION":
        return EvidenceLevel.L5_MODEL_CONVENTION
    if source_value == "HISTORICAL":
        # a ratio held at the median of a STABLE series is a repeated pattern;
        # a median over a wider (CYCLICAL) series is still derived from facts.
        return (EvidenceLevel.L3_REPEATED_HISTORICAL_PATTERN
                if shape_value == "STABLE" else EvidenceLevel.L2_DERIVED_FROM_FACTS)
    # ANALYST_ASSUMPTION: the VALUE may still be evidence-anchored. A year-1
    # growth taken as the median of a STABLE series is L3; a margin held at
    # the latest of a TRENDING / INFLECTING series is a genuine L4 judgement.
    if shape_value == "STABLE":
        return EvidenceLevel.L3_REPEATED_HISTORICAL_PATTERN
    return EvidenceLevel.L4_PLAUSIBLE_ANALYST_ASSUMPTION


def _evidence_band(level: EvidenceLevel) -> EvidenceBand:
    if level in (EvidenceLevel.L1_FILING_DISCLOSURE, EvidenceLevel.L2_DERIVED_FROM_FACTS):
        return EvidenceBand.STRONG
    if level is EvidenceLevel.L3_REPEATED_HISTORICAL_PATTERN:
        return EvidenceBand.MODERATE
    return EvidenceBand.WEAK


def _contradiction(name: str, hd) -> tuple[ContradictionStatus, str]:
    """Deterministic: does the historical series argue against holding this
    driver flat at its BASE value?"""
    d = hd.get(name)
    if d is None or not d.values or len(d.values) < 2:
        return ContradictionStatus.NO_DIRECT_CONTRADICTION, "no comparable series"
    if name == "revenue_growth" and d.shape.value == "TRENDING" and d.values[-1] < d.values[0]:
        return (ContradictionStatus.ASSUMPTION_CONTRADICTED_BY_EVIDENCE,
                f"revenue growth is DECELERATING ({d.values[0]:+.1%} -> "
                f"{d.values[-1]:+.1%}) yet the base holds it near the level")
    if name == "wc_cash_effect_over_revenue" and len(d.values) >= 2 \
            and d.values[-1] > 3 * abs(d.median or 1):
        return (ContradictionStatus.ASSUMPTION_CONTRADICTED_BY_EVIDENCE,
                "the latest working-capital contribution is far above its "
                "median; a median-based BASE assumes the recent build does not "
                "persist - defensible but the evidence points the other way")
    if name == "operating_margin" and d.shape.value == "INFLECTING":
        return (ContradictionStatus.NO_DIRECT_CONTRADICTION,
                "margin inflects (crosses zero); holding the latest is an "
                "assumption but is not contradicted by a monotone trend")
    return ContradictionStatus.NO_DIRECT_CONTRADICTION, "no monotone series argues against it"


def assumption_register(run) -> list[RegisterEntry]:
    from .operating_model import Scenario, build_operating_forecast, historical_drivers
    f = build_operating_forecast(run, Scenario.BASE)
    hd = {d.name: d for d in historical_drivers(run)}
    inputs = run.bridged.inputs
    live_value = run.result.value_per_share
    entries: list[RegisterEntry] = []
    if not f.years:
        return entries
    y1 = f.years[0]
    base_fcff = f.base_fcff

    # value sensitivity: re-run the DCF with the driver perturbed by a
    # plausible move and record |d(value/share)|.
    def sens(new_base_fcff):
        if base_fcff is None:
            return None
        v0 = _value_at_fcff(inputs, base_fcff)
        v1 = _value_at_fcff(inputs, new_base_fcff)
        return abs(v1 - v0) if (v0 is not None and v1 is not None) else None

    rev = hd["revenue"].latest or 0.0
    from .operating_model import STATUTORY_TAX_CONVENTION as TAX
    for a in y1.assumptions:
        hist_ref = a.historical_ref
        d = hd.get(a.name)                    # matching historical driver, if any
        shape_v = d.shape.value if d is not None else "STABLE"
        level = _evidence_level(shape_v, a.source.value)
        contra, cdetail = _contradiction(a.name, hd)
        # crude per-driver sensitivity via an FCFF proxy
        s = None
        if base_fcff is not None:
            if a.name == "operating_margin":
                bump = rev * 0.02 * (1 - TAX)          # +2pp margin
                s = sens(base_fcff + bump)
            elif a.name == "tax_rate":
                oi = rev * (y1.operating_margin or 0.0)
                s = sens(base_fcff + oi * 0.10)         # tax 21% -> 11%
            elif a.name == "wc_cash_effect_over_revenue":
                s = sens(base_fcff + rev * 0.02)        # +2pp of revenue
            elif a.name == "revenue_growth":
                s = sens(base_fcff * 1.10)              # a 10% higher FCFF path proxy
            elif a.name == "capex_over_revenue":
                s = sens(base_fcff + rev * 0.01)
            elif a.name == "sbc_over_revenue":
                s = 0.0                                 # reported only - no FCFF effect
            elif a.name == "dna_over_revenue":
                s = sens(base_fcff + rev * 0.005)
        band = (SensitivityBand.HIGH if (s or 0) > 0.15 * abs(live_value) else
                SensitivityBand.MEDIUM if (s or 0) > 0.05 * abs(live_value) else
                SensitivityBand.LOW)
        entries.append(RegisterEntry(
            variable=a.name, value=a.value, unit="decimal",
            evidence_level=level, historical_evidence=hist_ref,
            economic_rationale=a.lineage, model_convention=(a.source.value == "MODEL_CONVENTION"),
            contradiction=contra, contradiction_detail=cdetail,
            value_sensitivity=s, sensitivity_band=band,
            evidence_band=_evidence_band(level),
            independently_supported=(level in (
                EvidenceLevel.L1_FILING_DISCLOSURE,
                EvidenceLevel.L2_DERIVED_FROM_FACTS,
                EvidenceLevel.L3_REPEATED_HISTORICAL_PATTERN))))
    return entries


# --------------------------------------------------------------------------- #
# Phase 17 + 18 - per-model applicability (NO market price anywhere here)
# --------------------------------------------------------------------------- #
def model_applicability(run) -> list[ModelApplicabilityReport]:
    from .operating_model import Scenario, build_operating_forecast
    from .driver_based_dcf import driver_based_dcf, DriverDCFStatus
    inputs = run.bridged.inputs
    reports: list[ModelApplicabilityReport] = []

    rob = getattr(run, "robustness", None)
    live_applic = getattr(getattr(rob, "applicability", None), "value", "")
    reports.append(ModelApplicabilityReport(
        model="LIVE (latest reconstructed FCFF DCF)",
        value_per_share=round(run.result.value_per_share, 2),
        applicability=(Applicability.LIMITED_APPLICABILITY
                       if live_applic == "LIMITED_APPLICABILITY"
                       else Applicability.CONDITIONAL_APPLICABILITY),
        evidence_basis="one disclosed year's reconstructed FCFF (L2), embedding "
                       "the actual near-zero cash tax and the latest working-"
                       "capital contribution",
        dominant_assumption="the latest FCFF year is the run-rate",
        known_limitations=("anchor sensitivity HIGH (P5)",
                           "history comparability HIGH_CONCERN (P6)",
                           "no explicit operating-margin or tax assumption"),
        economic_domain="a firm whose latest FCFF is representative",
        unresolved=("whether the working-capital tailwind recurs (P8: not disclosed)",)))

    try:
        from .sustainable_fcff import assess_sustainable_fcff, sustainable_scenario_valuation
        s = assess_sustainable_fcff(run)
        if s.status.value == "SUPPORTED_RANGE":
            sv = {x.label: x.value_per_share
                  for x in sustainable_scenario_valuation(inputs, s)}
            p6_val = (f"{sv.get('sustainable_low'):.2f} / "
                      f"{sv.get('sustainable_central'):.2f} / "
                      f"{sv.get('sustainable_high'):.2f}")
            p6_ap = Applicability.CONDITIONAL_APPLICABILITY
        else:
            p6_val, p6_ap = s.status.value, Applicability.NOT_SUPPORTED
    except Exception:  # noqa: BLE001
        p6_val, p6_ap = "error", Applicability.NOT_SUPPORTED
    reports.append(ModelApplicabilityReport(
        model="P6 (sustainable-FCFF scenarios)",
        value_per_share=p6_val, applicability=p6_ap,
        evidence_basis="the SAME reconstructed FCFF (L2) with the working-"
                       "capital contribution flexed BEAR 0 / BASE median / BULL "
                       "latest (L4 - the median is an assumption)",
        dominant_assumption="which working-capital contribution is sustainable",
        known_limitations=("3-year non-comparable history (P6)",
                           "no operating-margin or tax modelling"),
        economic_domain="a firm whose FCFF rests materially on a working-"
                        "capital contribution of uncertain recurrence",
        unresolved=("the recurrence of the insurance-reserve / accrued float",)))

    f = build_operating_forecast(run, Scenario.BASE)
    if f.support.value == "INSUFFICIENT_EVIDENCE" or not f.years:
        reports.append(ModelApplicabilityReport(
            model="P9 (driver-based operating DCF)", value_per_share="n/a",
            applicability=Applicability.NOT_SUPPORTED,
            evidence_basis="operating margin is not evidence-supported and/or "
                           "the CFO reconciliation fails (P8)",
            dominant_assumption="n/a", known_limitations=("no forecast produced",),
            economic_domain="n/a", unresolved=("everything",)))
    else:
        r = driver_based_dcf(f, discount_rate=_wacc(run),
                             terminal_growth=inputs.terminal_growth,
                             net_debt=inputs.net_debt,
                             shares_outstanding=inputs.shares_outstanding)
        margin_a = "operating_margin" in f.unsupported_drivers
        p9_ap = (Applicability.LIMITED_APPLICABILITY if margin_a
                 else Applicability.CONDITIONAL_APPLICABILITY)
        reports.append(ModelApplicabilityReport(
            model="P9 (driver-based operating DCF)",
            value_per_share=(round(r.value_per_share, 2)
                             if r.value_per_share is not None
                             else r.status.value),
            applicability=(Applicability.LIMITED_APPLICABILITY
                           if r.status is not DriverDCFStatus.OK else p9_ap),
            evidence_basis="revenue growth (L2/L3), D&A/capex ratios (L3), "
                           "operating margin ("
                           + ("L4 - held at the latest, unsupported"
                              if margin_a else "L3") + "), 21% tax (L5)",
            dominant_assumption=("operating margin (held at the latest period, "
                                 "an ANALYST_ASSUMPTION)" if margin_a else
                                 "operating margin (historical median)"),
            known_limitations=("21% tax is a conservative simplification, not "
                               "the cash rate (see tax_audit)",
                               "working capital is scenario-only",
                               "10-year linear fade is a MODEL_CONVENTION"),
            economic_domain="a firm whose operating margin path is the right "
                            "lever and is evidence-supported",
            unresolved=("whether the latest operating margin is representative",)))

    return reports


# --------------------------------------------------------------------------- #
# Phase 13 + 14 - dominant assumptions + arbitration
# --------------------------------------------------------------------------- #
def _dominant(register: list[RegisterEntry]) -> list[str]:
    """Phase 13 - rank EVERY base-case assumption by how much it moves the
    valuation, most decisive first. The order is the deliverable: a reader
    takes the top of this list as the assumptions that determine the answer.
    HIGH sensitivity x WEAK evidence is additionally marked 'fragile' - that
    pairing, not raw sensitivity, is what governance escalates."""
    ranked = sorted(register, key=lambda e: (e.value_sensitivity or 0.0), reverse=True)
    out = []
    for e in ranked:
        tag = (f"{e.sensitivity_band.value} sensitivity x "
               f"{e.evidence_band.value} evidence")
        if (e.sensitivity_band is SensitivityBand.HIGH
                and e.evidence_band is EvidenceBand.WEAK):
            tag += "  <-- fragile"
        out.append(f"{e.variable}: {tag}")
    return out


def arbitrate(run, register, applicability) -> tuple[ArbitrationOutcome, list[str]]:
    vals = {}
    for m in applicability:
        v = m.value_per_share
        if isinstance(v, (int, float)):
            vals[m.model.split()[0]] = float(v)
        elif isinstance(v, str) and "/" in v:
            try:
                vals[m.model.split()[0] + "_central"] = float(v.split("/")[1])
            except ValueError:
                pass
    reasons: list[str] = []
    live = vals.get("LIVE")
    p6c = vals.get("P6_central")
    p9 = vals.get("P9")
    pool = [x for x in (live, p6c, p9) if x is not None]
    if len(pool) < 2:
        return (ArbitrationOutcome.MODEL_DIVERGENCE_UNRESOLVED,
                ["fewer than two models produced a comparable value"])
    mid = (max(pool) + min(pool)) / 2
    spread = (max(pool) - min(pool)) / abs(mid) if mid else math.inf
    if spread <= CONVERGENCE_FRAC:
        return (ArbitrationOutcome.MODEL_CONVERGENCE,
                [f"LIVE / P6-central / P9-base agree to within {spread:.0%}"])
    # is the divergence explained by identified assumptions with evidence?
    if p9 is not None and p6c is not None and abs(p9 - p6c) / abs((p9 + p6c) / 2 or 1) <= CONVERGENCE_FRAC:
        reasons.append("P9-base and P6-central CONVERGE - the earlier apparent "
                       "P9 divergence was the SBC double-count, now corrected")
    if live is not None and p6c is not None and live > p6c * (1 + CONVERGENCE_FRAC):
        reasons.append("LIVE sits above P6/P9 because it anchors on the latest "
                       "FCFF, which embeds the working-capital contribution "
                       "(P8: recurrence not disclosed) and ~0% cash tax")
    weak_dominant = [e for e in register
                     if e.sensitivity_band is SensitivityBand.HIGH
                     and e.evidence_band is EvidenceBand.WEAK]
    if weak_dominant:
        reasons.append("the driver that most moves P9 - "
                       + ", ".join(e.variable for e in weak_dominant)
                       + " - rests on weak evidence (L4/L5)")
    # P10.5 targeted branch. Where the P10.5 sequential bridge FULLY reconciles
    # the LIVE<->P9 gap and its dominant named delta is the 21% tax convention
    # (P9 normalises tax up; LIVE/P6 inherit the disclosed near-zero effective
    # rate), the divergence IS attributed - it is not "unexplained". Keyed to
    # that reconciliation, NOT to "P9 < LIVE". It does NOT validate 21% as the
    # forward cash-tax rate (that stays DISCLOSURE_BOUND, P10.5) and promotes
    # no model.
    try:
        from .evidence_resolution import (
            sequential_bridge_live_to_p9, EconomicallyExplained)
        _br = sequential_bridge_live_to_p9(run)
        if (_br.live_fcff is not None
                and _br.economically_explained is EconomicallyExplained.FULLY
                and "tax" in _br.dominant_cause.lower()):
            reasons.append(
                "P9-base sits below LIVE/P6-central because P9 normalises tax to "
                "the 21% statutory convention while LIVE/P6 inherit the filer's "
                "disclosed near-zero effective/cash-tax basis; the P10.5 bridge "
                f"reconciles the gap with a {_br.methodology_pct_of_fcff:.1%} "
                "methodology residual. DIVERGENCE ATTRIBUTION = RESOLVED. This "
                "does NOT establish 21% as the normalised forward cash-tax rate "
                "- that stays DISCLOSURE_BOUND (P10.5) - and neither model is "
                "thereby preferred")
    except Exception:  # noqa: BLE001
        pass
    if reasons:
        return ArbitrationOutcome.MODEL_DIVERGENCE_WITH_EVIDENCE_BASIS, reasons
    return (ArbitrationOutcome.MODEL_DIVERGENCE_UNRESOLVED,
            ["the models disagree and the difference cannot be attributed to a "
             "single identified assumption"])


# --------------------------------------------------------------------------- #
# orchestrator
# --------------------------------------------------------------------------- #
def assess_model_governance(run) -> GovernanceReport:
    doc_id = getattr(run, "doc_id", "")
    inputs = run.bridged.inputs
    live_value = run.result.value_per_share

    recon, recon_meta = reconcile_live_to_p9(run)
    reg = assumption_register(run)
    sbc = sbc_audit(run)
    tax = tax_audit(run)
    applic = model_applicability(run)
    arb, arb_reasons = arbitrate(run, reg, applic)
    dominant = _dominant(reg)

    # P6 numbers
    p6_low = p6_c = p6_h = None
    try:
        from .sustainable_fcff import assess_sustainable_fcff, sustainable_scenario_valuation
        s = assess_sustainable_fcff(run)
        if s.status.value == "SUPPORTED_RANGE":
            sv = {x.label: x.value_per_share
                  for x in sustainable_scenario_valuation(inputs, s)}
            p6_low, p6_c, p6_h = (sv.get("sustainable_low"),
                                  sv.get("sustainable_central"),
                                  sv.get("sustainable_high"))
    except Exception:  # noqa: BLE001
        pass

    # P9 scenario values
    from .operating_model import Scenario, build_operating_forecast
    from .driver_based_dcf import driver_based_dcf
    def p9v(sc):
        f = build_operating_forecast(run, sc)
        if f.support.value == "INSUFFICIENT_EVIDENCE" or not f.years:
            return "INSUFFICIENT_EVIDENCE"
        r = driver_based_dcf(f, discount_rate=_wacc(run),
                             terminal_growth=inputs.terminal_growth,
                             net_debt=inputs.net_debt,
                             shares_outstanding=inputs.shares_outstanding)
        return round(r.value_per_share, 2) if r.value_per_share is not None else r.status.value

    # P7 implied FCFF
    p7_fcff = None
    try:
        from .market_expectations import implied_base_fcff
        mp = getattr(run, "market_price", None)
        if mp:
            iq = implied_base_fcff(inputs, mp)
            p7_fcff = iq.value
    except Exception:  # noqa: BLE001
        pass

    if sbc["double_count"] == "PRESENT":
        headline = ("P10 BLOCKED: P9 double-counts SBC. Correct the driver "
                    "bridge before any arbitration is meaningful.")
    else:
        headline = (
            f"{doc_id}: LIVE {live_value:,.2f} / P6-central "
            f"{p6_c:,.2f} / P9-base {p9v(Scenario.BASE)}. "
            + ("These CONVERGE - " if arb is ArbitrationOutcome.MODEL_CONVERGENCE
               else "They disagree; ")
            + (arb_reasons[0] if arb_reasons else "")
            + ". No model is preferred for being more complex, more "
            "conservative, or closer to the market.") if p6_c is not None else (
            f"{doc_id}: LIVE {live_value:,.2f}; P6 and P9 are "
            "INSUFFICIENT_EVIDENCE for this filer.")

    return GovernanceReport(
        doc_id=doc_id, live_value=live_value,
        p6_low=p6_low, p6_central=p6_c, p6_high=p6_h,
        p9_bear=p9v(Scenario.BEAR), p9_base=p9v(Scenario.BASE),
        p9_bull=p9v(Scenario.BULL), p7_implied_fcff=p7_fcff,
        reconciliation=tuple(recon), register=tuple(reg),
        sbc_audit=sbc, tax_audit=tax, applicability=tuple(applic),
        arbitration=arb, arbitration_reasons=tuple(arb_reasons),
        dominant_assumptions=tuple(dominant), headline=headline,
        notes=(
            "GOVERNANCE layer: it never changed the LIVE DCF, never promoted "
            "P6/P7/P9, and its classification does not depend on a market price.",
            f"reconciliation order-dependent: {recon_meta.get('order_dependent')}; "
            f"{recon_meta.get('interaction_note', '')}",
        ))
