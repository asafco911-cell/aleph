"""Historical FCFF series, starting-point scenarios, and anchor sensitivity.

ISSUES.md #29 in one sentence: a single fiscal year's cash flow can dominate a
ten-year DCF even when every extracted figure is correct. UBER_FY2024 and
UBER_FY2025 value the same company at the same price on the same day at $77.08
and $119.95.

WHAT THIS MODULE DOES NOT DO. It does not pick an anchor. It does not replace
FCFF with an average. #29 already measured that averaging makes the
instability WORSE on this corpus - the latest-period basis moved +56% between
two Uber filings while a three-year average moved +151%, because the window's
composition changed more than its newest point did. A module that quietly
substituted a median would be trading a visible dependency for an invisible
one.

TWO UNCERTAINTIES, KEPT APART, because combining them into one number destroys
the only useful thing about either:

  ACCOUNTING NORMALISATION UNCERTAINTY - is reported FCFF economically
  representative at all? Answered by cfo_normalization: coverage, uncertain
  weight, NORMALIZATION_INSUFFICIENT.

  HISTORICAL ANCHOR UNCERTAINTY - even with every year's figure correct,
  which year should anchor the DCF? Answered here, by valuing under each
  starting point and reporting the spread.

A filing can be perfect on the first and hopeless on the second. Uber is.

VOCABULARY IS LOAD-BEARING. Only `normalised_fcff` carries the word
"normalised", and it means the output of cfo_normalization for that period.
`historical_mean_fcff` and `historical_median_fcff` are statistics over a
series. An arithmetic mean of four years is not an economic normalisation and
is never labelled as one - that conflation is the failure this whole
workstream exists to prevent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from statistics import mean, median

from .dcf_engine import DCFConsistencyError, DCFInputs, run_dcf

__all__ = [
    "Comparability",
    "Flag",
    "MATERIAL_DEVIATION",
    "REGIME_TIGHTNESS",
    "REGIME_JUMP",
    "HIGH_ANCHOR_SENSITIVITY",
    "FCFFPeriod",
    "ComparabilityEvent",
    "StartingPoint",
    "ScenarioValuation",
    "AnchorSensitivity",
    "HistoricalFCFF",
    "build_series",
    "value_under_scenarios",
]


class Comparability(str, Enum):
    """Whether the periods can be compared at all.

    LOW is set only from SUPPLIED evidence of a structural event, never
    inferred from the numbers: a series can jump because the business changed
    or because one year was unusual, and those look identical in a list of
    four figures. Inferring an acquisition from a jump would be exactly the
    fabrication this project refuses.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class Flag(str, Enum):
    """Deterministic diagnostics. None of them changes a number."""

    LATEST_YEAR_ABNORMALITY = "LATEST_YEAR_ABNORMALITY"
    HISTORICAL_TREND_PRESENT = "HISTORICAL_TREND_PRESENT"
    POTENTIAL_BUSINESS_REGIME_CHANGE = "POTENTIAL_BUSINESS_REGIME_CHANGE"
    HISTORICAL_COMPARABILITY_LOW = "HISTORICAL_COMPARABILITY_LOW"
    HISTORICAL_DATA_INSUFFICIENT = "HISTORICAL_DATA_INSUFFICIENT"
    HIGH_ANCHOR_SENSITIVITY = "HIGH_ANCHOR_SENSITIVITY"
    VALUATION_METHOD_LIMITATION = "VALUATION_METHOD_LIMITATION"
    MIXED_SIGN_HISTORY = "MIXED_SIGN_HISTORY"
    NEGATIVE_CENTRAL_TENDENCY = "NEGATIVE_CENTRAL_TENDENCY"


# Latest period more than this far from the prior median is worth naming.
# A convention, stated as one: it is the threshold at which a reader would
# want to look, not a level at which anything becomes true.
MATERIAL_DEVIATION = 0.25

# A regime change is claimed only when the prior years sit inside a tight
# band AND the latest breaks far above it. Both conditions, because either
# alone describes an ordinary volatile series.
REGIME_TIGHTNESS = 0.20
REGIME_JUMP = 1.00

