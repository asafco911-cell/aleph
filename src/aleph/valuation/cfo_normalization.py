"""Decompose reported CFO and separate recurring cash generation from the rest.

ISSUES.md #29 is the problem this exists for. UBER_FY2024 and UBER_FY2025
value the same company, at the same price, on the same day, at $77.08 and
$119.95 - and nearly the whole gap is two lines in one year's CFO
reconciliation: deferred income taxes and unrealized gains on marketable
securities. Both are real entries in a real statement. Neither is operating
cash generation that recurs.

What this module does NOT do:

  It does not decide. Every line is CLASSIFIED, with a reason, and the
  analyst reads the classification. A module that silently removed items it
  disliked would be manufacturing the very thing #29 warns about, in the
  opposite direction.

  It does not estimate. A material line whose recurring nature cannot be
  established from the caption is UNCERTAIN, and enough uncertain weight
  produces NORMALIZATION_INSUFFICIENT rather than a normalised number with a
  caveat attached.

  It does not average. An arithmetic mean of four years is not a
  normalisation - see basis.py, which reports what each starting-point
  METHOD implies and refuses to pick one.

The correction that shaped this module: a first version removed EVERY flagged
adjustment from CFO, non-cash reversals included, and reported Uber's FY2024
normalised CFO as 14,688 against 7,137 reported. A 106% inflation produced by
sound arithmetic - the exact "mathematically correct, economically wrong"
failure this system exists to catch, committed by the module written to catch
it. See Classification.NON_CASH_REVERSAL.

Sign convention: every adjustment is stated as it appears in the
reconciliation. Only POTENTIALLY_NON_RECURRING lines - cash costs that do not
recur - are subtracted to reach normalised CFO. On the six filings available
here that set is empty, so normalised equals reported, and saying so is the
honest output: these filings have volatile CFO, not overstated CFO.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "Classification",
    "MATERIALITY",
    "UNCERTAIN_BUDGET",
    "Adjustment",
    "NormalisedCFO",
    "classify_caption",
    "normalise_cfo",
]


class Classification(str, Enum):
    """What a reconciliation line is, for the purpose of a forward estimate.

    NON_CASH_REVERSAL is the category a first version of this module did not
    have, and its absence made the whole engine directionally wrong. The
    adjustments in a CFO reconciliation exist to STRIP non-cash items out of
    net income. Uber's FY2024 net income carried a one-off deferred tax
    benefit; the -6,027 adjustment removes it, and CFO is already clean of it.
    Treating that adjustment as a contaminant and subtracting it puts the
    non-cash benefit BACK IN - it raised normalised CFO from 7,137 to 14,688,
    a 106% inflation, on a filing whose CFO needed no such correction.

    The line that genuinely contaminates CFO is a CASH item that does not
    recur: a litigation settlement paid, restructuring cash costs. Those are
    POTENTIALLY_NON_RECURRING and are removed. A non-cash reversal is kept,
    because it is the correction, not the error.

    What ISSUES.md #29 measures is the year-over-year CHANGE in these
    reversal lines, which moves CFO because net income moved and the
    adjustment moved to offset it. That is a statement about CFO's
    volatility, not about the level being overstated - and conflating the two
    is how a normalisation engine doubles a company's cash flow.
    """

    RECURRING = "recurring"
    NON_CASH_REVERSAL = "non_cash_reversal"
    POTENTIALLY_NON_RECURRING = "potentially_non_recurring"
    UNCERTAIN = "uncertain"
    NOT_APPLICABLE = "not_applicable"


# A line smaller than this share of reported CFO cannot change the conclusion,
# so its classification does not gate the result. It is still reported.
MATERIALITY = 0.05

# How much CFO may sit in UNCERTAIN lines before the normalisation itself is
# not trustworthy. Above this, the module refuses rather than reporting a
# number whose composition it cannot account for.
UNCERTAIN_BUDGET = 0.20

# Caption fragments, lowercased, matched as substrings. DELIBERATELY not
# exhaustive: ISSUES.md #26 is the standing lesson that a substring list
# written against a few filers misses the next one's wording. Anything not
# matched here becomes UNCERTAIN and is reported by name - the failure mode
# is a loud "I do not know what this is", never a silent "recurring".
_RECURRING = (
    "depreciation", "amortization", "amortisation",
    "bad debt", "provision for doubtful", "allowance for credit",
    "stock-based compensation", "share-based compensation",
    "non-cash lease", "operating lease right-of-use",
    "accretion",
)

# NON-CASH items whose reconciliation line REVERSES them out of net income.
# CFO is already clean of these; removing the adjustment re-introduces them.
# Kept in normalised CFO, and reported, because their year-over-year SWING is
# what makes CFO volatile even when its level is sound (ISSUES.md #29).
_NON_CASH_REVERSAL = (
    "deferred income tax", "deferred tax",
    "unrealized", "unrealised", "mark-to-market", "fair value adjustment",
    "impairment", "write-down", "write-off",
    "gain on", "loss on", "gain from", "loss from",
    "divestiture", "disposal", "sale of business",
    "revaluation", "call option",
    "foreign currency",
    "equity method",
)

# CASH costs that do not recur. These DO contaminate CFO's level, and are the
# only class removed to reach normalised CFO.
_POTENTIALLY_NON_RECURRING = (
    "restructuring", "severance",
    "litigation", "legal settlement", "settlement charge", "settlement payment",
    "acquisition-related", "transaction costs",
    "one-time", "non-recurring",
)

# Working capital: recurring as a category, but its LEVEL swings and a single
# year's swing is not a run rate. Kept separate so its weight is reportable.
_WORKING_CAPITAL = (
    "accounts receivable", "accounts payable", "prepaid",
    "accrued", "inventor", "deferred revenue", "other assets",
    "other liabilities", "operating lease liabilit",
)


@dataclass(frozen=True)
class Adjustment:
    """One reconciliation line, classified, with everything needed to audit it."""

    caption: str
    amount: float
    unit: str
    fiscal_year: str
    classification: Classification
    reason: str
    is_working_capital: bool = False
    quote: str = ""
    doc_id: str = ""

    @property
    def share_of(self) -> float:
        """Placeholder kept out of the dataclass: share is relative to CFO."""
        raise NotImplementedError("use NormalisedCFO.weight(adjustment)")


@dataclass(frozen=True)
class NormalisedCFO:
    """Reported CFO decomposed, with the normalised figure and its confidence.

    ``sufficient`` False means NORMALIZATION_INSUFFICIENT: the module could
    not account for enough of CFO to stand behind the normalised number, and
    ``reason`` says what evidence is missing.
    """

    doc_id: str
    fiscal_year: str
    unit: str
    reported_cfo: float
    normalised_cfo: float | None
    adjustments: tuple[Adjustment, ...] = ()
    unmatched_captions: tuple[str, ...] = ()
    sufficient: bool = True
    reason: str = ""
    notes: tuple[str, ...] = ()

    def weight(self, adjustment: Adjustment) -> float:
        """An adjustment's size as a share of reported CFO."""
        if self.reported_cfo == 0:
            return float("inf") if adjustment.amount else 0.0
        return abs(adjustment.amount) / abs(self.reported_cfo)

    def by_classification(self, kind: Classification) -> tuple[Adjustment, ...]:
        return tuple(a for a in self.adjustments if a.classification is kind)

    @property
    def removed(self) -> float:
        """Total adjustment removed from reported CFO to reach normalised."""
        return sum(a.amount for a in self.by_classification(
            Classification.POTENTIALLY_NON_RECURRING))

    @property
    def uncertain_weight(self) -> float:
        """Share of reported CFO sitting in lines that could not be classified."""
        return sum(self.weight(a)
                   for a in self.by_classification(Classification.UNCERTAIN))


