"""Adjust reported accounting figures toward economic reality.

STATUS: EXPERIMENTAL - NOT IN THE LIVE VALUATION PATH (P5.1 closure, Part 15).
Nothing in scripts/run_valuation.py or valuation/pipeline.py imports this
module; it is exercised only by tests/test_normalization.py. As the next
paragraph already says, bridge.py is untouched by it. Kept as research
history (R&D capitalisation, operating-lease and SBC views); not wired in;
requires an ADR to become live.


Three adjustments, each deterministic and each reversible by reading the
returned breakdown. Nothing here calls a model, and nothing here is wired
into the DCF: bridge.py builds FCFF from CFO and is untouched. That is
deliberate. R&D capitalisation changes EBIT and invested capital, which are
inputs to ROIC, not to a CFO-based FCFF - routing it into cash flow as well
would double-count the same spending, since CFO already reflects R&D paid in
cash.

WHAT THIS MODULE DOES NOT DO, stated because the omission is easy to mistake
for an oversight: it does not adjust FCFF. docs/adr/0002 decided that
stock-based compensation is subtracted from FCFF at full value and that the
share count stays flat, and bridge.py implements exactly that. The SBC
helper here reports the same treatment as a normalisation, so a caller can
see the adjustment in isolation; it is not a second implementation feeding a
second answer.

Formulas, in the notation the docstrings use:

    Unamortised R&D asset
        A_t = sum_{i=1..L} R_{t-i} * (L - i) / L

    Amortisation of the R&D asset in year t
        D_t = sum_{i=1..L} R_{t-i} / L

    Adjusted operating income
        EBIT_adj = EBIT_reported + R_t - D_t

    Invested capital
        IC = D_total + E_book + A_t

    Return on invested capital
        ROIC = EBIT_adj * (1 - T_c) / IC
"""
from dataclasses import dataclass, field

__all__ = [
    "NON_RECURRING_MARKERS",
    "RandDResult",
    "NormalisedEarnings",
    "capitalise_rd",
    "adjusted_ebit",
    "invested_capital",
    "roic",
    "sbc_adjusted_fcff",
    "flag_non_recurring",
]

# Captions that name an item most analysts exclude from a run-rate. Matched
# as substrings against a lowercased caption, because filers phrase these
# differently and no two of the six filings tested word them identically.
#
# This list is DELIBERATELY not exhaustive and never will be. It flags; it
# does not decide. ISSUES.md #26 is the standing lesson: a substring list
# written against a few filers silently misses the next one's wording, so
# the output names what matched AND what did not, and the caller judges.
NON_RECURRING_MARKERS: tuple[str, ...] = (
    "impairment",
    "restructuring",
    "severance",
    "legal settlement",
    "litigation settlement",
    "gain on sale",
    "loss on sale",
    "gain on disposal",
    "loss on disposal",
    "goodwill write",
    "asset write-down",
    "acquisition-related",
    "one-time",
)


@dataclass(frozen=True)
class RandDResult:
    """One period's R&D capitalisation, with every component kept.

    A single "adjusted EBIT" number is not reviewable. The schedule that
    produced it is, which is why by_vintage survives into the result.
    """
    period: str
    amortisation_years: int
    current_expense: float
    unamortised_asset: float
    amortisation: float
    by_vintage: dict[str, float] = field(default_factory=dict)
    note: str = ""

    @property
    def ebit_uplift(self) -> float:
        """R_t - D_t: what adjusted EBIT gains over the reported figure."""
        return self.current_expense - self.amortisation


@dataclass(frozen=True)
class NormalisedEarnings:
    """Adjusted EBIT and ROIC for one period, with the inputs that made them."""
    period: str
    reported_ebit: float
    adjusted_ebit: float
    tax_rate: float
    invested_capital: float
    roic: float | None
    rd: RandDResult | None = None
    notes: tuple[str, ...] = ()