# Valuations across starting points spanning more than this share of their own
# midpoint mean the anchor choice, not the business, is driving the answer.
HIGH_ANCHOR_SENSITIVITY = 0.50


@dataclass(frozen=True)
class FCFFPeriod:
    """One fiscal year, with reported and normalised figures kept apart."""

    fiscal_year: str
    reported_cfo: float
    reported_capex: float
    reported_fcff: float
    normalised_cfo: float | None = None
    normalised_fcff: float | None = None
    normalisation_status: str = "not_run"
    normalisation_coverage: str = "unknown"
    unit: str = "USD millions"
    doc_id: str = ""
    provenance: tuple[str, ...] = ()

    @property
    def anchor_fcff(self) -> float:
        """The figure this period contributes: normalised if it exists."""
        return self.reported_fcff if self.normalised_fcff is None \
            else self.normalised_fcff


@dataclass(frozen=True)
class ComparabilityEvent:
    """Supplied evidence that two periods are not comparable.

    Never inferred. An acquisition, a divestiture, a discontinued operation or
    an accounting-standard adoption is a fact about the filing, and the series
    of numbers cannot distinguish one from a good year.
    """

    fiscal_year: str
    kind: str
    description: str
    source: str = ""


@dataclass(frozen=True)
class StartingPoint:
    """One candidate anchor, with what it is and why someone would choose it."""

    name: str
    fcff: float
    basis: str
    rationale: str


@dataclass(frozen=True)
class ScenarioValuation:
    starting_point: StartingPoint
    value_per_share: float | None
    rejected: str = ""


