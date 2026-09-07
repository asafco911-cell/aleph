"""Decompose reported CFO; separate what accounting says from what economics asks.

TWO DIFFERENT QUESTIONS, and conflating them is this module's history:

  ACCOUNTING NORMALISATION asks: is this line non-cash, or unusual as the
  statement presents it? A cash flow statement answers this itself. The
  reconciliation from net income to CFO exists precisely to strip non-cash
  items out, so by the time you are looking at CFO, accounting normalisation
  has already happened.

  ECONOMIC NORMALISATION asks: is this amount representative of the recurring
  cash-generating power of the business? A cash flow statement does not answer
  this and cannot. Nothing in it is labelled "one-time".

WHAT THIS MODULE CAN AND CANNOT SEE, measured rather than asserted.

Across all six filings, 71 distinct cash-flow captions, ZERO matched a
one-time-cash-cost marker. That is not evidence the filings are clean. It is
structural: a reconciliation caption names an item on the NON-CASH bridge. A
one-time CASH payment - a settlement paid, restructuring cash costs - never
appears as its own reconciliation line. It is either invisible (expensed and
paid in the same year, so no reconciling item exists) or buried inside a
working-capital caption that says only "Accrued expenses and other
liabilities". Searching reconciliation captions for cash distortions is a
category error, and an earlier version of this module made it.

The consequence, stated plainly rather than hidden behind a clean-looking
result: FROM THE CASH FLOW STATEMENT ALONE, THIS MODULE CANNOT IDENTIFY A
ONE-TIME CASH ITEM. It reports that limitation as coverage rather than
implying cleanliness by returning no adjustments. One-time cash items enter
through `analyst_adjustments`, which is an override with a written reason -
the same shape as net_debt, which blocks until a human states a policy.

THE DIRECTIONAL BUG, twice. The first version removed every flagged
adjustment from CFO and reported Uber's FY2024 normalised CFO as 14,688
against 7,137 - a 106% inflation from correct arithmetic. The fix introduced
NON_CASH_REVERSAL but left restructuring and litigation captions in the
removable set, so a "Restructuring charges 400" ADD-BACK - a non-cash accrual
the statement is reversing - was still subtracted, understating CFO by 400.
Both are regression-tested. A reconciliation add-back is never removed from
CFO, whatever it is called.

WHAT ISSUES.md #29 ACTUALLY SHOWS, reconstructed from extracted facts rather
than from its prose. Uber's CFO rose 2,962 (7,137 -> 10,099) and the two
lines that account for it are unrealized gains (+1,929) and deferred income
taxes (+1,248). Both are NON_CASH_REVERSAL. They moved because NET INCOME
moved - FY2024's was inflated by a deferred tax benefit and unrealized gains,
FY2025's was not - and the bridge moved to offset. CFO's level was never
contaminated by them; the bridge was doing its job in both years. What
changed in cash terms is working capital: accrued expenses +637, prepaid
-334, receivables -324. So #29 is a finding about CFO VOLATILITY and about
which year an analyst anchors on - not about an overstated CFO level.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from statistics import median

__all__ = [
    "LineRole",
    "Classification",
    "Coverage",
    "MATERIALITY",
    "UNCERTAIN_BUDGET",
    "AnalystAdjustment",
    "Adjustment",
    "NormalisedCFO",
    "AbnormalityDiagnostics",
    "classify_role",
    "classify_caption",
    "normalise_cfo",
    "abnormality_diagnostics",
]


class LineRole(str, Enum):
    """What a caption IS, before asking what it means.

    An earlier version fed every extracted cash-flow fact to the classifier,
    so "Net cash provided by operating activities", "Net income" and the
    beginning and end of period cash balances were all classified as
    adjustments. They are not adjustments: they are the subtotal, the
    starting point, and two balances. Twenty-eight captions sat in UNCERTAIN
    largely because of this, inflating the very measure used to decide
    whether the normalisation was trustworthy.
    """

    ADJUSTMENT = "adjustment"
    SUBTOTAL = "subtotal"
    STARTING_POINT = "starting_point"
    BALANCE = "balance"


class Classification(str, Enum):
    """What an adjustment is, for the purpose of a forward estimate."""

    RECURRING = "recurring"
    NON_CASH_REVERSAL = "non_cash_reversal"
    WORKING_CAPITAL = "working_capital"
    UNCERTAIN = "uncertain"


class Coverage(str, Enum):
    """How much of reported CFO the module could actually account for.

    Distinguishes three states an earlier version collapsed into one silent
    "no adjustments found":

    HIGH          every material line was placed on the non-cash bridge or in
                  working capital, and the residue is immaterial. Accounting
                  composition is understood. This says NOTHING about whether
                  the year is economically representative.
    MEDIUM        material lines are understood but the unclassified residue
                  is large enough to matter.
    LOW           the unclassified residue is a substantial share of CFO.
    INSUFFICIENT  above the budget: NORMALIZATION_INSUFFICIENT. No normalised
                  figure is returned.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INSUFFICIENT = "insufficient"


