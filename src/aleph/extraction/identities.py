"""Cross-statement gates: period alignment, unit consistency, accounting identities.

The six gates in gates.py check ONE fact against the region it was copied
from. These check facts against EACH OTHER, across statements, which is a
different question and catches a different class of error: every individual
figure can quote correctly, cross-foot correctly and carry the right unit
while still belonging to a different period, a different scale or a balance
sheet that does not balance.

Each check returns a list of Breach objects. Nothing here raises and nothing
here blocks - consistent with principle 5, a library reports and the caller
decides. A breach is evidence, and evidence is only useful if it names the
facts involved, so every Breach carries them.

The identities, in the form they are tested:

    Balance sheet     A = L + E
    Cash roll-forward Cash_end = Cash_begin + net change
    Income statement  NI = pretax income - tax provision

The third is stated in the task specification as
``NI = Operating Income + Non-Operating Items - Taxes``. It is tested in the
equivalent but checkable form above, because "non-operating items" is not a
single caption any of the six filings reports - it is a residual, and an
identity written against a residual can never fail. Pretax income and the
tax provision ARE reported line items, and their difference is net income by
construction.
"""
from dataclasses import dataclass, field

__all__ = [
    "DEFAULT_TOLERANCE",
    "Breach",
    "Figure",
    "check_period_alignment",
    "check_unit_consistency",
    "check_balance_sheet_identity",
    "check_cash_rollforward",
    "check_income_identity",
    "run_all",
]

# Relative tolerance for an identity, as a share of the larger side. Filings
# round their own components independently of their totals, so an exact
# equality test fails on arithmetic the filer itself published. 0.5% is the
# same slack assumptions.py already applies when reconciling geographic
# components against stated revenue, and is reused rather than reinvented so
# the two cannot drift apart.
DEFAULT_TOLERANCE = 0.005


@dataclass(frozen=True)
class Figure:
    """One extracted number, reduced to what a cross-statement check needs."""
    name: str
    value: float
    period: str | None
    unit: str
    statement: str


@dataclass(frozen=True)
class Breach:
    """One failed cross-statement check, with the facts that failed it.

    ``detail`` states the arithmetic. ``figures`` names the inputs. A breach
    that reports only a verdict sends the reader back to the filing to work
    out which numbers it meant.
    """
    check: str
    detail: str
    figures: tuple[str, ...] = ()
    severity: str = "error"


def _relative_gap(left: float, right: float) -> float:
    """Difference as a share of the larger magnitude; 0.0 when both are zero."""
    scale = max(abs(left), abs(right))
    if scale == 0.0:
        return 0.0
    return abs(left - right) / scale


def check_period_alignment(figures: list[Figure]) -> list[Breach]:
    """Every statement must contribute the same period to a single comparison.

    Mixing a trailing-twelve-month cash flow with an older fiscal-year balance
    sheet produces a ratio whose numerator and denominator describe different
    companies. Nothing in this pipeline currently does that - the period is
    carried on each fact and derivations align on it - so this check is a
    guard against a future caller that assembles figures by hand.

    A figure with no period is reported separately rather than silently
    excluded: an undated number cannot be aligned to anything, and treating
    it as compatible with everything is exactly backwards.
    """
    breaches: list[Breach] = []

    undated = [f for f in figures if f.period is None]
    if undated:
        breaches.append(Breach(
            check="period_alignment",
            detail=(f"{len(undated)} figure(s) carry no period and cannot be "
                    "aligned to anything"),
            figures=tuple(f"{f.statement}:{f.name}" for f in undated),
        ))

    dated = [f for f in figures if f.period is not None]
    by_statement: dict[str, set[str]] = {}
    for f in dated:
        by_statement.setdefault(f.statement, set()).add(f.period)

    common = set.intersection(*by_statement.values()) if by_statement else set()
    if by_statement and not common:
        breaches.append(Breach(
            check="period_alignment",
            detail=("no period is present on every statement: "
                    + "; ".join(f"{s}={sorted(p)}" for s, p in sorted(by_statement.items()))),
            figures=tuple(sorted(by_statement)),
        ))
    return breaches