@dataclass(frozen=True)
class AnchorSensitivity:
    """How much the answer depends on which year anchors it.

    Deliberately NOT called a confidence interval. Nothing here is a
    probability: these are the values the model produces under each anchor an
    analyst might defensibly choose, and the spread between them is a
    statement about the choice, not about the business.
    """

    minimum_value: float | None
    maximum_value: float | None
    median_value: float | None
    mean_value: float | None
    absolute_range: float | None
    percentage_range: float | None
    scenarios: tuple[ScenarioValuation, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class HistoricalFCFF:
    """The series, its statistics, and every diagnostic - no chosen answer."""

    periods: tuple[FCFFPeriod, ...]
    unit: str
    latest_reported_fcff: float | None = None
    latest_normalised_fcff: float | None = None
    historical_mean_fcff: float | None = None
    historical_median_fcff: float | None = None
    historical_min_fcff: float | None = None
    historical_max_fcff: float | None = None
    latest_deviation_from_median: float | None = None
    comparability: Comparability = Comparability.UNKNOWN
    comparability_events: tuple[ComparabilityEvent, ...] = ()
    flags: tuple[Flag, ...] = ()
    sufficient: bool = True
    reason: str = ""
    notes: tuple[str, ...] = ()

    @property
    def series(self) -> dict[str, float]:
        return {p.fiscal_year: p.anchor_fcff for p in self.periods}

    def starting_points(self) -> tuple[StartingPoint, ...]:
        """Scenarios A, B and C. D is deliberately absent - see the notes."""
        points: list[StartingPoint] = []
        if self.latest_normalised_fcff is not None:
            points.append(StartingPoint(
                "latest_normalized", self.latest_normalised_fcff,
                "latest period, after cfo_normalization",
                "the most recent evidence of what the business generates. "
                "Also the most exposed to one year being unusual."))
        if self.historical_median_fcff is not None:
            points.append(StartingPoint(
                "historical_median", self.historical_median_fcff,
                "median of the series (a STATISTIC, not a normalisation)",
                "robust to one outlying year. Economically wrong if the "
                "business changed level, because it anchors on a state the "
                "company has left."))
        if self.historical_mean_fcff is not None:
            points.append(StartingPoint(
                "historical_mean", self.historical_mean_fcff,
                "arithmetic mean of the series (a STATISTIC)",
                "uses every observation. Fully exposed to the outlier the "
                "median resists, and to the window's composition - #29 "
                "measured a three-year mean moving +151% between two Uber "
                "filings against +56% for the latest period."))
        return tuple(points)


def _flags_from_series(
    values: list[float], latest: float, prior: list[float],
    deviation: float | None, events: tuple[ComparabilityEvent, ...],
) -> tuple[list[Flag], list[str]]:
    flags: list[Flag] = []
    notes: list[str] = []

    if deviation is not None and abs(deviation) > MATERIAL_DEVIATION:
        flags.append(Flag.LATEST_YEAR_ABNORMALITY)
        notes.append(
            f"latest period is {deviation:+.1%} from the prior median. "
            "A diagnostic: nothing is adjusted on this basis.")

    if len(values) >= 3:
        rising = all(b > a for a, b in zip(values, values[1:]))
        falling = all(b < a for a, b in zip(values, values[1:]))
        if rising or falling:
            flags.append(Flag.HISTORICAL_TREND_PRESENT)
            notes.append(
                f"the series is monotonically {'rising' if rising else 'falling'} "
                "across every period. A median over a trend anchors on a state "
                "the business has passed through. NOT extrapolated into growth: "
                "that is a separate assumption with its own evidence.")

    if len(prior) >= 3 and all(p != 0 for p in prior):
        band = (max(prior) - min(prior)) / abs(median(prior))
        jump = (latest - median(prior)) / abs(median(prior))
        if band <= REGIME_TIGHTNESS and jump >= REGIME_JUMP:
            flags.append(Flag.POTENTIAL_BUSINESS_REGIME_CHANGE)
            notes.append(
                f"prior periods sit within a {band:.0%} band and the latest is "
                f"{jump:+.0%} above their median. That SHAPE is consistent with "
                "a level shift, and equally consistent with one exceptional "
                "year - the numbers cannot tell them apart. Supply a "
                "ComparabilityEvent if a structural change is documented; this "
                "flag is a prompt to look, never a finding.")

    if any(v > 0 for v in values) and any(v < 0 for v in values):
        flags.append(Flag.MIXED_SIGN_HISTORY)
        notes.append(
            "the series changes sign. A central tendency across a sign change "
            "is arithmetic, not an economic anchor.")

    if events:
        flags.append(Flag.HISTORICAL_COMPARABILITY_LOW)
        notes.append(
            f"{len(events)} structural event(s) supplied: "
            + "; ".join(f"{e.fiscal_year} {e.kind}" for e in events)
            + ". Periods either side of these are not measuring the same "
            "business, and no statistic over them repairs that.")

    return flags, notes


def build_series(
    periods: list[FCFFPeriod],
    comparability_events: tuple[ComparabilityEvent, ...] = (),
    minimum_periods: int = 3,
) -> HistoricalFCFF:
    """Assemble the series and every diagnostic. Chooses nothing.

    Fewer than ``minimum_periods`` is HISTORICAL_DATA_INSUFFICIENT: no
    statistics are reported, because a median over two points is a midpoint
    and a mean over two is the same number wearing a different name. Missing
    years are never estimated.
    """
    if not periods:
        return HistoricalFCFF(
            periods=(), unit="", sufficient=False,
            flags=(Flag.HISTORICAL_DATA_INSUFFICIENT,),
            reason="HISTORICAL_DATA_INSUFFICIENT: no periods supplied.")

    ordered = tuple(sorted(periods, key=lambda p: p.fiscal_year))
    unit = ordered[-1].unit

    units = {p.unit for p in ordered}
    if len(units) > 1:
        return HistoricalFCFF(
            periods=ordered, unit=unit, sufficient=False,
            flags=(Flag.HISTORICAL_DATA_INSUFFICIENT,),
            reason=(f"periods do not share one unit: {sorted(units)}. A series "
                    "mixing scales is not a series."))

    values = [p.anchor_fcff for p in ordered]
    latest_period = ordered[-1]
    prior = values[:-1]

    if len(ordered) < minimum_periods:
        return HistoricalFCFF(
            periods=ordered, unit=unit,
            latest_reported_fcff=latest_period.reported_fcff,
            latest_normalised_fcff=latest_period.normalised_fcff,
            comparability=Comparability.UNKNOWN,
            comparability_events=comparability_events,
            flags=(Flag.HISTORICAL_DATA_INSUFFICIENT,), sufficient=False,
            reason=(f"HISTORICAL_DATA_INSUFFICIENT: {len(ordered)} period(s), "
                    f"minimum {minimum_periods}. Statistics over fewer are not "
                    "reported and missing years are not estimated."))

    hist_median = median(values)
    hist_mean = mean(values)
    deviation = ((values[-1] - median(prior)) / abs(median(prior))
                 if prior and median(prior) != 0 else None)

    flags, notes = _flags_from_series(
        values, values[-1], prior, deviation, comparability_events)

    if hist_median < 0 or hist_mean < 0:
        flags.append(Flag.NEGATIVE_CENTRAL_TENDENCY)
        flags.append(Flag.VALUATION_METHOD_LIMITATION)
        notes.append(
            "a central tendency of the series is negative. A perpetuity on a "
            "negative cash flow compounds a loss forever and is not a "
            "valuation. VALUATION_METHOD_LIMITATION propagates to the output; "
            "the method is not silently switched.")

    comparability = (Comparability.LOW if comparability_events
                     else Comparability.UNKNOWN)
    if not comparability_events:
        notes.append(
            "comparability UNKNOWN, not HIGH. Acquisitions, divestitures, "
            "discontinued operations and accounting-standard adoptions are "
            "not detectable from a list of four numbers, and this module does "
            "not guess at them. Absence of supplied events is absence of "
            "evidence.")

    return HistoricalFCFF(
        periods=ordered, unit=unit,
        latest_reported_fcff=latest_period.reported_fcff,
        latest_normalised_fcff=latest_period.normalised_fcff,
        historical_mean_fcff=hist_mean,
        historical_median_fcff=hist_median,
        historical_min_fcff=min(values),
        historical_max_fcff=max(values),
        latest_deviation_from_median=deviation,
        comparability=comparability,
        comparability_events=comparability_events,
        flags=tuple(dict.fromkeys(flags)), sufficient=True,
        notes=tuple(notes),
    )


def value_under_scenarios(
    inputs: DCFInputs, history: HistoricalFCFF,
) -> AnchorSensitivity:
    """Value the filing under every starting point, and report the spread.

    The DCF is untouched: each scenario is run_dcf with only base_cash_flow
    replaced. No scenario is selected, no result is averaged into a headline,
    and a scenario the engine rejects is reported with its guard's message
    rather than dropped.
    """
    scenarios: list[ScenarioValuation] = []
    for point in history.starting_points():
        trial = DCFInputs(
            cash_flow_type=inputs.cash_flow_type,
            base_cash_flow=point.fcff,
            growth_rates=list(inputs.growth_rates),
            terminal_growth=inputs.terminal_growth,
            discount_rate=inputs.discount_rate,
            net_debt=inputs.net_debt,
            shares_outstanding=inputs.shares_outstanding,
            assumptions=[],
        )
        try:
            scenarios.append(ScenarioValuation(
                point, run_dcf(trial).value_per_share))
        except DCFConsistencyError as exc:
            scenarios.append(ScenarioValuation(point, None, str(exc)))

    valued = [s.value_per_share for s in scenarios if s.value_per_share is not None]
    notes: list[str] = []
    if not valued:
        return AnchorSensitivity(None, None, None, None, None, None,
                                 tuple(scenarios),
                                 ("no starting point produced a valuation.",))

    lo, hi = min(valued), max(valued)
    absolute = hi - lo
    midpoint = (hi + lo) / 2
    percentage = absolute / abs(midpoint) if midpoint else None

    if percentage is not None and percentage > HIGH_ANCHOR_SENSITIVITY:
        notes.append(
            f"{Flag.HIGH_ANCHOR_SENSITIVITY.value}: the answer spans "
            f"{percentage:.0%} of its own midpoint across starting points that "
            "are all defensible. The anchor choice, not the business, is the "
            "largest thing in this valuation.")
    notes.append(
        "This is a starting-point sensitivity, not a confidence interval. "
        "Nothing here is a probability - these are the values the model "
        "produces under each anchor an analyst might choose, and no policy "
        "here says which one is right.")

    return AnchorSensitivity(
        minimum_value=lo, maximum_value=hi,
        median_value=median(valued), mean_value=mean(valued),
        absolute_range=absolute, percentage_range=percentage,
        scenarios=tuple(scenarios), notes=tuple(notes),
    )