MATERIALITY = 0.05
UNCERTAIN_BUDGET = 0.20
_COVERAGE_HIGH = 0.02
_COVERAGE_MEDIUM = 0.10

_SUBTOTAL = ("net cash provided", "net cash used", "net cash from",
             "total adjustments", "net increase", "net decrease",
             "net change in cash")
_STARTING_POINT = ("net income", "net loss")
_BALANCE = ("beginning of period", "end of period", "beginning of year",
            "end of year", "- beginning", "- end")

_NON_CASH_REVERSAL = (
    "deferred income tax", "deferred tax",
    "unrealized", "unrealised", "mark-to-market", "fair value adjustment",
    "impairment", "write-down", "write-off",
    "gain on", "loss on", "gain from", "loss from",
    "divestiture", "disposal", "sale of business",
    "revaluation", "call option", "foreign currency", "equity method",
    "restructuring", "severance", "litigation", "settlement",
    "acquisition-related", "transaction costs",
)

_RECURRING = (
    "depreciation", "amortization", "amortisation",
    "bad debt", "provision for doubtful", "allowance for credit",
    "stock-based compensation", "share-based compensation",
    "non-cash lease", "operating lease right-of-use", "accretion",
)

_WORKING_CAPITAL = (
    "accounts receivable", "accounts payable", "prepaid", "accrued",
    "inventor", "deferred revenue", "other assets", "other liabilities",
    "operating lease liabilit", "insurance reserves", "lease liabilities",
    "funds held", "change in",
)


@dataclass(frozen=True)
class AnalystAdjustment:
    """A one-time CASH item, supplied by a human, never inferred.

    The cash flow statement cannot name these; see the module docstring. An
    analyst who knows a settlement was paid records it here with a reason and
    a source, exactly as net_debt requires a stated policy. ``amount`` is the
    cash effect ON CFO: a payment that reduced CFO is negative, and removing
    it therefore RAISES normalised CFO.
    """

    caption: str
    amount: float
    fiscal_year: str
    reason: str
    source: str = ""


@dataclass(frozen=True)
class Adjustment:
    caption: str
    amount: float
    unit: str
    fiscal_year: str
    role: LineRole
    classification: Classification | None
    reason: str
    quote: str = ""
    doc_id: str = ""


@dataclass(frozen=True)
class NormalisedCFO:
    doc_id: str
    fiscal_year: str
    unit: str
    reported_cfo: float
    normalised_cfo: float | None
    coverage: Coverage
    lines: tuple[Adjustment, ...] = ()
    analyst_adjustments: tuple[AnalystAdjustment, ...] = ()
    unmatched_captions: tuple[str, ...] = ()
    sufficient: bool = True
    reason: str = ""
    notes: tuple[str, ...] = ()

    @property
    def adjustments(self) -> tuple[Adjustment, ...]:
        return tuple(l for l in self.lines if l.role is LineRole.ADJUSTMENT)

    def weight(self, line: Adjustment) -> float:
        if self.reported_cfo == 0:
            return float("inf") if line.amount else 0.0
        return abs(line.amount) / abs(self.reported_cfo)

    def by_classification(self, kind: Classification) -> tuple[Adjustment, ...]:
        return tuple(a for a in self.adjustments if a.classification is kind)

    @property
    def uncertain_weight(self) -> float:
        return sum(self.weight(a)
                   for a in self.by_classification(Classification.UNCERTAIN))

    @property
    def working_capital_total(self) -> float:
        return sum(a.amount
                   for a in self.by_classification(Classification.WORKING_CAPITAL))

    @property
    def removed(self) -> float:
        """Only analyst adjustments move CFO. No reconciliation line does."""
        return sum(a.amount for a in self.analyst_adjustments)


