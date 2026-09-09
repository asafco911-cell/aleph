"""P9 - OPERATING MODEL, FORECAST ECONOMICS & DRIVER-BASED FCFF.

STATUS: EXPERIMENTAL - NOT WIRED INTO THE BASE DCF, does not promote P6/P7,
does not modify DCFInputs / WACC / terminal growth / the live point value.

THE QUESTION. Can Aleph forecast future FCFF from EXPLICIT business drivers -
revenue, operating margin, working-capital intensity, capex intensity, SBC -
rather than implicitly assuming that one historical year's reconstructed
FCFF is the run-rate? The forecast must be driver-based, explicit,
provenance-bound, scenario-separated and auditable; where a driver is not
supported by disclosed evidence it stays INSUFFICIENT_EVIDENCE.

WHAT IT IS NOT. No LLM, no ML, no fitted model, no forecasting from stock
price or reverse DCF, no back-solving, no automatic median/latest/smoothed
growth, no confidence score. A straight-line fade is represented explicitly
as a MODEL_CONVENTION, never hidden inside an array.

THE BRIDGE (Phase 11), deterministic, per forecast year:
    revenue_t          = revenue_{t-1} * (1 + g_t)
    operating_income_t = revenue_t * operating_margin_t
    nopat_t            = operating_income_t * (1 - tax)          tax = 21% (MODEL_CONVENTION)
    + dna_t            = revenue_t * (D&A / revenue)
    + wc_cash_effect_t = SCENARIO-only (see below)
    - capex_t          = revenue_t * (capex / revenue)
    - sbc_t            = revenue_t * (SBC / revenue)             full cash cost, ADR 0002
    = fcff_t

WORKING CAPITAL. P8 established the recurrence of the insurance-reserve /
accrued-liability float is NOT disclosed. So wc_cash_effect is never a point
estimate: bear = 0 (no tailwind), base = historical MEDIAN cash-effect /
revenue, bull = the latest ratio. It enters FCFF additively (positive = a
source of cash, as the CFO reconciliation presents it).

FOUR DISTINCT FCFF OBJECTS, never reused or mutated: historical
reconstructed FCFF (bridge.py), P6 sustainable FCFF, P9 forecast FCFF
(here), P7 market-implied FCFF. This module produces only the third and
never reads a market price.
"""
from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass, field
from enum import Enum

from ..infra.units import resolve_scale

__all__ = [
    "SeriesShape",
    "DriverSource",
    "DriverSupport",
    "ForecastSupport",
    "Scenario",
    "HistoricalDriver",
    "DriverAssumption",
    "ForecastYear",
    "OperatingForecast",
    "historical_drivers",
    "classify_series",
    "build_operating_forecast",
    "build_scenarios",
    "TERMINAL_GROWTH_CONVENTION",
    "STATUTORY_TAX_CONVENTION",
    "STABLE_BAND_FRAC",
    "GROWTH_SPREAD_FLOOR",
    "MARGIN_BOUND",
]

TERMINAL_GROWTH_CONVENTION = 0.025      # held identical to the live model
STATUTORY_TAX_CONVENTION = 0.21         # held identical to the live model
STABLE_BAND_FRAC = 0.15                 # within +-15% of the median -> STABLE
GROWTH_SPREAD_FLOOR = 0.02              # scenario spread is >= 2pp (from dispersion, not arbitrary)
MARGIN_BOUND = 0.50                     # |operating margin| economically representable bound


class SeriesShape(str, Enum):
    STABLE = "STABLE"
    TRENDING = "TRENDING"
    INFLECTING = "INFLECTING"
    CYCLICAL = "CYCLICAL"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class DriverSource(str, Enum):
    HISTORICAL = "HISTORICAL"
    ANALYST_ASSUMPTION = "ANALYST_ASSUMPTION"
    MODEL_CONVENTION = "MODEL_CONVENTION"
    TRANSITION = "TRANSITION"
    TERMINAL = "TERMINAL"


class DriverSupport(str, Enum):
    SUPPORTED = "SUPPORTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class ForecastSupport(str, Enum):
    FULLY_SUPPORTED = "FULLY_SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class Scenario(str, Enum):
    BEAR = "BEAR"
    BASE = "BASE"
    BULL = "BULL"


# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class HistoricalDriver:
    name: str
    periods: tuple[str, ...]
    values: tuple[float, ...]
    unit: str
    shape: SeriesShape
    median: float | None
    latest: float | None
    minimum: float | None
    maximum: float | None
    support: DriverSupport
    transformation: str
    source_facts: tuple[str, ...]
    note: str = ""


@dataclass(frozen=True)
class DriverAssumption:
    year: int
    name: str
    value: float
    source: DriverSource
    scenario: str
    historical_ref: str
    formula: str
    lineage: str


@dataclass(frozen=True)
class ForecastYear:
    year: int
    revenue: float
    revenue_growth: float
    operating_margin: float | None
    operating_income: float | None
    tax_rate: float
    nopat: float | None
    dna: float
    wc_cash_effect: float
    capex: float
    sbc: float
    fcff: float | None
    support: ForecastSupport
    assumptions: tuple[DriverAssumption, ...]
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class OperatingForecast:
    doc_id: str
    scenario: Scenario
    base_period: str
    base_revenue: float
    base_fcff: float | None
    forecast_years: int
    years: tuple[ForecastYear, ...]
    historical: tuple[HistoricalDriver, ...]
    support: ForecastSupport
    unsupported_drivers: tuple[str, ...]     # NO disclosed evidence for a value
    scenario_drivers: tuple[str, ...] = ()   # bracketed by BEAR/BASE/BULL, not a point
    notes: tuple[str, ...] = field(default_factory=tuple)
    # NEVER carries a market price - the forecast does not know the stock price.


# --------------------------------------------------------------------------- #
# fact plumbing
# --------------------------------------------------------------------------- #
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _scaled(f) -> float | None:
    s = resolve_scale(getattr(f, "unit", None))
    return None if s is None else f.value * s


def _series(facts, target_key, predicate) -> dict[str, float]:
    out: dict[str, float] = {}
    for f in facts:
        if not f.source or f.source.target_key != target_key or not f.period:
            continue
        if predicate(_norm(f.name).lower()):
            v = _scaled(f)
            if v is not None and f.period not in out:
                out[f.period] = v
    return out


def _revenue(facts) -> dict[str, float]:
    r = _series(facts, "operations",
                lambda n: n.startswith("total revenue"))
    return r


def _operating_income(facts) -> dict[str, float]:
    return _series(
        facts, "operations",
        lambda n: ("income from operations" in n or "loss from operations" in n
                   or "income (loss) from operations" in n
                   or n == "operating income" or n == "operating loss"))


def _dna(facts) -> dict[str, float]:
    return _series(facts, "cash_flows",
                   lambda n: n == "depreciation and amortization"
                   or n.startswith("depreciation and amortization"))


def _wc_cash_effect(facts) -> dict[str, float]:
    """Sum of the working-capital 'change in <account>' reconciliation lines,
    per period - the SAME quantity P6/P8 use, recomputed here from a lazy P8
    import so the two cannot disagree."""
    from .evidence_depth import map_reconciliation_caption, Category
    out: dict[str, float] = {}
    for f in facts:
        if not f.source or f.source.target_key != "cash_flows" or not f.period:
            continue
        m = map_reconciliation_caption(_norm(f.name))
        if m.category is Category.WORKING_CAPITAL:
            v = _scaled(f)
            if v is not None:
                out[f.period] = out.get(f.period, 0.0) + v
    return out


def _reconciliation_failed_periods(run) -> set[str]:
    try:
        from .evidence_depth import assess_evidence_depth, ReconciliationStatus
        rep = assess_evidence_depth(run)
        return {pe.period for pe in rep.period_evidence
                if pe.reconciliation_status is ReconciliationStatus.RECONCILIATION_FAILED}
    except Exception:  # noqa: BLE001
        return set()


# --------------------------------------------------------------------------- #
# Phase 4 - series shape classification (describes the OBSERVED series only)
# --------------------------------------------------------------------------- #
def classify_series(values: list[float]) -> SeriesShape:
    vals = [v for v in values if v is not None and math.isfinite(v)]
    if len(vals) < 2:
        return SeriesShape.INSUFFICIENT_EVIDENCE
    if any(v < 0 for v in vals) and any(v > 0 for v in vals):
        return SeriesShape.INFLECTING
    med = statistics.median(vals)
    if med != 0 and (max(vals) - min(vals)) / abs(med) <= STABLE_BAND_FRAC:
        return SeriesShape.STABLE
    rising = all(b > a for a, b in zip(vals, vals[1:]))
    falling = all(b < a for a, b in zip(vals, vals[1:]))
    if rising or falling:
        return SeriesShape.TRENDING
    return SeriesShape.CYCLICAL