def classify_caption(caption: str) -> tuple[Classification, str, bool]:
    """Return (classification, reason, is_working_capital) for one caption.

    Order matters and is not arbitrary. A cash non-recurring cost is tested
    first, then a non-cash reversal, then working capital, then recurring -
    so "Impairment of amortizable intangibles" is an impairment rather than
    amortisation, and "Restructuring-related asset write-offs" is
    restructuring rather than a write-off. Getting this precedence backwards
    would classify Uber's goodwill impairments as routine depreciation.
    """
    lowered = caption.lower()

    for marker in _POTENTIALLY_NON_RECURRING:
        if marker in lowered:
            return (
                Classification.POTENTIALLY_NON_RECURRING,
                f"caption names {marker!r}: a CASH cost that does not recur, so "
                "it overstates this year's operating cash generation and is "
                "removed to reach normalised CFO",
                False,
            )

    for marker in _NON_CASH_REVERSAL:
        if marker in lowered:
            return (
                Classification.NON_CASH_REVERSAL,
                f"caption names {marker!r}: a non-cash item this line REVERSES "
                "out of net income. CFO is already clean of it, so the "
                "adjustment is kept - subtracting it would put the non-cash "
                "amount back into cash flow. Its swing between years is "
                "reported, because that is what moves CFO (ISSUES.md #29)",
                False,
            )

    for marker in _WORKING_CAPITAL:
        if marker in lowered:
            return (
                Classification.RECURRING,
                f"working capital ({marker!r}): the category recurs, but the "
                "level swings, so its weight is reported separately",
                True,
            )

    for marker in _RECURRING:
        if marker in lowered:
            return (
                Classification.RECURRING,
                f"caption names {marker!r}, a recurring non-cash charge",
                False,
            )

    return (
        Classification.UNCERTAIN,
        "no marker matched this caption. Unmatched is reported as unknown, "
        "never assumed recurring: a substring list written against a few "
        "filers misses the next one's wording (ISSUES.md #26)",
        False,
    )


