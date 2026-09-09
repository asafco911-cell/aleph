"""P4 - accounting-quality diagnostics. Evidence-backed, deterministic, and
STRICTLY diagnostic: nothing in this module changes an FCFF, a WACC, a growth
rate, a share count, or any valuation output. It reads verified facts and
reports what they imply about how well reported earnings and cash flow
represent sustainable economic earning power.

THREE QUESTIONS, KEPT APART (never collapsed into one score):

  1. WHAT WAS REPORTED?              -> the FACT line of each diagnostic
  2. HOW REPRESENTATIVE IS IT?       -> the DIAGNOSTIC and INTERPRETATION lines
  3. HOW COULD THAT AFFECT VALUE?    -> the VALUATION RELEVANCE line and the
                                        qualitative potential_valuation_impact

There is NO composite "accounting quality score". A company can have clean
earnings and weak cash conversion, or heavy SBC and disciplined working
capital, at the same time. Each dimension is reported on its own terms. The
only synthesis is `converging_risks`, which LISTS the diagnostics that point
the same way - it is a sentence, not a number.

NO LLM. Every number here is deterministic Python over gate-verified Fact
objects. The LLM extracted and quoted those facts; it does not compute a
ratio, pick a threshold, or decide an impact. Interpretation strings are
templates with measured numbers filled in, not generated prose.

NO FRAUD LANGUAGE. The strongest conclusion this module will state is
"accounting-quality risk" / "cash-flow representation risk". It never
concludes fraud or manipulation - that would require the filing itself to
report an accounting issue, which is outside this module's inputs.

THRESHOLDS are conventions, documented as such at their definition: the level
at which a reader should LOOK, never a level at which something becomes true.
Each gates a FLAG, never a number. Where the data does not support a
diagnostic, the state is INSUFFICIENT_DATA or NOT_APPLICABLE - never silently
ASSESSED_NO_ISSUE (that conflation is the failure mode ISSUES.md keeps
returning to).

WHAT P4 CANNOT SEE, measured on the corpus:
  - Balance-sheet receivable/inventory/deferred-revenue LEVELS are not
    extracted (targets.py pulls only cash, investments, debt, and the
    totals from the balance sheet). Revenue-quality therefore works off the
    cash-flow "change in accounts receivable", which is a PROXY for the
    collection lag, not the balance itself - stated in every such diagnostic.
  - A one-time CASH cost never appears as its own reconciliation caption
    (cfo_normalization.py documents this at length). P4 identifies non-cash
    earnings adjustments from the reconciliation; it identifies a cash
    one-off ONLY from explicitly supplied analyst evidence, and otherwise
    reports NO_CASH_ONE_OFF_IDENTIFIED - never NO_CASH_ONE_OFF_EXISTS.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from enum import Enum
from statistics import median

__all__ = [
    "DiagnosticState",
    "ValuationImpact",
    "Horizon",
    "Confidence",
    "WCCoverage",
    "Direction",
    "Evidence",
    "Diagnostic",
    "WorkingCapitalCoverage",
    "ConvergingRisks",
    "AccountingQualityReport",
    "CashOneOff",
    "assess_accounting_quality",
    # thresholds, exported so tests and docs cite one definition
    "SBC_TO_REVENUE_MATERIAL",
    "SBC_TO_CFO_MATERIAL",
    "CAPEX_TO_CFO_INTENSIVE",
    "CAPEX_TO_REVENUE_INTENSIVE",
    "MATERIAL_DEVIATION",
    "ACCRUAL_TO_NI_HIGH",
    "RECEIVABLES_DRAG_MULTIPLE",
    "WORKING_CAPITAL_TO_CFO_HIGH",
    "WC_COVERAGE_SUFFICIENT",
    "CONVERGENCE_MIN_FLAGS",
    "CONVERGENCE_MIN_FAMILIES",
]


# --------------------------------------------------------------------------- #
# States and classifications
# --------------------------------------------------------------------------- #
class DiagnosticState(str, Enum):
    """Every diagnostic ends in exactly one of these. INSUFFICIENT_DATA is
    never read as ASSESSED_NO_ISSUE - absence of evidence is not evidence of
    a clean account."""

    NOT_ASSESSED = "NOT_ASSESSED"
    ASSESSED_NO_ISSUE = "ASSESSED_NO_ISSUE"
    FLAGGED = "FLAGGED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ValuationImpact(str, Enum):
    """Qualitative, rule-based, and NOT a numerical adjustment. The rules are
    stated per diagnostic. UNKNOWN is a real answer: it means the direction
    of the effect on value cannot be established from the filing."""

    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class Horizon(str, Enum):
    """Over what span the diagnostic holds. A single-year deviation is
    labelled as such and NOT called a structural problem.

    SINGLE_YEAR is distinct from LATEST_PERIOD: LATEST_PERIOD means "the most
    recent period, read against its own history"; SINGLE_YEAR means "one
    period is ALL there is, so persistence cannot be assessed at all". A
    SINGLE_YEAR diagnostic always carries confidence=LIMITED.
    """

    LATEST_PERIOD = "LATEST_PERIOD"
    HISTORICAL_PATTERN = "HISTORICAL_PATTERN"
    TREND = "TREND"
    SINGLE_YEAR_ANOMALY = "SINGLE_YEAR_ANOMALY"
    SINGLE_YEAR = "SINGLE_YEAR"
    NOT_ENOUGH_HISTORY = "NOT_ENOUGH_HISTORY"


class Confidence(str, Enum):
    """How much weight the diagnostic's own conclusion can bear.

    NORMAL   assessed against two or more periods of history.
    LIMITED  assessed, but from one period (no persistence check possible) or
             from an attribution the engine could not fully classify. The
             conclusion holds for the DATA OBSERVED and nothing wider - the
             interpretation string says exactly that and must not imply
             "historically clean" or "structurally normal".
    """

    NORMAL = "NORMAL"
    LIMITED = "LIMITED"


class WCCoverage(str, Enum):
    """How much of a period's working-capital movement the engine could place
    in a named bucket. An unknown operating component is COUNTED (it never
    disappears from the net total) but leaves coverage short of FULL."""

    FULL_COVERAGE = "FULL_COVERAGE"
    PARTIAL_COVERAGE = "PARTIAL_COVERAGE"
    NO_COVERAGE = "NO_COVERAGE"


class Direction(str, Enum):
    """Which way a flag points, for convergence synthesis only."""

    OVERSTATES_ECONOMIC_CASH = "OVERSTATES_ECONOMIC_CASH"
    UNDERSTATES_ECONOMIC_CASH = "UNDERSTATES_ECONOMIC_CASH"
    NEUTRAL = "NEUTRAL"


# --------------------------------------------------------------------------- #
# Thresholds - each with rationale, economic interpretation, and limitation.
# These gate a FLAG. They never change a value and never feed the DCF.
# --------------------------------------------------------------------------- #

# SBC as a share of revenue. rationale: at ~8% of revenue, SBC is a larger
# line than most filers' R&D or G&A, and treating it as costless materially
# changes per-share economics. interpretation: real employee compensation
# funded with equity rather than cash. limitation: revenue-relative, so a
# thin-margin reseller and a software firm are judged on one line although
# the same ratio means different things for each.
SBC_TO_REVENUE_MATERIAL = 0.08

# SBC as a share of CFO. rationale: CFO adds SBC back in full, so at ~15% of
# CFO the reported operating-cash figure is materially above what it would be
# if SBC were paid in wages. limitation: a working-capital-heavy year
# depresses CFO and inflates this ratio for reasons unrelated to SBC.
SBC_TO_CFO_MATERIAL = 0.15

# Capex as a share of CFO. rationale: above ~30% of operating cash flow
# reinvested in PP&E, free-cash generation is geared to the capex cycle and
# maintenance-vs-growth capex becomes the dominant valuation question.
# limitation: one growth year (a new facility) trips this without the
# business being structurally capital-intensive - hence the trend check
# alongside it.
CAPEX_TO_CFO_INTENSIVE = 0.30

# Capex as a share of revenue. rationale: ~10% of revenue sustained in PP&E
# is the rough line between an asset-light and an asset-heavy operating
# model. limitation: says nothing about returns on that capital.
CAPEX_TO_REVENUE_INTENSIVE = 0.10

# Latest value vs prior-period median: the gap past which a year is worth
# naming. Reused verbatim from historical_fcff.py / cfo_normalization.py so
# the three modules cannot drift apart on what "materially different" means.
MATERIAL_DEVIATION = 0.25

# Working-capital attribution: the share of the net movement that must sit in
# NAMED buckets before the composition claim (e.g. "dominated by insurance
# reserves") is safe to make. rationale: below this, enough of the movement is
# in components the engine could not classify that naming a driver would be a
# guess. limitation: a convention - the net TOTAL is always complete
# regardless, because unknown components are summed in; only the ATTRIBUTION
# is gated. Below the line the working-capital diagnostic returns
# INSUFFICIENT_DATA rather than a partial explanation dressed as a full one.
WC_COVERAGE_SUFFICIENT = 0.85

# |NI - CFO| as a share of |NI|. rationale: above a quarter, accounting
# earnings and cash earnings are telling materially different stories for
# the period. limitation: undefined when NI is near zero; the level gap is
# reported instead and the state stays INSUFFICIENT_DATA for the ratio.
ACCRUAL_TO_NI_HIGH = 0.25

# The cash-flow receivables drag growing this many times as fast as revenue.
# rationale: collections lagging billings by enough to notice. limitation: a
# PROXY - the cash-flow "change in accounts receivable" is not the
# balance-sheet receivable, and one large customer or a period-end timing
# effect moves it.
RECEIVABLES_DRAG_MULTIPLE = 1.5

# Net working-capital contribution as a share of CFO. rationale: above ~20%,
# the period's cash figure is materially carried (or depressed) by balances
# that swing rather than by a run rate. limitation: some businesses run a
# structural working-capital engine (insurance float, subscriptions) where
# a persistent contribution is the model, not an anomaly - the horizon
# label distinguishes the two.
WORKING_CAPITAL_TO_CFO_HIGH = 0.20

# How many MEDIUM/HIGH flags pointing the same way before the report says
# they converge. A count, not a score: three independent adverse signals in
# one direction is worth stating as a set.
CONVERGENCE_MIN_FLAGS = 3

_FORBIDDEN = ("fraud", "manipulat", "cook", "fictitious", "sham")

# Phrases that overclaim on the strength of thin data. An ASSESSED_NO_ISSUE
# from one period, or from a partial working-capital attribution, must not
# reach for any of these - checked by test_no_overclaiming_language and by
# AccountingQualityReport.has_overclaiming_language().
_OVERCLAIM = (
    "clean account", "historically clean", "structurally normal",
    "structurally sound", "healthy account", "no accounting risk",
    "no accounting-quality concern", "no accounting quality concern",
    "revenue is legitimate", "revenue is real", "revenue is genuine",
)


# --------------------------------------------------------------------------- #
# Structures
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Evidence:
    """One observation a diagnostic rests on, traceable to source.

    ``quote`` and ``source_ref`` come straight off the verified Fact. A
    computed number (a ratio, a growth rate) carries ``computed_from`` naming
    the facts it was built from, so every figure in a diagnostic can be
    walked back to quoted filing text.
    """

    label: str
    value: float | None
    unit: str = ""
    period: str | None = None
    quote: str = ""
    source_ref: str = ""
    computed_from: tuple[str, ...] = ()


@dataclass(frozen=True)
class Diagnostic:
    """One accounting-quality finding, with fact / diagnostic / interpretation
    / valuation-relevance kept as separate fields so they cannot blur."""

    key: str
    dimension: str
    state: DiagnosticState
    horizon: Horizon | None
    fact: str
    diagnostic: str
    interpretation: str
    valuation_relevance: str
    potential_valuation_impact: ValuationImpact
    direction: Direction = Direction.NEUTRAL
    evidence: tuple[Evidence, ...] = ()
    formula: str = ""
    threshold: str = ""
    # P4.5 additions - epistemic labelling, not new findings.
    confidence: Confidence = Confidence.NORMAL
    limitation: str = ""
    coverage: "WorkingCapitalCoverage | None" = None

    @property
    def flagged(self) -> bool:
        return self.state is DiagnosticState.FLAGGED

    def text_blob(self) -> str:
        parts = [self.fact, self.diagnostic, self.interpretation,
                 self.valuation_relevance, self.limitation]
        return " ".join(p for p in parts if p).lower()


@dataclass(frozen=True)
class WorkingCapitalCoverage:
    """What share of a period's net working-capital movement the engine placed
    in a named bucket. The net total is complete either way; this reports
    whether the COMPOSITION claim is safe."""

    classified: float
    unclassified: float
    coverage_ratio: float | None
    status: WCCoverage
    unknown_components: tuple[str, ...] = ()
    unmarked_candidates: tuple[str, ...] = ()
    unit: str = "USD millions"

    def render(self) -> str:
        return (f"classified={self.classified:,.0f} "
                f"unclassified={self.unclassified:,.0f} "
                f"coverage={'n/a' if self.coverage_ratio is None else f'{self.coverage_ratio:.0%}'} "
                f"status={self.status.value}"
                + (f"; unknown: {', '.join(self.unknown_components)}"
                   if self.unknown_components else "")
                + (f"; unmarked possible operating lines: "
                   f"{', '.join(self.unmarked_candidates)}"
                   if self.unmarked_candidates else ""))


@dataclass(frozen=True)
class ConvergingRisks:
    present: bool
    direction: Direction
    diagnostics: tuple[str, ...]
    summary: str
    # P4.6 F1/F2: flags grouped by the accounting RELATIONSHIP they measure.
    # Convergence counts DIMENSIONS, not raw flags - three flags that all
    # measure the NI<->CFO reconciliation are one signal, not three.
    families: dict[str, tuple[str, ...]] = field(default_factory=dict)
    limited_flag_count: int = 0


@dataclass(frozen=True)
class CashOneOff:
    """Explicitly supplied evidence of a one-time CASH item. Never inferred -
    the cash flow statement cannot name these (see cfo_normalization.py). An
    analyst who knows a settlement was paid records it here with a source."""

    amount: float
    unit: str
    fiscal_year: str
    description: str
    source: str = ""


@dataclass(frozen=True)
class AccountingQualityReport:
    doc_id: str
    assessed: bool
    diagnostics: tuple[Diagnostic, ...]
    converging_risks: ConvergingRisks | None = None
    periods: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    # P4.7: set only when the diagnostic layer failed to run. The valuation
    # is preserved; this records WHY accounting quality is unavailable so the
    # absence is never read as "assessed, no issue".
    not_assessed_reason: str = ""

    @staticmethod
    def not_assessed(doc_id: str, reason: str) -> "AccountingQualityReport":
        return AccountingQualityReport(
            doc_id=doc_id, assessed=False, diagnostics=(),
            converging_risks=None, periods=(),
            notes=(f"ACCOUNTING QUALITY: NOT ASSESSED - {reason}. The "
                   "valuation above is unaffected.",),
            not_assessed_reason=reason)

    def by_dimension(self, dimension: str) -> tuple[Diagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.dimension == dimension)

    def get(self, key: str) -> Diagnostic | None:
        return next((d for d in self.diagnostics if d.key == key), None)

    @property
    def flagged(self) -> tuple[Diagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.flagged)

    def _blob(self) -> str:
        blob = " ".join(d.text_blob() for d in self.diagnostics)
        if self.converging_risks:
            blob += " " + self.converging_risks.summary.lower()
        return blob

    def has_forbidden_language(self) -> bool:
        """True if any rendered text contains fraud/manipulation wording -
        used by a test as a standing guard, never expected to be True."""
        return any(bad in self._blob() for bad in _FORBIDDEN)

    def has_overclaiming_language(self) -> bool:
        """True if any text implies historical / structural cleanliness that
        the data does not support ('historically clean', 'structurally
        normal', 'revenue is legitimate'). Standing guard, expected False."""
        return any(bad in self._blob() for bad in _OVERCLAIM)


# --------------------------------------------------------------------------- #
# Fact plumbing - verified Fact objects in, period-keyed series out
# --------------------------------------------------------------------------- #
def _source_ref(fact) -> str:
    src = getattr(fact, "source", None)
    if not src:
        return ""
    pages = ",".join(str(p) for p in getattr(src, "pages", []) or [])
    return f"{src.doc_id} {src.kind}:{src.ref}" + (f" p.{pages}" if pages else "")


_ANNUAL_PERIOD = re.compile(r"^FY\d{4}$", re.I)


def _series(facts, *includes, exclude=(), target_key=None):
    """{period: Fact} for facts whose name contains every token in ``includes``
    and none in ``exclude``. Two conflicting values for one period drop that
    period into ``clashes`` rather than being averaged or picked.

    Non-annual period labels (anything but ``FY####``) are ignored: P4 reads
    raw verified facts, and a quarterly or stub-period figure must not be
    mixed into an annual series (P4.6 F7). The upstream P3 gate enforces
    period compatibility for the valuation path; this is the equivalent guard
    for the diagnostic path, which reads facts directly.
    """
    out: dict[str, object] = {}
    clashes: dict[str, list] = {}
    for f in facts:
        period = getattr(f, "period", None)
        if not period or not _ANNUAL_PERIOD.match(period):
            continue
        # a non-finite extracted value is corrupt data - drop it rather than
        # let NaN/inf propagate into a ratio (P4.6 section 6).
        if not isinstance(f.value, (int, float)) or not math.isfinite(f.value):
            continue
        if target_key is not None:
            src = getattr(f, "source", None)
            if not src or src.target_key != target_key:
                continue
        name = f.name.lower()
        if not all(tok in name for tok in includes):
            continue
        if any(tok in name for tok in exclude):
            continue
        if f.period in out and abs(out[f.period].value - f.value) > 1e-6:
            clashes.setdefault(f.period, []).append(f)
            continue
        out[f.period] = f
    return out, clashes


def _monetary_scale(unit: str | None) -> float | None:
    """Scale factor for a MONETARY unit, in millions-equivalents.

    Unlike infra.units.resolve_scale, a bare "USD" / "$" / "dollars" resolves
    to 1e-6 (dollars, i.e. one-millionth of a million) rather than None -
    because P4 compares SBC-in-dollars against revenue-in-millions and must
    see that as a 1,000,000x mismatch, not "nothing to compare" (ISSUES.md
    #15). Non-monetary units (percent/ratio/shares) and unrecognised strings
    return None.
    """
    from ..infra.units import resolve_scale, NON_SCALE_MARKERS
    if not unit:
        return None
    low = unit.lower()
    if any(m in low for m in NON_SCALE_MARKERS) or "share" in low:
        return None
    sc = resolve_scale(unit)
    if sc is not None:
        return sc
    if any(m in low for m in ("usd", "$", "dollar", "eur", "gbp", "jpy")):
        return 1e-6           # bare currency = dollars = 1e-6 of a million
    return None


def _scale_conflict(*series: dict) -> str | None:
    """A reason string when the monetary facts feeding these series do not all
    resolve to ONE scale - within a series or across them. A ratio built on a
    mixed-scale set is wrong by that factor (ISSUES.md #15, the LYFT_FY2025
    1000x). None when every resolvable monetary fact agrees, or nothing
    resolves (nothing to compare)."""
    seen: set[float] = set()
    for sr in series:
        for fx in sr.values():
            sc = _monetary_scale(getattr(fx, "unit", ""))
            if sc is not None:
                seen.add(sc)
    if len(seen) > 1:
        return (f"unit-scale mismatch among the monetary metrics: resolved "
                f"scales {sorted(seen)} (millions-equivalent) - a ratio would "
                "be wrong by that factor (ISSUES.md #15)")
    return None


def _first_nonempty(*maps: dict) -> dict:
    """The first resolver that returned anything. Used so a filer-specific
    caption can be tried before a broad one without nesting `if not x`."""
    for m in maps:
        if m:
            return m
    return {}


def _evidence(fact, label: str = "") -> Evidence:
    return Evidence(
        label=label or fact.name,
        value=fact.value,
        unit=fact.unit,
        period=fact.period,
        quote=getattr(fact, "quote", "") or "",
        source_ref=_source_ref(fact),
    )


def _ratio_evidence(label, value, computed_from, unit="ratio", period=None) -> Evidence:
    return Evidence(label=label, value=value, unit=unit, period=period,
                    computed_from=tuple(computed_from))


# --------------------------------------------------------------------------- #
# Horizon classification - shared by every time-series diagnostic
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class _SeriesRead:
    periods: tuple[str, ...]
    values: tuple[float, ...]
    latest_period: str | None
    latest: float | None
    prior: tuple[float, ...]
    prior_median: float | None
    deviation: float | None          # (latest - prior_median) / |prior_median|
    outside_prior_range: bool
    monotonic: str | None            # "rising" | "falling" | None
    horizon: Horizon


def _read_series(series: dict[str, float]) -> _SeriesRead:
    """Order a period->value map and classify its shape. No thresholds here -
    just the arithmetic every diagnostic reuses so they agree on 'the latest
    year is unusual'."""
    periods = tuple(sorted(series))
    values = tuple(series[p] for p in periods)
    if not values:
        return _SeriesRead(periods, values, None, None, (), None, None,
                           False, None, Horizon.NOT_ENOUGH_HISTORY)

    latest_period, latest = periods[-1], values[-1]
    prior = values[:-1]
    if len(prior) < 2:
        # one period total -> SINGLE_YEAR (persistence cannot be assessed);
        # two periods -> LATEST_PERIOD, but still thin (caller marks LIMITED).
        thin_horizon = Horizon.SINGLE_YEAR if not prior else Horizon.LATEST_PERIOD
        return _SeriesRead(periods, values, latest_period, latest, prior,
                           None, None, False, None, thin_horizon)

    pm = median(prior)
    deviation = (latest - pm) / abs(pm) if pm else None
    outside = latest > max(prior) or latest < min(prior)
    monotonic = ("rising" if all(b > a for a, b in zip(values, values[1:]))
                 else "falling" if all(b < a for a, b in zip(values, values[1:]))
                 else None)

    if monotonic:
        horizon = Horizon.TREND
    elif outside and deviation is not None and abs(deviation) > MATERIAL_DEVIATION:
        horizon = Horizon.SINGLE_YEAR_ANOMALY
    else:
        horizon = Horizon.HISTORICAL_PATTERN
    return _SeriesRead(periods, values, latest_period, latest, prior, pm,
                       deviation, outside, monotonic, horizon)


def _fmt(x: float | None, nd: int = 2) -> str:
    return "n/a" if x is None else f"{x:,.{nd}f}"


def _pct(x: float | None, nd: int = 1) -> str:
    return "n/a" if x is None else f"{x * 100:+.{nd}f}%"


# P4.5: a diagnostic assessed from thin history reports what it found for the
# OBSERVED period and explicitly declines to speak about persistence. This
# phrasing is deliberately free of "clean" / "structurally normal" - see
# _OVERCLAIM.
def _thin_history(read: "_SeriesRead") -> bool:
    return len(read.values) < 3


def _observed_only(base_interpretation: str, n_periods: int) -> str:
    if n_periods <= 1:
        tail = ("Only one period is available, so historical persistence "
                "cannot be assessed. This holds for the observed period only.")
    else:
        tail = (f"Only {n_periods} periods are available, so a historical "
                "pattern is not established. This holds for the observed "
                "periods only.")
    base = base_interpretation.strip().rstrip(".").strip()
    return f"No issue identified in the observed data. {base}. {tail}"


def _apply_confidence(d: Diagnostic, read: "_SeriesRead") -> Diagnostic:
    """P4.5 - epistemic labelling only, never a new finding.

    When a diagnostic was assessed from fewer than three periods it is marked
    confidence=LIMITED. An ASSESSED_NO_ISSUE additionally has its horizon set
    to SINGLE_YEAR (one period) or LATEST_PERIOD (two) and its interpretation
    rewritten to the 'observed data only' phrasing, so a one-year read can
    never be voiced as 'historically clean' or 'structurally normal'. A
    FLAGGED finding KEEPS its flag - a real signal in one year is still a
    signal - but is marked LIMITED so the reader knows persistence is
    untested.
    """
    if not _thin_history(read):
        return d
    n = len(read.values)
    if d.state is DiagnosticState.ASSESSED_NO_ISSUE:
        return replace(
            d, confidence=Confidence.LIMITED,
            horizon=Horizon.SINGLE_YEAR if n <= 1 else Horizon.LATEST_PERIOD,
            interpretation=_observed_only(d.interpretation.rstrip("."), n),
            limitation=((d.limitation + " ") if d.limitation else "")
            + f"Assessed from {n} period(s); historical persistence not tested.")
    if d.state is DiagnosticState.FLAGGED:
        return replace(
            d, confidence=Confidence.LIMITED,
            limitation=((d.limitation + " ") if d.limitation else "")
            + (f"Assessed from {n} period(s); the signal is real for the "
               "observed data but its persistence is not established."))
    return d


# --------------------------------------------------------------------------- #
# Dimension A - earnings vs cash
# --------------------------------------------------------------------------- #
def _earnings_vs_cash(ni, cfo) -> Diagnostic:
    dim = "earnings_vs_cash"
    key = "CASH_EARNINGS_DIVERGENCE"
    common = sorted(set(ni) & set(cfo))
    if len(common) < 2:
        return _insufficient(
            key, dim,
            "fewer than two periods with both net income and CFO - a "
            "divergence pattern needs at least two.")

    ratios: dict[str, float] = {}
    ev: list[Evidence] = []
    for p in common:
        ev.append(_evidence(ni[p], f"net income {p}"))
        ev.append(_evidence(cfo[p], f"CFO {p}"))
        if ni[p].value > 0:                        # ratio only meaningful when NI > 0
            ratios[p] = cfo[p].value / ni[p].value
    latest = common[-1]
    gap_latest = cfo[latest].value - ni[latest].value

    fact = (f"{latest}: net income {_fmt(ni[latest].value, 0)} {ni[latest].unit}, "
            f"CFO {_fmt(cfo[latest].value, 0)} {cfo[latest].unit}.")
    formula = "CFO/NI per period (NI>0 only); latest gap = CFO - NI"

    if latest not in ratios:
        return Diagnostic(
            key=key, dimension=dim, state=DiagnosticState.INSUFFICIENT_DATA,
            horizon=Horizon.LATEST_PERIOD, fact=fact,
            diagnostic=(f"net income for {latest} is not positive "
                        f"({_fmt(ni[latest].value, 0)}); CFO/NI is undefined. "
                        f"Cash-vs-earnings gap for {latest} is "
                        f"{_fmt(gap_latest, 0)} {cfo[latest].unit}."),
            interpretation=("a loss year: the ratio cannot characterise cash "
                            "conversion. The level gap is reported, not scored."),
            valuation_relevance=("no ratio-based conclusion. If losses persist a "
                                 "perpetuity DCF may be the wrong instrument - "
                                 "handled in historical_fcff, not here."),
            potential_valuation_impact=ValuationImpact.UNKNOWN,
            direction=Direction.NEUTRAL, evidence=tuple(ev), formula=formula,
        )

    read = _read_series(ratios)
    ev.append(_ratio_evidence(f"CFO/NI {latest}", ratios[latest],
                              [ni[latest].name, cfo[latest].name], period=latest))
    diag = (f"CFO/NI = {_fmt(ratios[latest])} for {latest}"
            + (f"; prior-period median {_fmt(read.prior_median)}, "
               f"deviation {_pct(read.deviation)}" if read.prior_median else "")
            + f". Series: " + ", ".join(f"{p}={_fmt(ratios[p])}" for p in read.periods) + ".")

    adverse = ratios[latest] < 1.0 and (
        (read.deviation is not None and read.deviation < -MATERIAL_DEVIATION
         and read.outside_prior_range)
        or read.monotonic == "falling"
    )
    if adverse:
        struct = read.horizon is not Horizon.SINGLE_YEAR_ANOMALY
        return _apply_confidence(Diagnostic(
            key=key, dimension=dim, state=DiagnosticState.FLAGGED,
            horizon=read.horizon, fact=fact, diagnostic=diag,
            interpretation=(
                "cash generation is running materially below reported earnings"
                + (" and has done so across the series"
                   if struct else
                   f", but this is a single-year move ({latest}) and is not "
                   "established as a structural change - it may be one year's "
                   "accruals or working capital") + "."),
            valuation_relevance=(
                "reported net income overstates the cash the business produced "
                "this period. A DCF anchored on earnings-like figures would be "
                "richer than one anchored on cash; the base-FCFF sensitivity in "
                "historical_fcff already carries this."),
            potential_valuation_impact=(ValuationImpact.HIGH if struct
                                        else ValuationImpact.MEDIUM),
            direction=Direction.OVERSTATES_ECONOMIC_CASH,
            evidence=tuple(ev), formula=formula,
            threshold=(f"flag when CFO/NI<1 and (deviation < -{MATERIAL_DEVIATION:.0%} "
                       f"and outside prior range, or a falling series)"),
        ), read)

    return _apply_confidence(Diagnostic(
        key=key, dimension=dim, state=DiagnosticState.ASSESSED_NO_ISSUE,
        horizon=read.horizon, fact=fact, diagnostic=diag,
        interpretation=("cash conversion is in line with reported earnings "
                        "across the observed periods - no persistent divergence"),
        valuation_relevance=("no earnings-vs-cash adjustment indicated by this "
                             "dimension."),
        potential_valuation_impact=ValuationImpact.LOW,
        direction=Direction.NEUTRAL, evidence=tuple(ev), formula=formula,
        threshold=f"no flag: CFO/NI within {MATERIAL_DEVIATION:.0%} of prior median",
    ), read)


# --------------------------------------------------------------------------- #
# Dimension B - accrual intensity
# --------------------------------------------------------------------------- #
def _accruals(ni, cfo, revenue) -> Diagnostic:
    dim = "accruals"
    key = "HIGH_ACCRUAL_COMPONENT"
    common = sorted(set(ni) & set(cfo))
    if len(common) < 2:
        return _insufficient(
            key, dim,
            "fewer than two periods with both net income and CFO.")

    accr = {p: ni[p].value - cfo[p].value for p in common}          # cash-flow accruals
    latest = common[-1]
    ni_latest = ni[latest].value
    rev_latest = revenue[latest].value if latest in revenue else None

    ev = [_evidence(ni[latest], f"net income {latest}"),
          _evidence(cfo[latest], f"CFO {latest}")]
    if rev_latest:
        ev.append(_evidence(revenue[latest], f"revenue {latest}"))
    ev.append(_ratio_evidence(f"accruals {latest} (NI - CFO)", accr[latest],
                              [ni[latest].name, cfo[latest].name], unit=ni[latest].unit,
                              period=latest))

    ratio_ni = accr[latest] / abs(ni_latest) if abs(ni_latest) > 1e-6 else None
    ratio_rev = accr[latest] / rev_latest if rev_latest else None
    formula = ("accruals = NI - CFO; reported as accruals/|NI| and, when "
               "revenue is available, accruals/revenue")

    fact = (f"{latest}: NI - CFO = {_fmt(accr[latest], 0)} {ni[latest].unit} "
            f"(accruals/|NI| = {_fmt(ratio_ni)}"
            + (f", accruals/revenue = {_pct(ratio_rev)}" if ratio_rev is not None else "")
            + ").")

    if ratio_ni is None:
        return Diagnostic(
            key=key, dimension=dim, state=DiagnosticState.INSUFFICIENT_DATA,
            horizon=Horizon.LATEST_PERIOD, fact=fact,
            diagnostic=(f"net income for {latest} is ~0; accruals/|NI| is "
                        "undefined."),
            interpretation="cannot characterise accrual intensity for a ~0 NI year.",
            valuation_relevance="none from this dimension for this period.",
            potential_valuation_impact=ValuationImpact.UNKNOWN,
            evidence=tuple(ev), formula=formula)

    # horizon is read only over PROFITABLE periods: an accrual ratio across a
    # loss year is not comparable to one in a profit year, and a "trend" that
    # spans the crossing into profitability is an artefact of the sign change.
    read = _read_series({p: accr[p] / ni[p].value
                         for p in common if ni[p].value > 1e-6})
    high = ratio_ni > ACCRUAL_TO_NI_HIGH
    diag = (f"accruals/|NI| = {_fmt(ratio_ni)} for {latest}"
            + (f"; prior median {_fmt(read.prior_median)}" if read.prior_median else "")
            + ". A positive figure means reported earnings sit above operating "
            "cash for the period.")
    if high:
        return _apply_confidence(Diagnostic(
            key=key, dimension=dim, state=DiagnosticState.FLAGGED,
            horizon=read.horizon or Horizon.LATEST_PERIOD, fact=fact, diagnostic=diag,
            interpretation=(f"a large accrual component: over "
                            f"{ACCRUAL_TO_NI_HIGH:.0%} of earnings did not arrive "
                            "as operating cash this period. Not a quality verdict "
                            "on its own - accruals reverse - but a reason to lean "
                            "on cash-based figures for this year."),
            valuation_relevance=("earnings-based multiples or an earnings-anchored "
                                 "DCF would be higher than a cash-anchored one; the "
                                 "FCFF the pipeline uses is already cash-based."),
            potential_valuation_impact=ValuationImpact.MEDIUM,
            direction=Direction.OVERSTATES_ECONOMIC_CASH,
            evidence=tuple(ev), formula=formula,
            threshold=(f"accruals/|NI| > {ACCRUAL_TO_NI_HIGH:.0%}. rationale: above "
                       "a quarter, cash and accounting earnings diverge materially. "
                       "limitation: undefined near NI=0; reverses over time.")), read)
    return _apply_confidence(Diagnostic(
        key=key, dimension=dim, state=DiagnosticState.ASSESSED_NO_ISSUE,
        horizon=read.horizon or Horizon.LATEST_PERIOD, fact=fact, diagnostic=diag,
        interpretation="accrual component is within the range seen across the "
                       "observed periods",
        valuation_relevance="no accrual-driven adjustment indicated.",
        potential_valuation_impact=ValuationImpact.LOW,
        evidence=tuple(ev), formula=formula,
        threshold=f"no flag: accruals/|NI| <= {ACCRUAL_TO_NI_HIGH:.0%}"), read)


# --------------------------------------------------------------------------- #
# Dimension C - working-capital quality
# --------------------------------------------------------------------------- #
_WC_BUCKETS = {
    "receivables": ("accounts receivable", "receivable", "customer-related"),
    "payables": ("accounts payable", "payable"),
    "inventory": ("inventor",),
    "prepaid_and_other_assets": ("prepaid", "other current assets",
                                 "other assets", "other operating asset"),
    "accrued_liabilities": ("accrued",),
    "deferred_revenue": ("deferred revenue", "contract liabilit", "contract asset"),
    "insurance_and_reserves": ("insurance reserve", "loss reserve",
                               "claims reserve", "reserve"),
    "operating_lease": ("operating lease", "lease liabilit",
                        "right-of-use", "lease right"),
    "other_operating_liabilities": ("other current liabilities",
                                    "other liabilities",
                                    "other non-current liabilities",
                                    "other operating liabilit"),
}

# A cash-flow line names an OPERATING WORKING-CAPITAL movement only if its
# caption carries one of these change markers. Measured across the corpus:
# Uber and Lyft write "Change in <balance>", DoorDash writes "<balance>
# (change)". A line without a marker (capex, the net-change subtotal, a
# gain/loss add-back, "Other adjustments") is NOT working capital and is
# skipped entirely rather than swept in as "unknown".
_WC_CHANGE_MARKERS = ("change in ", "(change)", "(increase) decrease",
                      "increase (decrease) in", "decrease (increase) in")

# NON-operating or non-cash bridge items - excluded even if they carry a
# change marker. Generic accounting vocabulary, not issuer-specific aliases.
# The financing/investing block (P4.6 finding F3): a "Change in long-term
# debt" or "Change in marketable securities" line carries the change marker
# but is a FINANCING or INVESTING flow, not operating working capital.
# Without these it was routed to UNKNOWN_OPERATING_COMPONENT and summed into
# the net working-capital total, distorting the CFO-dependence magnitude and
# mislabelling a financing flow as "operating".
_WC_NOT = ("depreciation", "amortiz", "stock-based", "share-based",
           "deferred income tax", "deferred tax ", "unrealized", "unrealise",
           "impairment", "bad debt", "allowance for", "accretion",
           "net income", "net loss", "net cash", "net increase", "net decrease",
           "beginning of period", "end of period", "revaluation", "fair value",
           "contingent consideration", "derivative", "warrant", "pension",
           "property and equipment", "capital expenditure",
           "sale of investment", "sale and disposal", "equity method",
           "gain on", "loss on", "loss from", "gain from",
           # financing
           "long-term debt", "short-term debt", "short-term borrowing",
           "long-term borrowing", "borrowings", "notes payable",
           "commercial paper", "line of credit", "revolving", "revolver",
           "debt issuance", "financing cost", "financing activities",
           "repayment", "repurchase", "treasury stock", "dividend",
           "proceeds from", "issuance of", "redemption of", "principal payment",
           "finance lease", "capital lease",
           # investing / cash reclassification
           "marketable securit", "available-for-sale", "held-to-maturity",
           "investing activities", "restricted cash",
           "cash and cash equivalents", "cash equivalents",
           "acquisition", "divestiture", "purchase of business")

_WC_STRUCTURAL = ("total adjustments", "adjustments to reconcile",
                  "changes in operating assets and liabilities",
                  "changes in assets and liabilities")


def _classify_wc_line(name: str) -> str:
    """One of: a bucket name, 'UNKNOWN_OPERATING_COMPONENT',
    'EXCLUDED_NON_OPERATING', 'STRUCTURAL', or 'NO_CHANGE_MARKER'.

    Fail-closed: a line that carries a change marker, survives the exclusion
    list, and matches no bucket is UNKNOWN_OPERATING_COMPONENT - counted in
    the net total, named in the coverage report, never silently dropped. A
    line with NO change marker that is also not clearly non-cash is reported
    as an unmarked candidate, so 'FULL_COVERAGE' is never claimed while a
    possible operating item sits unexamined.
    """
    low = name.lower()
    if any(t in low for t in _WC_STRUCTURAL):
        return "STRUCTURAL"
    if any(t in low for t in _WC_NOT):
        return "EXCLUDED_NON_OPERATING"
    if not any(t in low for t in _WC_CHANGE_MARKERS):
        return "NO_CHANGE_MARKER"
    for bucket, toks in _WC_BUCKETS.items():
        if any(t in low for t in toks):
            return bucket
    return "UNKNOWN_OPERATING_COMPONENT"


def _wc_lines_for_period(facts, period):
    """Return (buckets, unknown, unmarked) for one period's cash-flow
    reconciliation.

    ``buckets``   known bucket -> facts (classified).
    ``unknown``   change-marked lines that matched no bucket - counted in the
                  net total, named, never dropped.
    ``unmarked``  lines with no change marker that are not clearly non-cash -
                  possible operating items the engine did not capture; their
                  presence blocks a FULL_COVERAGE claim.
    """
    buckets: dict[str, list] = {}
    unknown: list = []
    unmarked: list = []
    for f in facts:
        if getattr(f, "period", None) != period:
            continue
        src = getattr(f, "source", None)
        if not src or src.target_key != "cash_flows":
            continue
        cls = _classify_wc_line(f.name)
        if cls in ("EXCLUDED_NON_OPERATING", "STRUCTURAL"):
            continue
        if cls == "NO_CHANGE_MARKER":
            unmarked.append(f)
        elif cls == "UNKNOWN_OPERATING_COMPONENT":
            unknown.append(f)
        else:
            buckets.setdefault(cls, []).append(f)
    return buckets, unknown, unmarked


def _wc_coverage(classified: float, unclassified: float, unmarked_sum: float,
                 unknown_names: tuple[str, ...],
                 unmarked_names: tuple[str, ...], unit: str) -> WorkingCapitalCoverage:
    """FULL / PARTIAL / NO coverage for one period's attribution.

    The net total (classified + unclassified) is complete for the lines the
    engine identified as working capital. Coverage reports whether the
    COMPOSITION can be described. An unmarked candidate (a cash-flow line
    with no change marker that is not clearly non-cash) downgrades FULL to
    PARTIAL only when its magnitude is material against the movement -
    immaterial unmarked lines are listed but do not by themselves gate the
    flag.
    """
    gross = abs(classified) + abs(unclassified)
    ratio = abs(classified) / gross if gross else None
    material_unmarked = gross > 0 and abs(unmarked_sum) > 0.10 * gross
    if abs(classified) < 1e-6 and abs(unclassified) >= 1e-6:
        status = WCCoverage.NO_COVERAGE
    elif abs(unclassified) < 1e-6 and not material_unmarked:
        status = WCCoverage.FULL_COVERAGE
    else:
        status = WCCoverage.PARTIAL_COVERAGE
    return WorkingCapitalCoverage(
        classified=classified, unclassified=unclassified, coverage_ratio=ratio,
        status=status, unknown_components=unknown_names,
        unmarked_candidates=unmarked_names, unit=unit)


def _working_capital(facts, cfo, periods) -> Diagnostic:
    dim = "working_capital"
    key = "WORKING_CAPITAL_DEPENDENT_CFO"
    per_period_total: dict[str, float] = {}          # complete: buckets + unknown
    per_period_classified: dict[str, float] = {}
    per_period_unknown: dict[str, list] = {}
    per_period_unmarked: dict[str, list] = {}
    per_period_ev: dict[str, list] = {}
    for p in periods:
        buckets, unknown, unmarked = _wc_lines_for_period(facts, p)
        if not buckets and not unknown:
            continue
        classified = 0.0
        evs = []
        for bucket, fs in buckets.items():
            for x in fs:
                classified += x.value
                evs.append(_evidence(x, f"{bucket}: {x.name}"))
        unknown_sum = sum(x.value for x in unknown)
        for x in unknown:
            evs.append(_evidence(x, f"UNKNOWN_OPERATING_COMPONENT: {x.name}"))
        per_period_classified[p] = classified
        per_period_unknown[p] = unknown
        per_period_unmarked[p] = unmarked
        per_period_total[p] = classified + unknown_sum      # never drops the unknown
        per_period_ev[p] = sorted(evs, key=lambda e: abs(e.value or 0.0), reverse=True)

    common = sorted(set(per_period_total) & set(cfo))
    if not common:
        return _insufficient(key, dim,
                             "no working-capital reconciliation lines matched, "
                             "or none share a period with CFO.")
    latest = common[-1]
    cfo_latest = cfo[latest].value
    share = per_period_total[latest] / abs(cfo_latest) if cfo_latest else None
    read = _read_series({p: per_period_total[p] for p in common})

    unknown_latest = per_period_unknown.get(latest, [])
    unknown_sum_latest = sum(x.value for x in unknown_latest)
    unmarked_latest = per_period_unmarked.get(latest, [])
    cov = _wc_coverage(
        per_period_classified.get(latest, 0.0), unknown_sum_latest,
        sum(x.value for x in unmarked_latest),
        tuple(x.name for x in unknown_latest),
        tuple(x.name for x in unmarked_latest), cfo[latest].unit)

    ev = list(per_period_ev.get(latest, [])) + [_evidence(cfo[latest], f"CFO {latest}")]
    ev.append(_ratio_evidence(f"net WC contribution / |CFO| {latest}", share,
                              ["change-in-* lines", cfo[latest].name], period=latest))
    # "biggest" is only used to name a driver - it must come from a CLASSIFIED
    # line, never an unknown, so the composition claim stays honest.
    classified_ev = [e for e in per_period_ev.get(latest, [])
                     if not e.label.startswith("UNKNOWN_OPERATING_COMPONENT")]
    biggest = max(classified_ev, key=lambda e: abs(e.value or 0.0), default=None)

    formula = ("net WC contribution = sum of EVERY operating asset/liability "
               "change in the cash-flow reconciliation (known buckets + "
               "unclassified), for the period; share = that / |CFO|")
    fact = (f"{latest}: net working-capital contribution to CFO = "
            f"{_fmt(per_period_total[latest], 0)} {cfo[latest].unit}, "
            f"{_pct(share)} of CFO. Attribution: {cov.render()}.")
    series_txt = ", ".join(f"{p}={_fmt(per_period_total[p], 0)}" for p in read.periods)

    # Fail closed: if nothing could be placed in a bucket, or the classified
    # share is below WC_COVERAGE_SUFFICIENT, the SIZE of the movement is still
    # reported but no composition/pattern claim is made.
    if cov.status is WCCoverage.NO_COVERAGE or (
        cov.coverage_ratio is not None
        and cov.coverage_ratio < WC_COVERAGE_SUFFICIENT
    ):
        return Diagnostic(
            key=key, dimension=dim, state=DiagnosticState.INSUFFICIENT_DATA,
            horizon=read.horizon, fact=fact,
            diagnostic=(f"net working capital moved CFO by {_pct(share)} in "
                        f"{latest} (series: {series_txt}), but only "
                        f"{'0%' if cov.coverage_ratio is None else f'{cov.coverage_ratio:.0%}'} "
                        "of that movement could be placed in a named component "
                        f"({cov.render()})."),
            interpretation=("the magnitude is measured; the composition is not. "
                            "A partial attribution is not presented as a full "
                            "working-capital explanation."),
            valuation_relevance=("the dependence of CFO on working capital cannot "
                                 "be characterised from the components available. "
                                 "INSUFFICIENT_DATA, not 'no issue'."),
            potential_valuation_impact=ValuationImpact.UNKNOWN,
            direction=Direction.NEUTRAL, evidence=tuple(ev), formula=formula,
            limitation=("unclassified operating working-capital components: "
                        + "; ".join(cov.unknown_components)),
            coverage=cov)

    partial = cov.status is WCCoverage.PARTIAL_COVERAGE
    _pieces = []
    if partial and cov.unknown_components:
        _pieces.append(f"{cov.unclassified:,.0f} {cov.unit} is in unclassified "
                       f"change lines ({', '.join(cov.unknown_components)})")
    if partial and cov.unmarked_candidates:
        _pieces.append("cash-flow lines with no change marker may also be "
                       f"operating items ({', '.join(cov.unmarked_candidates)})")
    partial_note = ((" " + "; ".join(_pieces)
                     + ". The movement size is reported; the composition is not "
                     "fully certified.") if _pieces else "")
    conf = Confidence.LIMITED if partial else Confidence.NORMAL

    persistent_high = (share is not None and abs(share) > WORKING_CAPITAL_TO_CFO_HIGH
                       and all(abs(per_period_total[p]) > WORKING_CAPITAL_TO_CFO_HIGH
                               * abs(cfo[p].value) for p in common if cfo[p].value))
    one_year_swing = (share is not None and abs(share) > WORKING_CAPITAL_TO_CFO_HIGH
                      and read.outside_prior_range
                      and read.deviation is not None
                      and abs(read.deviation) > MATERIAL_DEVIATION)

    if one_year_swing:
        return Diagnostic(
            key="ONE_YEAR_WORKING_CAPITAL_SWING", dimension=dim,
            state=DiagnosticState.FLAGGED, horizon=Horizon.SINGLE_YEAR_ANOMALY,
            fact=fact,
            diagnostic=(f"working capital moved CFO by {_pct(share)} of its value in "
                        f"{latest}, outside the prior-year range (series: {series_txt}). "
                        "Deviation from prior median " + _pct(read.deviation) + "."),
            interpretation=("one year's cash flow is materially carried or "
                            "depressed by a working-capital movement that is not "
                            "seen in the other periods. Diagnostic only - nothing "
                            "is normalised on this basis."),
            valuation_relevance=("anchoring the DCF on this year's CFO imports a "
                                 "one-off balance movement as if it were a run "
                                 "rate. The multi-year FCFF bound in "
                                 "historical_fcff is where this is stress-tested."),
            potential_valuation_impact=ValuationImpact.MEDIUM,
            direction=Direction.OVERSTATES_ECONOMIC_CASH if per_period_total[latest] > 0
            else Direction.UNDERSTATES_ECONOMIC_CASH,
            evidence=tuple(ev), formula=formula, confidence=conf,
            limitation=partial_note.strip(), coverage=cov,
            threshold=(f"flag when |net WC / CFO| > {WORKING_CAPITAL_TO_CFO_HIGH:.0%} "
                       f"AND outside prior range AND |deviation| > {MATERIAL_DEVIATION:.0%}"))

    if persistent_high:
        return Diagnostic(
            key=key, dimension=dim, state=DiagnosticState.FLAGGED,
            horizon=Horizon.HISTORICAL_PATTERN, fact=fact,
            diagnostic=(f"net working capital contributes {_pct(share)} of CFO in "
                        f"{latest} and a comparable share in every prior period "
                        f"(series: {series_txt})."),
            interpretation=("a large and RECURRING share of operating cash comes "
                            "from working-capital movements"
                            + (f", dominated by {biggest.label}" if biggest else "")
                            + ". This can be a structural feature (float, deferred "
                            "revenue) rather than an anomaly, but a balance that "
                            "builds can also release."),
            valuation_relevance=("CFO, and the FCFF built from it, depends on the "
                                 "working-capital build continuing at this rate. A "
                                 "slowdown or reversal would lower cash generation "
                                 "without earnings changing."),
            potential_valuation_impact=ValuationImpact.MEDIUM,
            direction=Direction.OVERSTATES_ECONOMIC_CASH if per_period_total[latest] > 0
            else Direction.NEUTRAL,
            evidence=tuple(ev), formula=formula, confidence=conf,
            limitation=partial_note.strip(), coverage=cov,
            threshold=(f"flag when |net WC / CFO| > {WORKING_CAPITAL_TO_CFO_HIGH:.0%} "
                       "in the latest and every prior period"))

    return _apply_confidence(Diagnostic(
        key=key, dimension=dim, state=DiagnosticState.ASSESSED_NO_ISSUE,
        horizon=read.horizon, fact=fact,
        diagnostic=(f"net working-capital contribution to CFO is {_pct(share)} in "
                    f"{latest} (series: {series_txt}) - not a dominant share and "
                    "not a one-year outlier."),
        interpretation="working-capital movements are not carrying reported cash "
                       "flow across the observed periods" + partial_note,
        valuation_relevance="no working-capital-driven adjustment indicated.",
        potential_valuation_impact=ValuationImpact.LOW,
        evidence=tuple(ev), formula=formula,
        confidence=conf, limitation=partial_note.strip(), coverage=cov,
        threshold=f"no flag: |net WC / CFO| <= {WORKING_CAPITAL_TO_CFO_HIGH:.0%}"), read)


# --------------------------------------------------------------------------- #
# Dimension D - revenue quality (cash-collection proxy)
# --------------------------------------------------------------------------- #
# The proxy limitation, attached to EVERY revenue-quality output: this
# dimension is a cash-flow REVENUE_CASH_DIVERGENCE screen, not a full
# REVENUE_QUALITY_ASSESSMENT. The latter needs data the pipeline does not
# extract (P5/P8 candidate - see targets.py note).
_REVENUE_PROXY_LIMITATION = (
    "This is REVENUE_CASH_DIVERGENCE, not a full REVENUE_QUALITY_ASSESSMENT. "
    "The accounts-receivable balance, contract assets, contract liabilities / "
    "deferred revenue and the allowance for doubtful accounts are not "
    "extracted, so this rests on the cash-flow 'change in accounts "
    "receivable' as a collection-lag proxy. It is not sufficient by itself "
    "to establish a revenue-recognition issue.")


def _revenue_quality(facts, revenue, cfo) -> Diagnostic:
    dim = "revenue_quality"
    key = "REVENUE_CASH_DIVERGENCE"
    periods = sorted(revenue)
    if len(periods) < 2:
        d = _insufficient(key, dim, "fewer than two revenue periods.")
        return replace(d, limitation=_REVENUE_PROXY_LIMITATION)

    # cash-flow receivables drag, per period, from the same reconciliation lines
    ar: dict[str, float] = {}
    ar_facts: dict[str, list] = {}
    for p in periods:
        lines = _wc_lines_for_period(facts, p)[0].get("receivables", [])
        if lines:
            ar[p] = sum(x.value for x in lines)
            ar_facts[p] = lines

    latest, prev = periods[-1], periods[-2]
    rev_growth = ((revenue[latest].value - revenue[prev].value) / revenue[prev].value
                  if revenue[prev].value else None)

    ev = [_evidence(revenue[latest], f"revenue {latest}"),
          _evidence(revenue[prev], f"revenue {prev}")]
    formula = ("revenue growth vs the cash-flow receivables drag. PROXY: the "
               "cash-flow 'change in accounts receivable' stands in for the "
               "balance-sheet receivable, which is not extracted.")

    # Case C - only the proxy is available AND it too is missing a period.
    if latest not in ar or prev not in ar or not ar[prev]:
        return Diagnostic(
            key=key, dimension=dim, state=DiagnosticState.INSUFFICIENT_DATA,
            horizon=Horizon.LATEST_PERIOD, confidence=Confidence.LIMITED,
            fact=(f"{latest}: revenue {_fmt(revenue[latest].value, 0)} "
                  f"{revenue[latest].unit}, growth {_pct(rev_growth)}. Receivables "
                  "change from the cash flow statement is not available for both "
                  "periods."),
            diagnostic=("cannot compare revenue growth to a cash-collection proxy "
                        "without the receivables reconciliation line in both years."),
            interpretation=("no revenue/cash conclusion. Neither the proxy nor "
                            "any balance-sheet revenue-quality field is available."),
            valuation_relevance="none from this dimension.",
            potential_valuation_impact=ValuationImpact.UNKNOWN,
            evidence=tuple(ev), formula=formula,
            limitation=_REVENUE_PROXY_LIMITATION)

    for p in (latest, prev):
        for x in ar_facts[p]:
            ev.append(_evidence(x, f"receivables change {p}: {x.name}"))
    # both drags are uses of cash (negative); compare magnitudes
    drag_growth = ((abs(ar[latest]) - abs(ar[prev])) / abs(ar[prev])
                   if ar[prev] else None)
    ev.append(_ratio_evidence("revenue growth", rev_growth,
                              [revenue[latest].name, revenue[prev].name], unit="pct",
                              period=latest))
    ev.append(_ratio_evidence("receivables-drag growth", drag_growth,
                              [ar_facts[latest][0].name, ar_facts[prev][0].name],
                              unit="pct", period=latest))

    # Is the divergence a one-year move or a repeated one? With >=3 receivables
    # periods, check whether an earlier drag spike reversed (Case B - timing).
    ar_read = _read_series({p: abs(ar[p]) for p in sorted(ar)})
    reversed_before = (len(ar_read.values) >= 3
                       and ar_read.values[-2] > ar_read.values[-3] * 1.3
                       and ar_read.values[-1] < ar_read.values[-2])

    fact = (f"{latest}: revenue growth {_pct(rev_growth)}; cash-flow receivables "
            f"drag {_fmt(ar[prev], 0)} -> {_fmt(ar[latest], 0)} "
            f"{revenue[latest].unit} ({_pct(drag_growth)}).")
    diag = (f"receivables use of cash grew {_pct(drag_growth)} against revenue "
            f"growth of {_pct(rev_growth)}.")

    divergence = (rev_growth is not None and rev_growth > 0
                  and drag_growth is not None
                  and drag_growth > RECEIVABLES_DRAG_MULTIPLE * rev_growth
                  and ar[latest] < 0)
    if divergence:
        return Diagnostic(
            key=key, dimension=dim, state=DiagnosticState.FLAGGED,
            horizon=Horizon.LATEST_PERIOD, confidence=Confidence.LIMITED,
            fact=fact, diagnostic=diag,
            interpretation=("on this cash-flow proxy, billings are being "
                            "recognised as revenue faster than the associated "
                            "cash is collected in the latest period. This is a "
                            "single-year divergence and is NOT described as "
                            "structural revenue-quality deterioration"
                            + (" - an earlier drag spike reversed the following "
                               "year, consistent with timing" if reversed_before
                               else "") + ". It makes no claim about revenue "
                            "recognition being right or wrong: one large customer "
                            "or a period-end timing effect produces the same "
                            "signal."),
            valuation_relevance=("if the collection lag persists, reported revenue "
                                 "growth overstates the growth in cash the "
                                 "business will actually see. Whether it persists "
                                 "cannot be judged from the proxy alone."),
            potential_valuation_impact=ValuationImpact.MEDIUM,
            direction=Direction.OVERSTATES_ECONOMIC_CASH,
            evidence=tuple(ev), formula=formula,
            limitation=_REVENUE_PROXY_LIMITATION,
            threshold=(f"flag when revenue growth>0 and receivables-drag growth > "
                       f"{RECEIVABLES_DRAG_MULTIPLE:g}x revenue growth. rationale: "
                       "collections lagging billings by enough to notice. "
                       "limitation: a proxy, and timing-sensitive."))
    return Diagnostic(
        key=key, dimension=dim, state=DiagnosticState.ASSESSED_NO_ISSUE,
        horizon=Horizon.LATEST_PERIOD, confidence=Confidence.LIMITED,
        fact=fact, diagnostic=diag,
        interpretation=("no revenue/cash divergence in the observed data: the "
                        "cash-flow receivables drag is not growing materially "
                        "faster than revenue. Persistence and the underlying "
                        "balances are not assessed."),
        valuation_relevance="no revenue/cash divergence indicated on the proxy.",
        potential_valuation_impact=ValuationImpact.LOW,
        evidence=tuple(ev), formula=formula,
        limitation=_REVENUE_PROXY_LIMITATION,
        threshold=(f"no flag: receivables-drag growth <= "
                   f"{RECEIVABLES_DRAG_MULTIPLE:g}x revenue growth"))


# --------------------------------------------------------------------------- #
# Dimension E - capital intensity
# --------------------------------------------------------------------------- #
def _capital_intensity(capex, cfo, revenue) -> tuple[Diagnostic, Diagnostic]:
    dim = "capital_intensity"
    common = sorted(set(capex) & set(cfo))
    # intensity diagnostic
    if not common:
        intensity = _insufficient("HIGH_CAPITAL_INTENSITY", dim,
                                  "capex and CFO do not share a period.")
    else:
        latest = common[-1]
        cx = abs(capex[latest].value)
        cfo_l = cfo[latest].value
        rev_l = revenue[latest].value if latest in revenue else None
        cx_cfo = cx / abs(cfo_l) if cfo_l else None
        cx_rev = cx / rev_l if rev_l else None
        read = _read_series({p: abs(capex[p].value) / abs(cfo[p].value)
                             for p in common if cfo[p].value})
        ev = [_evidence(capex[latest], f"capex {latest}"),
              _evidence(cfo[latest], f"CFO {latest}")]
        if rev_l:
            ev.append(_evidence(revenue[latest], f"revenue {latest}"))
        ev.append(_ratio_evidence(f"capex/CFO {latest}", cx_cfo,
                                  [capex[latest].name, cfo[latest].name], period=latest))
        fact = (f"{latest}: capex {_fmt(cx, 0)} {capex[latest].unit}, "
                f"capex/CFO {_fmt(cx_cfo)}"
                + (f", capex/revenue {_pct(cx_rev)}" if cx_rev is not None else "") + ".")
        formula = "capex/CFO and capex/revenue, latest period; trend over the series"
        high = (cx_cfo is not None and cx_cfo > CAPEX_TO_CFO_INTENSIVE) or \
               (cx_rev is not None and cx_rev > CAPEX_TO_REVENUE_INTENSIVE)
        if high:
            intensity = _apply_confidence(Diagnostic(
                key="HIGH_CAPITAL_INTENSITY", dimension=dim,
                state=DiagnosticState.FLAGGED, horizon=read.horizon or Horizon.LATEST_PERIOD,
                fact=fact,
                diagnostic=(f"capex/CFO = {_fmt(cx_cfo)} "
                            f"(threshold {CAPEX_TO_CFO_INTENSIVE:.0%}), "
                            f"capex/revenue = {_pct(cx_rev)} "
                            f"(threshold {CAPEX_TO_REVENUE_INTENSIVE:.0%}). Series "
                            "capex/CFO: " + ", ".join(f"{p}={_fmt(v)}" for p, v
                            in zip(read.periods, read.values)) + "."),
                interpretation=("a large share of operating cash is reinvested in "
                                "property and equipment. Free-cash generation is "
                                "geared to the capex cycle."),
                valuation_relevance=("FCFF is highly sensitive to the capex "
                                     "assumption, and how much of this capex is "
                                     "maintenance vs growth is the dominant "
                                     "question for terminal value - see the "
                                     "maintenance-capex diagnostic."),
                potential_valuation_impact=ValuationImpact.HIGH,
                direction=Direction.OVERSTATES_ECONOMIC_CASH,
                evidence=tuple(ev), formula=formula,
                threshold=(f"flag when capex/CFO > {CAPEX_TO_CFO_INTENSIVE:.0%} or "
                           f"capex/revenue > {CAPEX_TO_REVENUE_INTENSIVE:.0%}. "
                           "limitation: one growth year trips this without the "
                           "model being structurally capital-heavy.")), read)
        else:
            intensity = _apply_confidence(Diagnostic(
                key="HIGH_CAPITAL_INTENSITY", dimension=dim,
                state=DiagnosticState.ASSESSED_NO_ISSUE,
                horizon=read.horizon or Horizon.LATEST_PERIOD, fact=fact,
                diagnostic=(f"capex/CFO = {_fmt(cx_cfo)}, capex/revenue = "
                            f"{_pct(cx_rev)} - both below the intensity thresholds."),
                interpretation="an asset-light operating model on the observed periods",
                valuation_relevance=("FCFF is not dominated by the capex line; "
                                     "capex-driven terminal-value risk is limited."),
                potential_valuation_impact=ValuationImpact.LOW,
                evidence=tuple(ev), formula=formula,
                threshold=(f"no flag: capex/CFO <= {CAPEX_TO_CFO_INTENSIVE:.0%} and "
                           f"capex/revenue <= {CAPEX_TO_REVENUE_INTENSIVE:.0%}")), read)

    # maintenance-capex diagnostic - almost always unverifiable from a 10-K
    maint = Diagnostic(
        key="MAINTENANCE_CAPEX_UNVERIFIABLE", dimension=dim,
        state=DiagnosticState.INSUFFICIENT_DATA, horizon=Horizon.LATEST_PERIOD,
        fact=("the filing reports total purchases of property and equipment; it "
              "does not split maintenance from growth capex."),
        diagnostic=("no maintenance/growth capex breakdown is disclosed, and it "
                    "cannot be derived without assuming a depreciation-to-"
                    "maintenance identity the filing does not support."),
        interpretation=("MAINTENANCE_CAPEX_UNVERIFIABLE: the share of capex "
                        "required just to hold the asset base steady is unknown."),
        valuation_relevance=("terminal free cash flow depends on maintenance "
                             "capex, which is not observable here. Treat any "
                             "maintenance-capex figure in a scenario as an "
                             "analyst assumption, not a filing fact."),
        potential_valuation_impact=ValuationImpact.UNKNOWN,
        direction=Direction.NEUTRAL,
        evidence=tuple(_evidence(capex[p], f"capex {p}") for p in sorted(capex)),
        formula="n/a - not computable from the filing",
    )
    return intensity, maint


# --------------------------------------------------------------------------- #
# Dimension F - SBC materiality
# --------------------------------------------------------------------------- #
def _sbc_materiality(sbc, revenue, cfo, ni) -> Diagnostic:
    dim = "sbc"
    key = "HIGH_SBC"
    if not sbc:
        return _insufficient(key, dim, "no stock-based compensation fact extracted.")
    latest = max(sbc)
    s = sbc[latest].value
    n_sbc = len(sbc)
    if abs(s) < 1e-6:
        return Diagnostic(
            key=key, dimension=dim, state=DiagnosticState.ASSESSED_NO_ISSUE,
            horizon=Horizon.SINGLE_YEAR if n_sbc <= 1 else Horizon.LATEST_PERIOD,
            confidence=Confidence.LIMITED if n_sbc < 3 else Confidence.NORMAL,
            fact=f"{latest}: stock-based compensation = 0.",
            diagnostic="the filing reports no SBC expense for the latest period.",
            interpretation=("no SBC expense in the observed data; equity "
                            "compensation is not a material cost for this "
                            "period."),
            valuation_relevance="no SBC-driven difference between reported and "
                                "economic FCFF.",
            potential_valuation_impact=ValuationImpact.NONE,
            evidence=(_evidence(sbc[latest], f"SBC {latest}"),),
            formula="SBC / revenue, SBC / CFO, SBC / NI")

    rev_l = revenue[latest].value if latest in revenue else None
    cfo_l = cfo[latest].value if latest in cfo else None
    ni_l = ni[latest].value if latest in ni else None
    # ratios are only meaningful against a POSITIVE denominator - SBC/revenue
    # with revenue <= 0 (a contra-revenue year) is arithmetic nonsense, not a
    # materiality signal (P4.6 F8).
    s_rev = s / rev_l if (rev_l and rev_l > 0) else None
    s_cfo = s / cfo_l if (cfo_l and cfo_l > 0) else None
    s_ni = s / ni_l if ni_l and ni_l > 0 else None
    read = _read_series({p: sbc[p].value / revenue[p].value
                         for p in sorted(set(sbc) & set(revenue))
                         if revenue[p].value and revenue[p].value > 0})

    ev = [_evidence(sbc[latest], f"SBC {latest}")]
    for label, src in (("revenue", revenue), ("CFO", cfo), ("net income", ni)):
        if latest in src:
            ev.append(_evidence(src[latest], f"{label} {latest}"))
    ev.append(_ratio_evidence(f"SBC/revenue {latest}", s_rev, [sbc[latest].name], unit="pct"))
    ev.append(_ratio_evidence(f"SBC/CFO {latest}", s_cfo, [sbc[latest].name], unit="ratio"))

    fact = (f"{latest}: SBC = {_fmt(s, 0)} {sbc[latest].unit}. "
            f"SBC/revenue {_pct(s_rev)}, SBC/CFO {_fmt(s_cfo)}, "
            f"SBC/NI {_fmt(s_ni) if s_ni is not None else 'n/a'}.")
    formula = "SBC / revenue, SBC / CFO, SBC / NI (NI>0), latest period; trend of SBC/revenue"
    if s_rev is None and s_cfo is None:
        return replace(
            _insufficient(key, dim, "no positive revenue or CFO to scale SBC "
                          f"against for {latest}."),
            fact=f"{latest}: SBC = {_fmt(s, 0)} {sbc[latest].unit}; revenue and "
                 "CFO are not positive, so no materiality ratio is defined.",
            evidence=(_evidence(sbc[latest], f"SBC {latest}"),))
    material = (s_rev is not None and s_rev > SBC_TO_REVENUE_MATERIAL) or \
               (s_cfo is not None and s_cfo > SBC_TO_CFO_MATERIAL)
    trend_txt = (", ".join(f"{p}={_pct(v)}" for p, v in zip(read.periods, read.values))
                 if read.periods else "n/a")
    diag = (f"SBC is {_pct(s_rev)} of revenue and {_fmt(s_cfo)}x CFO in {latest}. "
            f"SBC/revenue trend: {trend_txt}.")

    if material:
        return _apply_confidence(Diagnostic(
            key=key, dimension=dim, state=DiagnosticState.FLAGGED,
            horizon=read.horizon or Horizon.LATEST_PERIOD, fact=fact, diagnostic=diag,
            interpretation=("material employee compensation is being paid in "
                            "equity. It is a real economic cost regardless of "
                            "being non-cash: shareholders bear it through "
                            "dilution or through buybacks funded to offset it. "
                            "P4 does NOT decide the treatment - it exposes the "
                            "question."),
            valuation_relevance=("reported FCFF may overstate economic cash "
                                 "generation if SBC is treated as costless AND "
                                 "dilution is ignored. The pipeline's own FCFF "
                                 "subtracts SBC at full value and holds shares "
                                 "flat (ADR 0002); an alternative is to add SBC "
                                 "back and model dilution instead - the two must "
                                 "not both be applied. See the SBC-dilution "
                                 "diagnostic for observed share growth."),
            potential_valuation_impact=ValuationImpact.HIGH,
            direction=Direction.OVERSTATES_ECONOMIC_CASH,
            evidence=tuple(ev), formula=formula,
            threshold=(f"flag when SBC/revenue > {SBC_TO_REVENUE_MATERIAL:.0%} or "
                       f"SBC/CFO > {SBC_TO_CFO_MATERIAL:.0%}. rationale and "
                       "limitations at the constant definitions.")), read)
    return _apply_confidence(Diagnostic(
        key=key, dimension=dim, state=DiagnosticState.ASSESSED_NO_ISSUE,
        horizon=read.horizon or Horizon.LATEST_PERIOD, fact=fact, diagnostic=diag,
        interpretation=("SBC is present but below the materiality lines relative "
                        "to revenue and CFO in the observed data"),
        valuation_relevance=("SBC is unlikely to move the investment conclusion "
                             "on its own; it is still subtracted from FCFF at "
                             "full value by the pipeline."),
        potential_valuation_impact=ValuationImpact.LOW,
        direction=Direction.NEUTRAL, evidence=tuple(ev), formula=formula,
        threshold=(f"no flag: SBC/revenue <= {SBC_TO_REVENUE_MATERIAL:.0%} and "
                   f"SBC/CFO <= {SBC_TO_CFO_MATERIAL:.0%}")), read)


# --------------------------------------------------------------------------- #
# Dimension G - SBC dilution (separate from SBC expense)
# --------------------------------------------------------------------------- #
def _sbc_dilution(shares, sbc) -> Diagnostic:
    dim = "sbc_dilution"
    key = "SBC_DILUTION"
    if len(shares) < 2:
        return Diagnostic(
            key="SBC_DILUTION_DATA_INSUFFICIENT", dimension=dim,
            state=DiagnosticState.INSUFFICIENT_DATA, horizon=Horizon.NOT_ENOUGH_HISTORY,
            fact=("fewer than two periods of diluted weighted-average share "
                  "counts were extracted."),
            diagnostic="share-count growth cannot be measured.",
            interpretation=("SBC_DILUTION_DATA_INSUFFICIENT: dilution is not "
                            "inferred from SBC expense - it needs the share "
                            "counts, which are not available for two periods."),
            valuation_relevance=("cannot say whether SBC is being offset by "
                                 "buybacks or is flowing through to the share "
                                 "count."),
            potential_valuation_impact=ValuationImpact.UNKNOWN,
            evidence=tuple(_evidence(shares[p], f"diluted shares {p}")
                           for p in sorted(shares)),
            formula="year-over-year growth in diluted weighted-average shares")

    periods = sorted(shares)
    latest, prev = periods[-1], periods[-2]
    g = ((shares[latest].value - shares[prev].value) / shares[prev].value
         if shares[prev].value else None)
    read = _read_series({p: shares[p].value for p in periods})
    ev = [_evidence(shares[p], f"diluted shares {p}") for p in periods]
    ev.append(_ratio_evidence(f"share growth {latest}", g,
                              [shares[latest].name, shares[prev].name], unit="pct"))
    series_txt = ", ".join(f"{p}={_fmt(shares[p].value, 0)}" for p in periods)
    fact = (f"{latest}: diluted weighted-average shares {_fmt(shares[prev].value, 0)} "
            f"-> {_fmt(shares[latest].value, 0)} {shares[latest].unit} "
            f"({_pct(g)}). Series: {series_txt}.")
    diag = (f"diluted share count changed {_pct(g)} year over year"
            + (f"; the series is {read.monotonic}" if read.monotonic else "") + ".")
    # this is an observation, not a pass/fail; state ASSESSED with impact tied to size
    rising = g is not None and g > 0.0
    impact = (ValuationImpact.MEDIUM if g is not None and abs(g) > 0.02
              else ValuationImpact.LOW)
    return _apply_confidence(Diagnostic(
        key=key, dimension=dim, state=DiagnosticState.ASSESSED_NO_ISSUE,
        horizon=read.horizon, fact=fact, diagnostic=diag,
        interpretation=("the diluted share count is "
                        + ("rising, so equity compensation is reaching the share "
                           "base and is not being fully offset by buybacks"
                           if rising else
                           "flat or falling, consistent with buybacks offsetting "
                           "equity issuance") + " over the periods disclosed. SBC "
                        "expense and this share-count change are DIFFERENT "
                        "quantities and are reported separately."),
        valuation_relevance=("if a scenario adds SBC back to FCFF, it must model "
                             f"roughly this rate of dilution ({_pct(g)} in "
                             f"{latest}) instead. The pipeline's base case does "
                             "the opposite - subtracts SBC, holds shares flat - "
                             "and doing both would double-count."),
        potential_valuation_impact=impact,
        direction=Direction.OVERSTATES_ECONOMIC_CASH if rising else Direction.NEUTRAL,
        evidence=tuple(ev),
        formula="year-over-year growth in diluted weighted-average shares",
        threshold="descriptive: >2% p.a. treated as MEDIUM potential impact, else LOW"), read)


# --------------------------------------------------------------------------- #
# Dimension H - one-off items (non-cash adjustments vs supplied cash one-offs)
# --------------------------------------------------------------------------- #
_NON_CASH_MARKERS = ("deferred income tax", "deferred tax", "unrealized", "unrealised",
                     "mark-to-market", "fair value adjustment", "impairment",
                     "write-down", "write-off", "revaluation",
                     "gain on sale", "loss on sale", "gain on divest", "loss on divest",
                     "gain from", "loss from")


def _one_off_items(facts, ni, periods, cash_one_offs: tuple[CashOneOff, ...]) -> tuple[Diagnostic, Diagnostic]:
    dim = "one_off_items"

    # H1 - large non-cash earnings adjustments, read from the reconciliation
    latest = max(periods) if periods else None
    nc_lines = []
    if latest is not None:
        for f in facts:
            if getattr(f, "period", None) != latest:
                continue
            src = getattr(f, "source", None)
            if not src or src.target_key != "cash_flows":
                continue
            if any(m in f.name.lower() for m in _NON_CASH_MARKERS):
                nc_lines.append(f)
    nc_lines.sort(key=lambda f: abs(f.value), reverse=True)   # material first

    if latest is None or not nc_lines or latest not in ni or abs(ni[latest].value) < 1e-6:
        non_cash = _insufficient(
            "LARGE_NON_CASH_EARNINGS_ADJUSTMENTS", dim,
            "no non-cash reconciliation lines matched, or net income is ~0 for "
            "the latest period.")
    else:
        nc_total = sum(f.value for f in nc_lines)
        share = nc_total / abs(ni[latest].value)
        ev = [_evidence(f, f"non-cash: {f.name}") for f in nc_lines]
        ev.append(_evidence(ni[latest], f"net income {latest}"))
        ev.append(_ratio_evidence("non-cash adjustments / |NI|", share,
                                  [f.name for f in nc_lines] + [ni[latest].name],
                                  period=latest))
        biggest = max(nc_lines, key=lambda f: abs(f.value))
        fact = (f"{latest}: reconciliation non-cash items sum to "
                f"{_fmt(nc_total, 0)} {ni[latest].unit}, {_pct(share)} of net "
                f"income. Largest: {biggest.name} {_fmt(biggest.value, 0)}.")
        # per-line horizon: is the biggest line itself a single-year outlier?
        big_series = _series(facts, *[t for t in _NON_CASH_MARKERS
                                      if t in biggest.name.lower()][:1])[0]
        big_read = _read_series({p: v.value for p, v in big_series.items()})
        material = abs(share) > MATERIAL_DEVIATION
        if material:
            non_cash = Diagnostic(
                key="LARGE_NON_CASH_EARNINGS_ADJUSTMENTS", dimension=dim,
                state=DiagnosticState.FLAGGED,
                horizon=big_read.horizon or Horizon.LATEST_PERIOD, fact=fact,
                diagnostic=(f"non-cash items reverse {_pct(share)} of reported net "
                            f"income on the way to CFO. The largest, {biggest.name}, "
                            + (f"is a single-year outlier "
                               f"({_fmt(big_read.latest,0)} vs prior median "
                               f"{_fmt(big_read.prior_median,0)})"
                               if big_read.horizon is Horizon.SINGLE_YEAR_ANOMALY
                               else "moves with net income across the series") + "."),
                interpretation=("reported net income for the period contains large "
                                "non-cash elements (deferred taxes, unrealised "
                                "marks, impairments). These are accounting "
                                "recognition events; CFO already excludes them. "
                                "This says nothing about a cash one-off - see the "
                                "separate cash diagnostic."),
                valuation_relevance=("net income is a poor anchor for this period; "
                                     "a valuation should lean on CFO/FCFF, which "
                                     "the pipeline does. If any of these non-cash "
                                     "items also distorted the effective tax rate, "
                                     "that is handled by the tax-rate override."),
                potential_valuation_impact=ValuationImpact.HIGH,
                direction=Direction.NEUTRAL,   # affects NI, not the cash the DCF uses
                evidence=tuple(ev),
                formula="sum of reconciliation non-cash lines / |NI|, latest period",
                threshold=f"flag when |non-cash / NI| > {MATERIAL_DEVIATION:.0%}")
        else:
            non_cash = Diagnostic(
                key="LARGE_NON_CASH_EARNINGS_ADJUSTMENTS", dimension=dim,
                state=DiagnosticState.ASSESSED_NO_ISSUE, horizon=Horizon.LATEST_PERIOD,
                fact=fact,
                diagnostic=(f"non-cash reconciliation items are {_pct(share)} of "
                            "net income - not a dominant share."),
                interpretation="reported earnings are not heavily non-cash this period.",
                valuation_relevance="net income and cash are not far apart on "
                                    "non-cash grounds for this period.",
                potential_valuation_impact=ValuationImpact.LOW,
                evidence=tuple(ev),
                formula="sum of reconciliation non-cash lines / |NI|, latest period",
                threshold=f"no flag: |non-cash / NI| <= {MATERIAL_DEVIATION:.0%}")

    # H2 - actual cash one-offs: ONLY from supplied evidence
    if cash_one_offs:
        ev = [Evidence(label=f"cash one-off {c.fiscal_year}: {c.description}",
                       value=c.amount, unit=c.unit, period=c.fiscal_year,
                       quote="", source_ref=c.source) for c in cash_one_offs]
        total = sum(c.amount for c in cash_one_offs)
        cash = Diagnostic(
            key="DOCUMENTED_CASH_ONE_OFF", dimension=dim,
            state=DiagnosticState.FLAGGED, horizon=Horizon.SINGLE_YEAR_ANOMALY,
            fact=(f"{len(cash_one_offs)} cash one-off item(s) supplied as analyst "
                  f"evidence, totalling {_fmt(total, 0)} {cash_one_offs[0].unit}: "
                  + "; ".join(f"{c.fiscal_year} {c.description} {_fmt(c.amount, 0)}"
                              for c in cash_one_offs) + "."),
            diagnostic=("these are cash movements the analyst has identified as "
                        "non-recurring, with a source. They are NOT visible in the "
                        "reconciliation captions and were not discovered by this "
                        "module."),
            interpretation=("the affected period's CFO includes a cash amount that "
                            "is not expected to recur."),
            valuation_relevance=("if a one-off cash outflow depressed the anchor "
                                 "year's CFO, reported FCFF understates run-rate "
                                 "cash, and vice versa. This module does NOT adjust "
                                 "CFO - it records the evidence for a scenario."),
            potential_valuation_impact=ValuationImpact.MEDIUM,
            direction=Direction.NEUTRAL, evidence=tuple(ev),
            formula="none - supplied evidence, reported as-is",
            threshold="n/a")
    else:
        cash = Diagnostic(
            key="NO_CASH_ONE_OFF_IDENTIFIED", dimension=dim,
            state=DiagnosticState.INSUFFICIENT_DATA, horizon=Horizon.LATEST_PERIOD,
            fact="no cash one-off evidence was supplied for this filing.",
            diagnostic=("NO_CASH_ONE_OFF_IDENTIFIED. A one-time cash payment "
                        "(a settlement, cash restructuring costs) does not appear "
                        "as its own reconciliation line and cannot be found from "
                        "the cash flow statement - measured across the corpus in "
                        "cfo_normalization.py."),
            interpretation=("this is NOT NO_CASH_ONE_OFF_EXISTS. Absence of "
                            "supplied evidence is absence of evidence, not a clean "
                            "cash flow statement."),
            valuation_relevance=("unquantified. If the analyst knows of a one-off "
                                 "cash item, it enters as supplied evidence, the "
                                 "same shape as a net-debt policy override."),
            potential_valuation_impact=ValuationImpact.UNKNOWN,
            direction=Direction.NEUTRAL, evidence=(),
            formula="n/a", threshold="n/a")
    return non_cash, cash


# --------------------------------------------------------------------------- #
# Helpers and orchestration
# --------------------------------------------------------------------------- #
def _insufficient(key, dimension, why) -> Diagnostic:
    return Diagnostic(
        key=key, dimension=dimension, state=DiagnosticState.INSUFFICIENT_DATA,
        horizon=None,
        fact=f"insufficient data: {why}",
        diagnostic="not computed.",
        interpretation="INSUFFICIENT_DATA - not read as ASSESSED_NO_ISSUE.",
        valuation_relevance="none available from this dimension.",
        potential_valuation_impact=ValuationImpact.UNKNOWN,
        evidence=(), formula="", threshold="")


# Which accounting RELATIONSHIP each convergence-eligible flag measures.
# Flags in one family are different views of ONE underlying relationship
# (the NI<->CFO reconciliation, or the equity-compensation structure), not
# independent signals. Convergence counts distinct families.
_CONVERGENCE_FAMILY = {
    "CASH_EARNINGS_DIVERGENCE": "cash_vs_earnings",
    "HIGH_ACCRUAL_COMPONENT": "cash_vs_earnings",
    "WORKING_CAPITAL_DEPENDENT_CFO": "cash_vs_earnings",
    "ONE_YEAR_WORKING_CAPITAL_SWING": "cash_vs_earnings",
    "LARGE_NON_CASH_EARNINGS_ADJUSTMENTS": "cash_vs_earnings",
    "REVENUE_CASH_DIVERGENCE": "cash_vs_earnings",
    "HIGH_SBC": "equity_compensation",
    "SBC_DILUTION": "equity_compensation",
    "HIGH_CAPITAL_INTENSITY": "capital_intensity",
    "DOCUMENTED_CASH_ONE_OFF": "one_off_cash",
}

CONVERGENCE_MIN_FAMILIES = 2


def _converging(diagnostics: list[Diagnostic]) -> ConvergingRisks | None:
    """Qualitative synthesis. Reports convergence only when adverse flags span
    at least CONVERGENCE_MIN_FAMILIES INDEPENDENT accounting relationships -
    never on multiple measurements of one relationship (P4.6 F1). The summary
    groups the flags by family and discloses how many rest on single-period
    (LIMITED) evidence (P4.6 F2). It is a sentence, not a score, and does not
    touch valuation.
    """
    weighty = [d for d in diagnostics
               if d.flagged
               and d.potential_valuation_impact in (ValuationImpact.MEDIUM,
                                                    ValuationImpact.HIGH)
               and d.direction is Direction.OVERSTATES_ECONOMIC_CASH]
    if len(weighty) < CONVERGENCE_MIN_FLAGS:
        return None

    families: dict[str, list[str]] = {}
    for d in weighty:
        fam = _CONVERGENCE_FAMILY.get(d.key, f"ungrouped:{d.key}")
        families.setdefault(fam, []).append(d.key)

    if len(families) < CONVERGENCE_MIN_FAMILIES:
        # Enough flags, but they all measure ONE relationship. Not convergence.
        return None

    keys = tuple(d.key for d in weighty)
    limited = sum(1 for d in weighty if d.confidence is Confidence.LIMITED)
    fam_render = "; ".join(
        f"{fam} ({', '.join(ks)})" for fam, ks in sorted(families.items()))
    limited_note = (
        f" {limited} of {len(weighty)} contributing flags rest on single-period "
        "(LIMITED-confidence) evidence; persistence is not established for those."
        if limited else "")
    return ConvergingRisks(
        present=True, direction=Direction.OVERSTATES_ECONOMIC_CASH,
        diagnostics=keys,
        families={k: tuple(v) for k, v in families.items()},
        limited_flag_count=limited,
        summary=(f"CONVERGING_ACCOUNTING_QUALITY_RISKS: {len(weighty)} adverse "
                 f"flags across {len(families)} INDEPENDENT accounting "
                 f"dimensions ({fam_render}) point the same way - reported "
                 "earnings or cash flow likely overstates sustainable economic "
                 "cash generation. Flags within one dimension are different "
                 "measurements of the same relationship, not independent "
                 f"signals.{limited_note} This is a qualitative synthesis, not "
                 "a score, and it does not modify the valuation."))


def assess_accounting_quality(
    facts: list,
    fcff_by_period: dict[str, float] | None = None,
    cash_one_offs: tuple[CashOneOff, ...] = (),
    doc_id: str = "",
) -> AccountingQualityReport:
    """Run every dimension over the verified facts. Deterministic, diagnostic
    only. ``fcff_by_period`` is the pipeline's single FCFF definition
    (bridge._per_period_fcff), passed in rather than recomputed. ``cash_one_offs``
    is analyst-supplied evidence of non-recurring cash items - never inferred.
    """
    # Fact wording differs across filers, so each series is resolved by the
    # same tolerant-substring approach assumptions.py uses, not by one exact
    # caption. Measured: Uber writes "Net cash provided by operating
    # activities"; Lyft writes "Net cash provided by (used in) operating
    # activities" - an exact match on the first misses the second entirely.
    ni = _first_nonempty(
        _series(facts, "net income", "including")[0],       # Uber: total w/ NCI
        _series(facts, "total net income")[0],              # explicitly tagged total
        _series(facts, "net income", exclude=("attributable", "adjustments",
                                              "other", "before", "per share",
                                              "reconcile", "including"))[0],
        _series(facts, "net income", "attributable")[0],    # last resort
    )
    cfo, cfo_clash = _series(facts, "net cash", "operating activities")
    revenue, rev_clash = _series(facts, "total revenue", target_key="operations")
    capex, capex_clash = _series(facts, "property and equipment",
                                 exclude=("stock-based", "share-based"))
    sbc, sbc_clash = _series(facts, "stock-based compensation",
                             exclude=("capitalized",), target_key="cash_flows")
    _, ni_clash = _series(facts, "net income", "including")
    shares, _ = _series(facts, "diluted", "shares outstanding")
    if not shares:
        shares, _ = _series(facts, "diluted weighted-average shares")

    # P4.6 F5: conflicting facts (same period, different value) are detected
    # by _series but were being discarded first-seen-wins. A metric with a
    # clash forces every diagnostic that consumes it to INSUFFICIENT_DATA.
    conflicted = {
        name for name, cl in (("net_income", ni_clash), ("cfo", cfo_clash),
                              ("revenue", rev_clash), ("capex", capex_clash),
                              ("sbc", sbc_clash)) if cl}
    # P4.6 F4: a ratio across two monetary series in different unit scales
    # is wrong by that factor (ISSUES.md #15). Detect once, up front.
    scale_reason = _scale_conflict(ni, cfo, revenue, capex, sbc)

    periods = tuple(sorted(
        set(ni) | set(cfo) | set(revenue) | set(capex) | set(sbc)))

    diagnostics: list[Diagnostic] = []
    diagnostics.append(_earnings_vs_cash(ni, cfo))
    diagnostics.append(_accruals(ni, cfo, revenue))
    diagnostics.append(_working_capital(facts, cfo, periods))
    diagnostics.append(_revenue_quality(facts, revenue, cfo))
    intensity, maint = _capital_intensity(capex, cfo, revenue)
    diagnostics.append(intensity)
    diagnostics.append(maint)
    diagnostics.append(_sbc_materiality(sbc, revenue, cfo, ni))
    diagnostics.append(_sbc_dilution(shares, sbc))
    non_cash, cash = _one_off_items(facts, ni, periods, cash_one_offs)
    diagnostics.append(non_cash)
    diagnostics.append(cash)

    # P4.6 F4/F5 - fail closed on conflicting inputs or mismatched unit
    # scales. Cross-metric diagnostics are forced to INSUFFICIENT_DATA rather
    # than reporting a ratio built on ambiguous or mis-scaled inputs.
    _DIM_INPUTS = {
        "earnings_vs_cash": {"net_income", "cfo"},
        "accruals": {"net_income", "cfo", "revenue"},
        "capital_intensity": {"capex", "cfo", "revenue"},
        "sbc": {"sbc", "revenue", "cfo", "net_income"},
        "one_off_items": {"net_income"},
    }
    _CROSS_METRIC = {"CASH_EARNINGS_DIVERGENCE", "HIGH_ACCRUAL_COMPONENT",
                     "HIGH_CAPITAL_INTENSITY", "HIGH_SBC",
                     "LARGE_NON_CASH_EARNINGS_ADJUSTMENTS"}
    if conflicted or scale_reason:
        fixed: list[Diagnostic] = []
        for d in diagnostics:
            hit_conflict = conflicted & _DIM_INPUTS.get(d.dimension, set())
            hit_scale = scale_reason and d.key in _CROSS_METRIC
            if (hit_conflict or hit_scale) and d.state in (
                DiagnosticState.FLAGGED, DiagnosticState.ASSESSED_NO_ISSUE):
                why = (f"conflicting source facts for {', '.join(sorted(hit_conflict))}"
                       if hit_conflict else scale_reason)
                fixed.append(replace(
                    d, state=DiagnosticState.INSUFFICIENT_DATA,
                    potential_valuation_impact=ValuationImpact.UNKNOWN,
                    confidence=Confidence.LIMITED,
                    interpretation=("INSUFFICIENT_DATA (P4.6 fail-closed): the "
                                    "inputs to this diagnostic are not "
                                    "trustworthy - " + why + ". No ratio is "
                                    "reported."),
                    limitation=(d.limitation + " " if d.limitation else "") + why))
            else:
                fixed.append(d)
        diagnostics = fixed

    assessed = any(d.state in (DiagnosticState.FLAGGED,
                               DiagnosticState.ASSESSED_NO_ISSUE)
                   for d in diagnostics)

    notes: list[str] = []
    if conflicted:
        notes.append("CONFLICTING SOURCE FACTS for: " + ", ".join(sorted(conflicted))
                     + " (same period, different value). Affected diagnostics "
                     "forced to INSUFFICIENT_DATA - the conflict is not resolved "
                     "by picking one value.")
    if scale_reason:
        notes.append("UNIT-SCALE MISMATCH: " + scale_reason
                     + ". Cross-metric diagnostics forced to INSUFFICIENT_DATA.")
    if fcff_by_period and len(fcff_by_period) >= 2:
        notes.append(
            "FCFF-quality drivers (no single score): reported FCFF by period "
            + ", ".join(f"{p}={v:,.0f}" for p, v in sorted(fcff_by_period.items()))
            + ". Confidence in the latest figure as a run rate is a function of "
            "the flags above - earnings/cash divergence, working-capital "
            "dependence, SBC treatment, non-cash adjustments - not a number this "
            "module produces. The starting-point sensitivity lives in "
            "historical_fcff.")
    else:
        notes.append(
            "FCFF-quality: fewer than two reconstructed FCFF periods available, "
            "so no multi-year FCFF driver commentary. Not read as 'FCFF is "
            "reliable'.")

    n_ins = sum(1 for d in diagnostics
                if d.state is DiagnosticState.INSUFFICIENT_DATA)
    if n_ins:
        notes.append(f"{n_ins} diagnostic(s) INSUFFICIENT_DATA - listed explicitly, "
                     "never collapsed into a pass.")

    return AccountingQualityReport(
        doc_id=doc_id, assessed=assessed, diagnostics=tuple(diagnostics),
        converging_risks=_converging(diagnostics), periods=periods,
        notes=tuple(notes),
    )