def _driver(name, per_val: dict[str, float], unit, transformation, source_facts,
            note="") -> HistoricalDriver:
    periods = tuple(sorted(per_val))
    values = tuple(per_val[p] for p in periods)
    shape = classify_series(list(values))
    med = statistics.median(values) if values else None
    return HistoricalDriver(
        name=name, periods=periods, values=values, unit=unit, shape=shape,
        median=med, latest=values[-1] if values else None,
        minimum=min(values) if values else None,
        maximum=max(values) if values else None,
        support=(DriverSupport.INSUFFICIENT_EVIDENCE
                 if shape is SeriesShape.INSUFFICIENT_EVIDENCE
                 else DriverSupport.SUPPORTED),
        transformation=transformation, source_facts=tuple(source_facts), note=note)


# --------------------------------------------------------------------------- #
# Phase 3 + 4 - historical driver series
# --------------------------------------------------------------------------- #
def historical_drivers(run) -> list[HistoricalDriver]:
    facts = list(getattr(run, "facts", []) or [])
    rev = _revenue(facts)
    oi = _operating_income(facts)
    dna = _dna(facts)
    wc = _wc_cash_effect(facts)
    bound = getattr(getattr(run, "bridged", None), "base_cash_flow_bound", None) or {}
    fcff = dict(bound.get("fcff_by_period") or {}) \
        if isinstance(bound, dict) and bound.get("available") else {}

    ranges = getattr(run, "ranges", {}) or {}
    def range_series(name):
        r = ranges.get(name)
        if r is None:
            return {}
        s = resolve_scale(r.unit)
        return {o.period: (o.value * s if s is not None else o.value)
                for o in r.observations}
    capex = {p: abs(v) for p, v in range_series("capex").items()}
    sbc = range_series("stock_based_compensation")

    ds: list[HistoricalDriver] = []
    ds.append(_driver("revenue", rev, "USD millions", "total revenue, per period",
                      ("Total revenue",)))
    growth = {}
    yrs = sorted(rev)
    for a, b in zip(yrs, yrs[1:]):
        if rev[a]:
            growth[b] = rev[b] / rev[a] - 1.0
    ds.append(_driver("revenue_growth", growth, "decimal",
                      "year-over-year: revenue_t / revenue_{t-1} - 1",
                      ("Total revenue",)))
    margin = {p: oi[p] / rev[p] for p in oi if p in rev and rev[p]}
    ds.append(_driver("operating_margin", margin, "decimal",
                      "income (loss) from operations / total revenue",
                      ("Income (loss) from operations", "Total revenue")))
    ds.append(_driver("wc_cash_effect_over_revenue",
                      {p: wc[p] / rev[p] for p in wc if p in rev and rev[p]},
                      "decimal", "sum(change-in-<account> lines) / total revenue",
                      ("Change in <working-capital account> lines",),
                      note="P8: recurrence of the insurance-reserve / accrued "
                      "float is NOT disclosed - this is a scenario dimension, "
                      "never a point estimate"))
    ds.append(_driver("capex_over_revenue",
                      {p: capex[p] / rev[p] for p in capex if p in rev and rev[p]},
                      "decimal", "abs(purchases of property and equipment) / revenue",
                      ("Purchases of property and equipment", "Total revenue")))
    ds.append(_driver("sbc_over_revenue",
                      {p: sbc[p] / rev[p] for p in sbc if p in rev and rev[p]},
                      "decimal", "stock-based compensation / total revenue",
                      ("Stock-based compensation", "Total revenue")))
    ds.append(_driver("dna_over_revenue",
                      {p: dna[p] / rev[p] for p in dna if p in rev and rev[p]},
                      "decimal", "depreciation and amortization / total revenue",
                      ("Depreciation and amortization", "Total revenue")))
    ds.append(_driver("reconstructed_fcff", fcff, "USD millions",
                      "bridge.py: CFO + interest*(1-tax) - capex - SBC (historical)",
                      ("(pipeline reconstruction)",),
                      note="the LIVE anchor; shown for comparison, NOT a P9 driver"))
    ds.append(_driver("fcff_margin",
                      {p: fcff[p] / rev[p] for p in fcff if p in rev and rev[p]},
                      "decimal", "reconstructed FCFF / total revenue",
                      ("(pipeline reconstruction)", "Total revenue")))
    return ds