def check_unit_consistency(figures: list[Figure]) -> list[Breach]:
    """Monetary figures compared with each other must share one scale.

    Compares the resolved SCALE, not the unit string, using the same
    infra.units vocabulary gates.py and bridge.py use - three call sites
    agreeing on what "thousands" means, never four opinions.

    A unit that names no scale (percent, decimal, ratio) or names more than
    one is excluded from the comparison rather than treated as a mismatch:
    unresolved is unverifiable, not wrong. That is the same fail-safe rule
    check_unit_matches_source applies at the extraction gate.
    """
    from ..infra.units import resolve_scale

    scales: dict[float, list[Figure]] = {}
    for f in figures:
        scale = resolve_scale(f.unit)
        if scale is None:
            continue
        scales.setdefault(scale, []).append(f)

    if len(scales) <= 1:
        return []

    groups = "; ".join(
        f"{scale:g}x: " + ", ".join(f"{f.statement}:{f.name}" for f in members)
        for scale, members in sorted(scales.items())
    )
    return [Breach(
        check="unit_consistency",
        detail=f"figures span {len(scales)} different unit scales - {groups}",
        figures=tuple(f"{f.statement}:{f.name}" for m in scales.values() for f in m),
    )]


def check_balance_sheet_identity(
    total_assets: float,
    total_liabilities: float,
    total_equity: float,
    period: str = "",
    tolerance: float = DEFAULT_TOLERANCE,
) -> list[Breach]:
    r"""Assets must equal liabilities plus equity.

    .. math:: A = L + E

    The single most basic check a set of balance-sheet extractions can fail,
    and the one that catches a figure copied from the wrong column: a total
    read one year to the left still quotes correctly and still cross-foots
    within its own row.

    WHICH equity, measured on all six filings. Run against the extracted
    captions this check passes on Lyft and DoorDash in every period and
    breaches on Uber in every period - by 1,433 (FY2023), 918 (FY2024) and
    1,042 (FY2025). Uber is not out of balance. Its balance sheet reads:

        Total liabilities                                      28,768
        Redeemable non-controlling interests                       93
        Total Uber Technologies, Inc. stockholders' equity     21,558
        Non-redeemable non-controlling interests                  825
        Total equity                                           22,383
        Total liabilities, redeemable NCI and equity           51,244

    and 28,768 + 93 + 22,383 = 51,244 exactly. The FY2024 gap of 918 is
    93 + 825 - the non-controlling interests - because the extraction picked
    the parent-only subtotal. FY2023 is the same: 654 + 779 = 1,433.

    So for a filer with material NCI the identity is A = L + mezzanine + E,
    and the equity term must be TOTAL equity, not the attributable subtotal.
    This is the same failure as the one documented on check_income_identity,
    on a second statement: a parent-only caption standing in for a total. The
    fix in both cases is to extract the total, never to widen the tolerance
    until a wrong comparison passes - 1.79% would need a tolerance four times
    the current one, which would also stop catching real breaks.
    """
    right = total_liabilities + total_equity
    gap = _relative_gap(total_assets, right)
    if gap <= tolerance:
        return []
    return [Breach(
        check="balance_sheet_identity",
        detail=(f"{period + ': ' if period else ''}"
                f"assets {total_assets:,.0f} != liabilities {total_liabilities:,.0f} "
                f"+ equity {total_equity:,.0f} = {right:,.0f} "
                f"(off by {abs(total_assets - right):,.0f}, {gap:.2%})"),
        figures=("total_assets", "total_liabilities", "total_equity"),
    )]