def classify_role(caption: str) -> LineRole:
    """Is this caption an adjustment, a subtotal, the starting point, or a balance?"""
    lowered = caption.lower()
    if any(m in lowered for m in _BALANCE):
        return LineRole.BALANCE
    if any(m in lowered for m in _SUBTOTAL):
        return LineRole.SUBTOTAL
    if any(m in lowered for m in _STARTING_POINT):
        return LineRole.STARTING_POINT
    return LineRole.ADJUSTMENT


def classify_caption(caption: str) -> tuple[Classification, str]:
    """Classify one ADJUSTMENT. Never called on a subtotal or a balance.

    Every branch here describes the NON-CASH BRIDGE or working capital. None
    of them removes anything from CFO, because none of them can: an add-back
    is the statement reversing a non-cash item, and subtracting it puts that
    item back into cash flow. That was the bug, twice.
    """
    lowered = caption.lower()

    for marker in _NON_CASH_REVERSAL:
        if marker in lowered:
            return (
                Classification.NON_CASH_REVERSAL,
                f"names {marker!r}: a non-cash item this line REVERSES out of "
                "net income. CFO is already clean of it, so it is kept. Its "
                "swing between years moves CFO without the level being wrong "
                "(ISSUES.md #29)",
            )

    for marker in _WORKING_CAPITAL:
        if marker in lowered:
            return (
                Classification.WORKING_CAPITAL,
                f"working capital ({marker!r}): real cash, but a level that "
                "swings. Kept in CFO; its weight is reported so a year carried "
                "by a working-capital release is visible",
            )

    for marker in _RECURRING:
        if marker in lowered:
            return (
                Classification.RECURRING,
                f"names {marker!r}: a recurring non-cash charge, kept",
            )

    return (
        Classification.UNCERTAIN,
        "no marker matched. Reported as unknown, never assumed recurring: a "
        "substring list written against a few filers misses the next one's "
        "wording (ISSUES.md #26)",
    )


def _coverage(uncertain_weight: float) -> Coverage:
    if uncertain_weight > UNCERTAIN_BUDGET:
        return Coverage.INSUFFICIENT
    if uncertain_weight <= _COVERAGE_HIGH:
        return Coverage.HIGH
    if uncertain_weight <= _COVERAGE_MEDIUM:
        return Coverage.MEDIUM
    return Coverage.LOW