# --------------------------------------------------------------------------- #
# Phase 5 + 6 + 7 + 8 + 9 - scenario-aware forecast construction
# --------------------------------------------------------------------------- #
def _fade(start: float, end: float, n: int) -> list[float]:
    if n <= 1:
        return [end]
    step = (start - end) / (n - 1)
    return [start - step * i for i in range(n)]


def _spread(d: HistoricalDriver) -> float:
    if d.maximum is None or d.minimum is None:
        return GROWTH_SPREAD_FLOOR
    return max((d.maximum - d.minimum) / 2.0, GROWTH_SPREAD_FLOOR)


def build_operating_forecast(run, scenario: Scenario,
                             forecast_years: int = 10) -> OperatingForecast:
    doc_id = getattr(run, "doc_id", "")
    hist = historical_drivers(run)
    by = {d.name: d for d in hist}
    rev_d = by["revenue"]
    g_d = by["revenue_growth"]
    m_d = by["operating_margin"]
    wc_d = by["wc_cash_effect_over_revenue"]
    cx_d = by["capex_over_revenue"]
    sbc_d = by["sbc_over_revenue"]
    dna_d = by["dna_over_revenue"]

    base_period = rev_d.periods[-1] if rev_d.periods else ""
    base_revenue = rev_d.latest or 0.0
    unsupported: list[str] = []
    notes: list[str] = []
    failed = _reconciliation_failed_periods(run)
    if failed:
        notes.append(f"P8 reports RECONCILIATION_FAILED for {sorted(failed)}; "
                     "the working-capital driver is unreliable for this filer.")

    # ---- revenue growth path (Phase 6) --------------------------------------
    if g_d.support is DriverSupport.INSUFFICIENT_EVIDENCE or g_d.median is None:
        return _insufficient(doc_id, scenario, base_period, base_revenue,
                             forecast_years, hist,
                             ["revenue_growth"] + unsupported,
                             notes + ["fewer than two year-over-year revenue "
                                      "growth observations; no forecast"])
    # If the LIVE model already carries an analyst override for revenue
    # growth, the driver model RESPECTS it (it is a recorded decision) and
    # says so; otherwise year-1 is the historical MEDIAN, declared as an
    # explicit ANALYST_ASSUMPTION - never a silent default either way.
    rg_range = (getattr(run, "ranges", {}) or {}).get("revenue_growth")
    g1_center = g_d.median
    g1_source = "historical median of the observed year-over-year growth"
    if rg_range is not None and getattr(rg_range, "status", "") == "overridden" \
            and rg_range.base is not None:
        g1_center = (rg_range.base / 100.0 if abs(rg_range.base) > 1 else rg_range.base)
        g1_source = (f"analyst override from data/overrides.json "
                     f"({g1_center:+.1%}); the driver model does not overrule it")
        notes.append(f"revenue growth year-1 uses the live analyst override "
                     f"({g1_center:+.1%}), not the historical median "
                     f"({g_d.median:+.1%}).")
    gsp = _spread(g_d)
    g1 = {Scenario.BASE: g1_center,
          Scenario.BEAR: g1_center - gsp,
          Scenario.BULL: g1_center + gsp}[scenario]
    growth_path = _fade(g1, TERMINAL_GROWTH_CONVENTION, forecast_years)

    # ---- operating margin path (Phase 7) ----------------------------------
    margin_support = ForecastSupport.FULLY_SUPPORTED
    if m_d.support is DriverSupport.INSUFFICIENT_EVIDENCE:
        unsupported.append("operating_margin")
        margin_support = ForecastSupport.INSUFFICIENT_EVIDENCE
        m_val, m_src, m_note = (m_d.latest or 0.0), DriverSource.ANALYST_ASSUMPTION, \
            "fewer than two operating-margin observations"
    elif m_d.shape is SeriesShape.INFLECTING:
        unsupported.append("operating_margin")
        margin_support = ForecastSupport.INSUFFICIENT_EVIDENCE
        m_val = {Scenario.BASE: m_d.latest, Scenario.BEAR: m_d.minimum,
                 Scenario.BULL: m_d.maximum}[scenario]
        m_src, m_note = DriverSource.ANALYST_ASSUMPTION, (
            "operating margin INFLECTS across the disclosed years (crosses "
            "zero); no point forecast is evidence-supported - scenario bracket "
            "only")
    elif m_d.shape is SeriesShape.STABLE:
        m_val = {Scenario.BASE: m_d.median, Scenario.BEAR: m_d.minimum,
                 Scenario.BULL: m_d.maximum}[scenario]
        m_src, m_note = DriverSource.HISTORICAL, "operating margin STABLE; held at " + \
            {Scenario.BASE: "median", Scenario.BEAR: "min", Scenario.BULL: "max"}[scenario]
    else:  # TRENDING / CYCLICAL
        slope = ((m_d.values[-1] - m_d.values[0]) / (len(m_d.values) - 1)
                 if len(m_d.values) > 1 else 0.0)
        m_val = {Scenario.BASE: m_d.latest,
                 Scenario.BEAR: m_d.minimum,
                 Scenario.BULL: (m_d.latest or 0.0) + 2 * slope}[scenario]
        m_src = DriverSource.ANALYST_ASSUMPTION
        m_note = (f"operating margin {m_d.shape.value}; BASE holds the LATEST "
                  f"margin flat (an explicit assumption, not an extrapolation); "
                  f"BULL adds 2x the observed slope ({slope:+.1%}/yr) then flat; "
                  f"BEAR uses the minimum observed")
    m_val = max(-MARGIN_BOUND, min(MARGIN_BOUND, m_val or 0.0))
    margin_path = [m_val] * forecast_years        # held flat over the horizon

    # ---- WC cash effect path (Phase 8) - SCENARIO ONLY -------------------
    wc_ratio_med = wc_d.median if wc_d.median is not None else 0.0
    wc_ratio_latest = wc_d.latest if wc_d.latest is not None else 0.0
    wc_ratio = {Scenario.BEAR: 0.0,
                Scenario.BASE: wc_ratio_med,
                Scenario.BULL: wc_ratio_latest}[scenario]
    # working capital is NEVER a point (P8: recurrence not disclosed). It is a
    # SCENARIO dimension, not an "unsupported" driver - BEAR 0 / BASE
    # historical-median ratio / BULL latest ratio bracket it.
    scenario_drivers = ["wc_cash_effect_over_revenue"]

    # ---- capex / SBC / D&A ratios (Phase 9 / 10) ------------------------
    def ratio(d: HistoricalDriver, sc: Scenario, favour_low: bool) -> tuple[float, DriverSource]:
        if d.support is DriverSupport.INSUFFICIENT_EVIDENCE or d.median is None:
            return 0.0, DriverSource.ANALYST_ASSUMPTION
        lo, hi = d.minimum, d.maximum
        v = {Scenario.BASE: d.median,
             Scenario.BEAR: (lo if favour_low else hi),
             Scenario.BULL: (hi if favour_low else lo)}[sc]
        return v, DriverSource.HISTORICAL
    capex_ratio, capex_src = ratio(cx_d, scenario, favour_low=False)   # bear = higher capex
    sbc_ratio, sbc_src = ratio(sbc_d, scenario, favour_low=False)      # bear = higher SBC
    dna_ratio = dna_d.median if dna_d.median is not None else 0.0
    if cx_d.support is DriverSupport.INSUFFICIENT_EVIDENCE:
        unsupported.append("capex_over_revenue")
    if sbc_d.support is DriverSupport.INSUFFICIENT_EVIDENCE:
        unsupported.append("sbc_over_revenue")

    # ---- build the year path --------------------------------------------
    # P10 SBC CORRECTION. Stock-based compensation is a GAAP operating expense
    # and is ALREADY inside income-from-operations, hence inside NOPAT. The
    # earlier bridge additionally subtracted a separate `- sbc_t` term, which
    # double-counted SBC: the total FCFF drag was 1.21x SBC (0.79x through
    # NOPAT + 1.0x explicit). It is subtracted ONCE now, through the P&L.
    # This tax-shields SBC at 21% (SBC is a deductible compensation expense),
    # a small labelled difference from the LIVE bridge's full pre-tax
    # subtraction - NOT a second charge. sbc_t is still reported for
    # transparency.
    def bridge(rev_prev, rev_t, g_t, margin_t, src_margin, yr):
        oi_t = rev_t * margin_t
        nopat_t = oi_t * (1 - STATUTORY_TAX_CONVENTION)
        dna_t = rev_t * dna_ratio
        wc_t = rev_t * wc_ratio
        capex_t = rev_t * capex_ratio
        sbc_t = rev_t * sbc_ratio            # reported only; already in oi_t
        fcff_t = nopat_t + dna_t + wc_t - capex_t
        a = (
            DriverAssumption(yr, "revenue_growth", g_t,
                             DriverSource.MODEL_CONVENTION if yr > 1 else DriverSource.ANALYST_ASSUMPTION,
                             scenario.value,
                             f"{g_d.shape.value}; median {g_d.median:+.1%}, "
                             f"observed {', '.join(f'{v:+.1%}' for v in g_d.values)}",
                             "linear fade from year-1 to terminal 2.5%",
                             f"year-1 center = {g1_source}; scenario shift = "
                             f"+/- half the observed dispersion "
                             f"(spread {_spread(g_d):.1%}); years 2..n fade linearly"),
            DriverAssumption(yr, "operating_margin", margin_t, src_margin,
                             scenario.value,
                             f"{m_d.shape.value}; observed "
                             f"{', '.join(f'{v:+.1%}' for v in m_d.values)}",
                             "operating_income_t = revenue_t * operating_margin_t",
                             m_note),
            DriverAssumption(yr, "tax_rate", STATUTORY_TAX_CONVENTION,
                             DriverSource.MODEL_CONVENTION, scenario.value,
                             "n/a - a held-identical convention",
                             "nopat_t = operating_income_t * (1 - 0.21)",
                             "21% statutory; the filers' actual effective CASH "
                             "tax has been near zero (DTA releases) - this "
                             "convention is CONSERVATIVE for the forecast"),
            DriverAssumption(yr, "dna_over_revenue", dna_ratio, DriverSource.HISTORICAL,
                             scenario.value,
                             f"median of {', '.join(f'{v:.1%}' for v in dna_d.values)}"
                             if dna_d.values else "n/a",
                             "dna_t = revenue_t * (D&A / revenue)", "held at the historical median"),
            DriverAssumption(yr, "wc_cash_effect_over_revenue", wc_ratio,
                             DriverSource.ANALYST_ASSUMPTION, scenario.value,
                             f"observed {', '.join(f'{v:+.1%}' for v in wc_d.values)}"
                             if wc_d.values else "n/a",
                             "wc_cash_effect_t = revenue_t * wc_ratio (enters FCFF +)",
                             "SCENARIO ONLY - BEAR 0 / BASE historical-median / "
                             "BULL latest ratio; recurrence NOT disclosed (P8)"),
            DriverAssumption(yr, "capex_over_revenue", capex_ratio, capex_src,
                             scenario.value,
                             f"observed {', '.join(f'{v:.1%}' for v in cx_d.values)}"
                             if cx_d.values else "n/a",
                             "capex_t = revenue_t * (capex / revenue)",
                             "no maintenance/growth split is disclosed (P8) - "
                             "TOTAL capex only"),
            DriverAssumption(yr, "sbc_over_revenue", sbc_ratio, sbc_src,
                             scenario.value,
                             f"observed {', '.join(f'{v:.1%}' for v in sbc_d.values)}"
                             if sbc_d.values else "n/a",
                             "sbc_t = revenue_t * (SBC / revenue) - REPORTED ONLY; "
                             "SBC is already inside operating_income and is NOT "
                             "subtracted again",
                             "P10 correction: the earlier bridge double-counted "
                             "SBC (1.21x drag). SBC is a GAAP opex, charged once "
                             "through the P&L; shares held flat (ADR 0002)"),
        )
        return oi_t, nopat_t, dna_t, wc_t, capex_t, sbc_t, fcff_t, a

    years: list[ForecastYear] = []
    rev_prev = base_revenue
    # year 0 (base): the bridge on base_revenue with year-1 drivers, no growth
    oi0, nopat0, dna0, wc0, cx0, sbc0, fcff0, _ = bridge(
        base_revenue, base_revenue, 0.0, margin_path[0], m_src, 0)
    for k in range(forecast_years):
        g_t = growth_path[k]
        rev_t = rev_prev * (1 + g_t)
        margin_t = margin_path[k]
        oi_t, nopat_t, dna_t, wc_t, cx_t, sbc_t, fcff_t, a = bridge(
            rev_prev, rev_t, g_t, margin_t, m_src, k + 1)
        yr_support = (ForecastSupport.INSUFFICIENT_EVIDENCE
                      if margin_support is ForecastSupport.INSUFFICIENT_EVIDENCE
                      else ForecastSupport.PARTIALLY_SUPPORTED)
        years.append(ForecastYear(
            year=k + 1, revenue=rev_t, revenue_growth=g_t,
            operating_margin=margin_t, operating_income=oi_t,
            tax_rate=STATUTORY_TAX_CONVENTION, nopat=nopat_t, dna=dna_t,
            wc_cash_effect=wc_t, capex=cx_t, sbc=sbc_t, fcff=fcff_t,
            support=yr_support, assumptions=a,
            notes=("working capital is a SCENARIO input, not a point estimate",)))
        rev_prev = rev_t

    # ---- overall support -----------------------------------------------
    if margin_support is ForecastSupport.INSUFFICIENT_EVIDENCE and failed:
        support = ForecastSupport.INSUFFICIENT_EVIDENCE
        notes.append("operating margin is not evidence-supported AND the CFO "
                     "reconciliation fails - no driver-based FCFF is produced.")
        return OperatingForecast(
            doc_id=doc_id, scenario=scenario, base_period=base_period,
            base_revenue=base_revenue, base_fcff=None,
            forecast_years=forecast_years, years=(), historical=tuple(hist),
            support=support, unsupported_drivers=tuple(sorted(set(unsupported))),
            scenario_drivers=tuple(scenario_drivers), notes=tuple(notes))

    # FULLY_SUPPORTED requires the operating margin to be held at the
    # historical MEDIAN of a STABLE series (source HISTORICAL). A TRENDING /
    # CYCLICAL / INFLECTING margin held at the latest value is an
    # ANALYST_ASSUMPTION and caps support at PARTIALLY_SUPPORTED - the
    # forecast then rests on a choice, and the report must say so. Working
    # capital being scenario-bracketed does NOT itself reduce support.
    support = (ForecastSupport.FULLY_SUPPORTED
               if (not unsupported
                   and margin_support is not ForecastSupport.INSUFFICIENT_EVIDENCE
                   and m_src is DriverSource.HISTORICAL)
               else ForecastSupport.PARTIALLY_SUPPORTED)
    notes.append("wc_cash_effect is scenario-only (BEAR 0 / BASE median / BULL "
                 "latest) - the model NEVER assumes the insurance-reserve build "
                 "repeats.")
    notes.append("driver FCFF applies 21% tax to operating income; the "
                 "historical reconstructed FCFF instead inherits the near-zero "
                 "effective CASH tax - this is the main source of divergence.")
    return OperatingForecast(
        doc_id=doc_id, scenario=scenario, base_period=base_period,
        base_revenue=base_revenue, base_fcff=fcff0,
        forecast_years=forecast_years, years=tuple(years),
        historical=tuple(hist), support=support,
        unsupported_drivers=tuple(sorted(set(unsupported))),
        scenario_drivers=tuple(scenario_drivers), notes=tuple(notes))


def _insufficient(doc_id, scenario, base_period, base_revenue, n, hist,
                  unsupported, notes) -> OperatingForecast:
    return OperatingForecast(
        doc_id=doc_id, scenario=scenario, base_period=base_period,
        base_revenue=base_revenue, base_fcff=None, forecast_years=n,
        years=(), historical=tuple(hist),
        support=ForecastSupport.INSUFFICIENT_EVIDENCE,
        unsupported_drivers=tuple(sorted(set(unsupported))), notes=tuple(notes))


def build_scenarios(run, forecast_years: int = 10) -> dict[str, OperatingForecast]:
    return {sc.value: build_operating_forecast(run, sc, forecast_years)
            for sc in (Scenario.BEAR, Scenario.BASE, Scenario.BULL)}