def normalise_cfo(
    reported_cfo: float,
    reconciliation: dict[str, float],
    fiscal_year: str,
    unit: str = "USD millions",
    doc_id: str = "",
    quotes: dict[str, str] | None = None,
    materiality: float = MATERIALITY,
    uncertain_budget: float = UNCERTAIN_BUDGET,
) -> NormalisedCFO:
    r"""Classify every reconciliation line and report normalised CFO.

    .. math::
        CFO_{norm} = CFO_{reported} - \sum_{i \in \text{non-recurring}} A_i

    ``reconciliation`` maps caption to the adjustment AS PRESENTED in the
    statement - the amount added to (or subtracted from) net income to reach
    CFO. Net income itself must not be included; it is the starting point,
    not an adjustment.

    Refuses, rather than reporting a number, when more than
    ``uncertain_budget`` of reported CFO sits in captions it could not
    classify. That is NORMALIZATION_INSUFFICIENT: the composition of the
    figure is unknown, and a normalised number carrying an unknown remainder
    is exactly the false precision this project exists to avoid.
    """
    quotes = quotes or {}
    adjustments: list[Adjustment] = []
    for caption, amount in reconciliation.items():
        classification, reason, is_wc = classify_caption(caption)
        adjustments.append(Adjustment(
            caption=caption, amount=float(amount), unit=unit,
            fiscal_year=fiscal_year, classification=classification,
            reason=reason, is_working_capital=is_wc,
            quote=quotes.get(caption, ""), doc_id=doc_id,
        ))

    draft = NormalisedCFO(
        doc_id=doc_id, fiscal_year=fiscal_year, unit=unit,
        reported_cfo=float(reported_cfo), normalised_cfo=None,
        adjustments=tuple(adjustments),
    )

    material_uncertain = [
        a for a in draft.by_classification(Classification.UNCERTAIN)
        if draft.weight(a) >= materiality
    ]
    uncertain_weight = draft.uncertain_weight

    notes: list[str] = []
    if material_uncertain:
        notes.append(
            f"{len(material_uncertain)} unclassified line(s) each above "
            f"{materiality:.0%} of CFO: "
            + "; ".join(f"{a.caption}={a.amount:,.0f}" for a in material_uncertain)
        )

    if uncertain_weight > uncertain_budget:
        return NormalisedCFO(
            doc_id=doc_id, fiscal_year=fiscal_year, unit=unit,
            reported_cfo=float(reported_cfo), normalised_cfo=None,
            adjustments=tuple(adjustments),
            unmatched_captions=tuple(
                a.caption for a in draft.by_classification(Classification.UNCERTAIN)),
            sufficient=False,
            reason=(
                f"NORMALIZATION_INSUFFICIENT: {uncertain_weight:.0%} of reported "
                f"CFO sits in captions this module cannot classify, above the "
                f"{uncertain_budget:.0%} budget. Missing evidence: what these "
                "lines are and whether they recur. Classify them by adding a "
                "marker with an accounting justification, or record an analyst "
                "override; do not estimate them."
            ),
            notes=tuple(notes),
        )

    normalised = float(reported_cfo) - draft.removed
    flagged = draft.by_classification(Classification.POTENTIALLY_NON_RECURRING)
    if flagged:
        notes.append(
            f"{len(flagged)} line(s) totalling {draft.removed:,.0f} {unit} are "
            "flagged as potentially non-recurring and REMOVED from normalised "
            "CFO. Each is a judgement the analyst can reverse: "
            + "; ".join(f"{a.caption}={a.amount:,.0f}" for a in flagged)
        )

    wc = [a for a in adjustments if a.is_working_capital]
    if wc:
        wc_total = sum(a.amount for a in wc)
        notes.append(
            f"working capital contributes {wc_total:,.0f} {unit} "
            f"({abs(wc_total) / abs(reported_cfo) if reported_cfo else 0:.0%} of "
            "reported CFO). Kept IN normalised CFO - the category recurs - but "
            "its level is one year's swing, not a run rate."
        )

    return NormalisedCFO(
        doc_id=doc_id, fiscal_year=fiscal_year, unit=unit,
        reported_cfo=float(reported_cfo), normalised_cfo=normalised,
        adjustments=tuple(adjustments),
        unmatched_captions=tuple(
            a.caption for a in draft.by_classification(Classification.UNCERTAIN)),
        sufficient=True, reason="", notes=tuple(notes),
    )