def normalise_cfo(
    reported_cfo: float,
    reconciliation: dict[str, float],
    fiscal_year: str,
    unit: str = "USD millions",
    doc_id: str = "",
    quotes: dict[str, str] | None = None,
    analyst_adjustments: tuple[AnalystAdjustment, ...] = (),
) -> NormalisedCFO:
    r"""Classify the reconciliation and report normalised CFO with its coverage.

    .. math:: CFO_{norm} = CFO_{reported} - \sum_i A_i

    where :math:`A_i` are ANALYST adjustments only. No reconciliation line is
    ever subtracted - see the module docstring for why that is not a
    conservative choice but the only correct one.

    Subtotals, the starting point and cash balances are separated out by
    ``classify_role`` and never treated as adjustments.
    """
    quotes = quotes or {}
    lines: list[Adjustment] = []
    for caption, amount in reconciliation.items():
        role = classify_role(caption)
        classification, reason = (
            classify_caption(caption) if role is LineRole.ADJUSTMENT
            else (None, f"{role.value}: not an adjustment, excluded from "
                        "classification and from every weight")
        )
        lines.append(Adjustment(
            caption=caption, amount=float(amount), unit=unit,
            fiscal_year=fiscal_year, role=role, classification=classification,
            reason=reason, quote=quotes.get(caption, ""), doc_id=doc_id,
        ))

    draft = NormalisedCFO(
        doc_id=doc_id, fiscal_year=fiscal_year, unit=unit,
        reported_cfo=float(reported_cfo), normalised_cfo=None,
        coverage=Coverage.INSUFFICIENT, lines=tuple(lines),
    )
    uncertain_weight = draft.uncertain_weight
    coverage = _coverage(uncertain_weight)
    unmatched = tuple(a.caption
                      for a in draft.by_classification(Classification.UNCERTAIN))

    if coverage is Coverage.INSUFFICIENT:
        return NormalisedCFO(
            doc_id=doc_id, fiscal_year=fiscal_year, unit=unit,
            reported_cfo=float(reported_cfo), normalised_cfo=None,
            coverage=coverage, lines=tuple(lines),
            analyst_adjustments=tuple(analyst_adjustments),
            unmatched_captions=unmatched, sufficient=False,
            reason=(
                f"NORMALIZATION_INSUFFICIENT: {uncertain_weight:.0%} of reported "
                f"CFO sits in captions this module cannot classify, above the "
                f"{UNCERTAIN_BUDGET:.0%} budget. Missing evidence: what these "
                "lines are and whether they recur. Classify them with an "
                "accounting justification, or record an analyst adjustment; "
                "do not estimate them."
            ),
        )

    removed = sum(a.amount for a in analyst_adjustments)
    normalised = float(reported_cfo) - removed

    notes = [
        "NO reconciliation line is removed from CFO. Every one of them is "
        "either the non-cash bridge, which CFO has already applied, or "
        "working capital, which is real cash. Only analyst adjustments move "
        "this figure.",
        f"normalisation coverage {coverage.value.upper()}: "
        f"{uncertain_weight:.1%} of CFO is unclassified. Coverage describes "
        "ACCOUNTING composition only - it says nothing about whether this "
        "year is economically representative. For that, read the abnormality "
        "diagnostics.",
    ]
    if not analyst_adjustments:
        notes.append(
            "NO_ADJUSTMENT_IDENTIFIED. This is not NO_ADJUSTMENT_REQUIRED. A "
            "one-time cash cost does not appear as a reconciliation caption "
            "and cannot be found here - measured: zero of 71 captions across "
            "six filings name one. Absence of an adjustment is absence of "
            "evidence, not evidence of a clean year."
        )
    wc = draft.working_capital_total
    if wc and reported_cfo:
        notes.append(
            f"working capital contributes {wc:,.0f} {unit}, "
            f"{abs(wc) / abs(reported_cfo):.0%} of reported CFO - real cash, "
            "but a level that swings rather than a run rate."
        )
    return NormalisedCFO(
        doc_id=doc_id, fiscal_year=fiscal_year, unit=unit,
        reported_cfo=float(reported_cfo), normalised_cfo=normalised,
        coverage=coverage, lines=tuple(lines),
        analyst_adjustments=tuple(analyst_adjustments),
        unmatched_captions=unmatched, sufficient=True, notes=tuple(notes),
    )


@dataclass(frozen=True)
class AbnormalityDiagnostics:
    """Is the latest year unusual? A DIAGNOSTIC, never an adjustment.

    Nothing here changes a number. Historical deviation is evidence that the
    anchor year may not be representative; deciding what to do about that is
    the analyst's, and #29 records that averaging makes it worse, not better.
    """

    fiscal_year: str
    latest: float
    history: tuple[float, ...]
    historical_median: float | None
    deviation_from_median: float | None
    is_outside_prior_range: bool
    n_periods: int
    verdict: str


def abnormality_diagnostics(
    series: dict[str, float], latest: str | None = None
) -> AbnormalityDiagnostics:
    """Compare the latest period against its own history.

    Two periods cannot establish a range, so with fewer than three the verdict
    says the history is too short rather than reporting a deviation from a
    median of one observation.
    """
    if not series:
        raise ValueError("series is empty")
    latest = latest or max(series)
    prior = [v for k, v in series.items() if k < latest]
    value = series[latest]

    if len(prior) < 2:
        return AbnormalityDiagnostics(
            fiscal_year=latest, latest=value, history=tuple(prior),
            historical_median=None, deviation_from_median=None,
            is_outside_prior_range=False, n_periods=len(prior),
            verdict=(f"history too short: {len(prior)} prior period(s). Two "
                     "points cannot establish a range, and a median of one "
                     "observation is that observation."),
        )

    centre = median(prior)
    deviation = (value - centre) / abs(centre) if centre else None
    outside = value > max(prior) or value < min(prior)
    parts = [f"latest {value:,.0f} against a prior median of {centre:,.0f}"]
    if deviation is not None:
        parts.append(f"{deviation:+.0%}")
    parts.append("OUTSIDE the prior range" if outside else "inside the prior range")
    parts.append("Diagnostic only: nothing is adjusted on this basis.")
    return AbnormalityDiagnostics(
        fiscal_year=latest, latest=value, history=tuple(prior),
        historical_median=centre, deviation_from_median=deviation,
        is_outside_prior_range=outside, n_periods=len(prior),
        verdict=", ".join(parts[:3]) + ". " + parts[3],
    )