def capitalise_rd(
    history: dict[str, float],
    period: str,
    amortisation_years: int = 3,
) -> RandDResult:
    r"""Capitalise R&D on a straight-line schedule.

    ``history`` maps period label to that period's R&D EXPENSE as reported.
    Labels must sort chronologically as strings - "FY2023" < "FY2024" does,
    which is the convention every extracted fact in this project already uses.

    The asset at the end of ``period`` carries each earlier year's spend at
    the fraction of its life still remaining:

    .. math::
        A_t = \sum_{i=1}^{L} R_{t-i} \frac{L - i}{L}

    and the year's amortisation is the straight-line share of each vintage
    still being written off:

    .. math::
        D_t = \sum_{i=1}^{L} \frac{R_{t-i}}{L}

    The CURRENT year's spend is capitalised in full and contributes no
    amortisation yet, which is why ``ebit_uplift`` is positive for a company
    whose R&D is growing and negative for one whose R&D is shrinking.

    A short history is not an error and is not padded with zeros - zeros
    would understate the asset and overstate ROIC. The result says how many
    vintages it actually had.
    """
    if amortisation_years < 1:
        raise ValueError("amortisation_years must be at least 1")
    if period not in history:
        raise KeyError(f"{period!r} is not in the R&D history {sorted(history)}")

    earlier = sorted(p for p in history if p < period)
    used = earlier[-amortisation_years:]

    asset = 0.0
    amortisation = 0.0
    by_vintage: dict[str, float] = {}
    for age, vintage in enumerate(reversed(used), start=1):
        spend = history[vintage]
        remaining = spend * (amortisation_years - age) / amortisation_years
        asset += remaining
        amortisation += spend / amortisation_years
        by_vintage[vintage] = remaining

    current = history[period]
    asset += current                       # this year's spend, not yet amortised
    by_vintage[period] = current

    missing = amortisation_years - len(used)
    note = ""
    if missing > 0:
        note = (
            f"only {len(used)} of {amortisation_years} prior years available; "
            f"the asset is understated by whatever was spent in the "
            f"{missing} missing year(s). Not padded with zeros - a zero is a "
            "measurement, an absence is not."
        )

    return RandDResult(
        period=period,
        amortisation_years=amortisation_years,
        current_expense=current,
        unamortised_asset=asset,
        amortisation=amortisation,
        by_vintage=by_vintage,
        note=note,
    )


def adjusted_ebit(reported_ebit: float, rd: RandDResult) -> float:
    r"""EBIT with R&D treated as investment rather than expense.

    .. math:: EBIT_{adj} = EBIT_{reported} + R_t - D_t
    """
    return reported_ebit + rd.ebit_uplift


def invested_capital(
    total_debt: float,
    book_equity: float,
    rd_asset: float = 0.0,
) -> float:
    r"""Capital the business is financed with, including capitalised R&D.

    .. math:: IC = D + E + A_t

    The R&D asset belongs here for the same reason it belongs in EBIT: a
    company that expensed it looks as though it invested nothing, so its
    ROIC denominator is missing exactly the spending its returns came from.
    """
    return total_debt + book_equity + rd_asset


def roic(
    ebit_after_adjustment: float, tax_rate: float, capital: float
) -> float | None:
    r"""After-tax return on invested capital.

    .. math:: ROIC = \frac{EBIT_{adj} (1 - T_c)}{IC}

    Returns None when capital is zero or negative rather than a number: a
    ratio over non-positive capital is arithmetic, not a return, and a
    company financed by an accumulated deficit would otherwise report a
    spectacular ROIC on the way to insolvency.
    """
    if capital <= 0:
        return None
    return ebit_after_adjustment * (1.0 - tax_rate) / capital


def sbc_adjusted_fcff(
    cfo: float,
    capex: float,
    sbc: float,
    interest: float = 0.0,
    tax_rate: float = 0.0,
) -> float:
    r"""FCFF with stock-based compensation treated as a cash cost.

    .. math:: FCFF = CFO + I(1 - T_c) - CapEx - SBC

    The interest add-back is not optional and defaults to zero only so a
    caller holding no interest figure gets an explicit zero rather than a
    silent one. CFO is a LEVERED figure - interest paid is already deducted -
    and WACC discounting prices the cost of debt again, so omitting the
    add-back counts interest twice. bridge.py carries the same formula as its
    rule 1; this function exists so the adjustment can be inspected on its
    own, not so a second answer can be produced.

    Sign convention: ``capex``, ``sbc`` and ``interest`` are magnitudes.
    Whatever sign the filing prints them with is removed here, so a filer
    that reports capex as a negative number cannot silently add it back.
    """
    return cfo + abs(interest) * (1.0 - tax_rate) - abs(capex) - abs(sbc)


def flag_non_recurring(
    captions: dict[str, float],
) -> tuple[dict[str, float], list[str]]:
    """Split captions into (flagged, unmatched-caption-names).

    Returns BOTH halves on purpose. A filter that reports only what it caught
    tells an analyst nothing about what it may have missed, and #26 recorded
    what that costs: a block printed an incomplete component list and implied
    a net-debt figure wrong by 1.3 billion. The second element names every
    caption the markers did not match, so the reader can see the evidence the
    filter did not act on.

    Nothing is removed from anything. This flags; the analyst decides.
    """
    flagged = {
        caption: value for caption, value in captions.items()
        if any(marker in caption.lower() for marker in NON_RECURRING_MARKERS)
    }
    unmatched = sorted(c for c in captions if c not in flagged)
    return flagged, unmatched