def check_cash_rollforward(
    beginning_cash: float,
    net_change: float,
    ending_cash: float,
    period: str = "",
    tolerance: float = DEFAULT_TOLERANCE,
) -> list[Breach]:
    r"""The cash flow statement must roll forward to the reported ending cash.

    .. math:: Cash_{end} = Cash_{begin} + \Delta Cash

    Filers that report cash and restricted cash together in this reconciliation
    will fail this against a balance sheet cash figure that excludes restricted
    cash. That is a real disagreement worth surfacing, not a false positive:
    the two numbers are being read as if they were the same quantity.
    """
    expected = beginning_cash + net_change
    gap = _relative_gap(ending_cash, expected)
    if gap <= tolerance:
        return []
    return [Breach(
        check="cash_rollforward",
        detail=(f"{period + ': ' if period else ''}"
                f"ending cash {ending_cash:,.0f} != beginning {beginning_cash:,.0f} "
                f"+ change {net_change:,.0f} = {expected:,.0f} "
                f"(off by {abs(ending_cash - expected):,.0f}, {gap:.2%})"),
        figures=("beginning_cash", "net_change_in_cash", "ending_cash"),
    )]


def check_income_identity(
    pretax_income: float,
    tax_provision: float,
    net_income: float,
    period: str = "",
    tolerance: float = DEFAULT_TOLERANCE,
) -> list[Breach]:
    r"""Net income must be pretax income less the tax provision.

    .. math:: NI = EBT - T

    Sign convention follows the filings: a provision is positive when tax is
    an expense and negative when it is a benefit, so the identity subtracts
    in both cases. Uber's FY2024 is the case that matters - a benefit of
    -5,758 against pretax income, giving net income ABOVE pretax income. An
    implementation that took the absolute value of the provision would report
    a breach on a filing that balances perfectly.

    WHICH net income, measured: this identity needs TOTAL net income, and the
    pipeline currently extracts "Net income (loss) attributable to Uber
    Technologies, Inc." - the figure after non-controlling interests. Run
    against Uber's three disclosed years the difference is not academic:

        FY2022  pretax -9,426  tax -181    -> -9,245 vs -9,141 reported (1.1%)
        FY2023  pretax  2,321  tax   213   ->  2,108 vs  1,887 reported (10.5%)
        FY2024  pretax  4,125  tax -5,758  ->  9,883 vs  9,856 reported (0.3%)

    Two of three breach, and the check is RIGHT to breach: the attributable
    figure is not the identity's left-hand side. Wiring this to the facts as
    they are extracted today would report an extraction failure that is not
    one. The fix is to extract total net income, not to widen the tolerance
    until a wrong comparison passes.
    """
    expected = pretax_income - tax_provision
    gap = _relative_gap(net_income, expected)
    if gap <= tolerance:
        return []
    return [Breach(
        check="income_identity",
        detail=(f"{period + ': ' if period else ''}"
                f"net income {net_income:,.0f} != pretax {pretax_income:,.0f} "
                f"- tax {tax_provision:,.0f} = {expected:,.0f} "
                f"(off by {abs(net_income - expected):,.0f}, {gap:.2%})"),
        figures=("pretax_income", "tax_provision", "net_income"),
    )]


def run_all(
    figures: list[Figure],
    identities: dict[str, dict[str, float]] | None = None,
    tolerance: float = DEFAULT_TOLERANCE,
) -> list[Breach]:
    """Run every structural check, and each identity whose inputs are supplied.

    ``identities`` maps a period to the figures that period offers, by the
    keyword names the identity functions take. An identity whose inputs are
    absent is NOT run and NOT reported as passing - a check that never ran is
    not a check that succeeded, and conflating the two is how a documented
    guarantee ends up enforcing nothing.
    """
    breaches = check_period_alignment(figures) + check_unit_consistency(figures)

    for period, values in sorted((identities or {}).items()):
        if {"total_assets", "total_liabilities", "total_equity"} <= values.keys():
            breaches += check_balance_sheet_identity(
                values["total_assets"], values["total_liabilities"],
                values["total_equity"], period, tolerance)
        if {"beginning_cash", "net_change_in_cash", "ending_cash"} <= values.keys():
            breaches += check_cash_rollforward(
                values["beginning_cash"], values["net_change_in_cash"],
                values["ending_cash"], period, tolerance)
        if {"pretax_income", "tax_provision", "net_income"} <= values.keys():
            breaches += check_income_identity(
                values["pretax_income"], values["tax_provision"],
                values["net_income"], period, tolerance)

    return breaches
