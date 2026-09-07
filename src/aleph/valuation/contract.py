"""The required-data contract: what a valuation needs, declared before extraction.

THE DEFECT THIS EXISTS FOR. `check_coverage` in gates.py groups facts by their
quote and can only examine rows that appear in at least one quote. A row the
model never referenced produces no group, so there is nothing for the gate to
iterate over - confirmed by synthetic test in ISSUES.md #27. The gate cannot
see what was never returned. Any gate built that way cannot: it is downstream
of the omission it is supposed to catch.

The fix is not a better gate. It is knowing the requirement BEFORE extraction,
so "expected but never seen" is a state the system holds rather than an
absence it cannot observe:

    VALUATION REQUIREMENTS -> CONTRACT -> extraction -> verification
                                                            |
                                       DERIVATION <- CONTRACT GATE

Every requirement below is taken from the real code path, not invented:
`require(ranges, ...)` in bridge.py, REQUIRED_MARKET in wacc.py, `_market(...)`
lookups, and the substring each derive_* function queries. A requirement
nothing actually consumes would be theatre.

WHAT THIS MODULE DOES NOT DO. It does not extract, derive, value, or repair.
It reports states. The caller blocks. A library raises or reports; the CLI
decides the exit code (principle 5).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "State",
    "Kind",
    "Status",
    "Requirement",
    "Observed",
    "ContractResult",
    "REQUIREMENTS",
    "KNOWN_UNITS",
    "evaluate",
    "requirements_for",
]


class State(str, Enum):
    """Lifecycle of one required observation. None of these is None.

    EXPECTED       declared by the contract; extraction has not run yet.
    LOCATED        a region was resolved for it, but nothing extracted yet.
    EXTRACTED      the model returned it; gates have not accepted it yet.
    VERIFIED       extracted AND gate-accepted AND unit and period resolved.
                   Only this state may reach a valuation.
    DERIVED        computed from other VERIFIED observations, not read.
    MISSING        expected, extraction ran, nothing came back. This is the
                   state the old coverage gate structurally could not hold.
    AMBIGUOUS      two or more conflicting candidates; the system will not
                   choose between them.
    BLOCKED        present but unusable - unknown unit, wrong period, a
                   derivation that refused.
    NOT_APPLICABLE the filer does not report it and the methodology does not
                   need it. Different from MISSING, and never inferred from
                   absence alone.
    """

    EXPECTED = "EXPECTED"
    LOCATED = "LOCATED"
    EXTRACTED = "EXTRACTED"
    VERIFIED = "VERIFIED"
    DERIVED = "DERIVED"
    MISSING = "MISSING"
    AMBIGUOUS = "AMBIGUOUS"
    BLOCKED = "BLOCKED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Kind(str, Enum):
    DIRECT_FACT = "DIRECT_FACT"
    DERIVED_FACT = "DERIVED_FACT"
    ANALYST_ASSUMPTION = "ANALYST_ASSUMPTION"
    MARKET_DATA = "MARKET_DATA"
    OPTIONAL = "OPTIONAL"


class Status(str, Enum):
    """Aggregate verdict.

    PASS                every requirement of every SELECTED path is VERIFIED
                        or DERIVED.
    PASS_WITH_WARNINGS  every required path is satisfied; an OPTIONAL path is
                        not, so a diagnostic is unavailable but no valuation
                        depends on it.
    BLOCKED             at least one required observation is MISSING,
                        AMBIGUOUS or BLOCKED. The path it feeds does not run.
    """

    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    BLOCKED = "BLOCKED"


# Valuation paths. A requirement is enforced only for the paths actually
# selected, so a run that asks for no reverse DCF is not blocked by the
# absence of a market price.
PATH_DCF = "dcf"
PATH_PER_SHARE = "per_share"
PATH_WACC = "wacc"
PATH_REVERSE_DCF = "reverse_dcf"
PATH_HISTORICAL = "historical_fcff"

# Units a valuation input may carry. Anything else cannot become VERIFIED:
# an unresolved unit is the failure that valued LYFT_FY2025 at 65,792 against
# a 17.35 market price (ISSUES.md #15).
KNOWN_UNITS = (
    "usd", "usd thousands", "usd millions", "usd billions",
    "thousands", "millions", "billions",
    "shares", "percent", "%", "decimal", "ratio",
)


@dataclass(frozen=True)
class Requirement:
    """One thing the valuation needs, and which paths stop without it."""

    field: str
    kind: Kind
    required_for: tuple[str, ...]
    source: str
    note: str = ""
    depends_on: tuple[str, ...] = ()


# Every entry below is read off the code path named in its `source`.
REQUIREMENTS: tuple[Requirement, ...] = (
    Requirement("operating_cash_flow", Kind.DERIVED_FACT, (PATH_DCF,),
                "bridge.require; derive_operating_cash_flow queries "
                "'operating activities'"),
    Requirement("capex", Kind.DERIVED_FACT, (PATH_DCF,),
                "bridge.require; derive_capex queries 'property and equipment'"),
    Requirement("interest_expense", Kind.DERIVED_FACT, (PATH_DCF,),
                "bridge.require; FCFF adds it back after tax so CFO's levered "
                "basis is not double-counted"),
    Requirement("stock_based_compensation", Kind.DERIVED_FACT, (PATH_DCF,),
                "bridge.require; subtracted from FCFF at full value per ADR 0002"),
    Requirement("effective_tax_rate", Kind.ANALYST_ASSUMPTION,
                (PATH_DCF, PATH_WACC),
                "bridge.require and wacc; blocks on sign change in every "
                "filing measured, so it arrives by override"),
    Requirement("revenue_growth", Kind.DERIVED_FACT, (PATH_DCF,),
                "bridge.require; derive_growth queries 'total revenue'"),
    Requirement("net_debt", Kind.ANALYST_ASSUMPTION,
                (PATH_DCF, PATH_PER_SHARE, PATH_WACC),
                "bridge.require and wacc; ADR 0004 - always blocks until an "
                "analyst states a cash and debt policy"),
    Requirement("diluted_shares", Kind.DERIVED_FACT,
                (PATH_PER_SHARE, PATH_WACC),
                "bridge.require and wacc; the divisor of the entire per-share "
                "result"),

    Requirement("risk_free_rate", Kind.MARKET_DATA, (PATH_WACC,),
                "wacc.REQUIRED_MARKET"),
    Requirement("equity_risk_premium", Kind.MARKET_DATA, (PATH_WACC,),
                "wacc.REQUIRED_MARKET"),
    Requirement("unlevered_industry_beta", Kind.ANALYST_ASSUMPTION, (PATH_WACC,),
                "wacc.REQUIRED_MARKET; held identical across filers per ADR 0001"),
    Requirement("debt_spread", Kind.MARKET_DATA, (PATH_WACC,),
                "wacc.REQUIRED_MARKET"),
    Requirement("country_risk_premium", Kind.ANALYST_ASSUMPTION, (PATH_WACC,),
                "wacc.REQUIRED_MARKET"),
    Requirement("share_price", Kind.MARKET_DATA,
                (PATH_WACC, PATH_REVERSE_DCF),
                "wacc.REQUIRED_MARKET for market-value weights; the reverse "
                "DCF solves against it"),
    Requirement("terminal_growth", Kind.ANALYST_ASSUMPTION,
                (PATH_DCF, PATH_REVERSE_DCF),
                "bridge._market"),
    Requirement("discount_rate", Kind.DERIVED_FACT,
                (PATH_DCF, PATH_REVERSE_DCF),
                "bridge._market; DERIVED by build_wacc and never authored - "
                "ISSUES.md #19",
                depends_on=("risk_free_rate", "equity_risk_premium",
                            "unlevered_industry_beta", "debt_spread",
                            "country_risk_premium", "share_price",
                            "net_debt", "diluted_shares", "effective_tax_rate")),

    Requirement("fcff_by_period", Kind.DERIVED_FACT, (PATH_HISTORICAL,),
                "bridge.base_cash_flow_bound; historical_fcff needs at least "
                "three verified periods",
                depends_on=("operating_cash_flow", "capex", "interest_expense",
                            "stock_based_compensation")),
    Requirement("geographic_revenue", Kind.OPTIONAL, (),
                "derive_geographic_revenue; feeds the country risk premium a "
                "human sets, and no valuation path stops without it"),
)


@dataclass(frozen=True)
class Observed:
    """What the run actually holds for one field.

    ``override`` is carried SEPARATELY from ``value`` and never folded into
    it: an analyst decision that looks like filing evidence is the thing this
    whole repository is built to prevent.
    """

    field: str
    state: State
    value: float | None = None
    unit: str | None = None
    period: str | None = None
    quote: str = ""
    source_ref: str = ""
    detail: str = ""
    override: bool = False
    override_reason: str = ""
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True)
class ContractResult:
    status: Status
    rows: tuple[Observed, ...]
    expected_count: int
    verified_count: int
    blocked_paths: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def row(self, field_name: str) -> Observed | None:
        return next((r for r in self.rows if r.field == field_name), None)

    def by_state(self, state: State) -> tuple[Observed, ...]:
        return tuple(r for r in self.rows if r.state is state)

    def path_is_blocked(self, path: str) -> bool:
        return path in self.blocked_paths

    def as_table(self) -> str:
        width = max((len(r.field) for r in self.rows), default=10)
        lines = [f"{r.field:<{width}}  {r.state.value}"
                 + (f"  ({r.detail})" if r.detail else "")
                 + ("  [ANALYST OVERRIDE]" if r.override else "")
                 for r in self.rows]
        lines.append(f"STATUS: {self.status.value}")
        for reason in self.reasons:
            lines.append(f"  {reason}")
        return "\n".join(lines)


def requirements_for(paths: tuple[str, ...]) -> tuple[Requirement, ...]:
    """Only the requirements the selected paths actually consume."""
    return tuple(r for r in REQUIREMENTS
                 if any(p in r.required_for for p in paths))


_BAD = {State.MISSING, State.AMBIGUOUS, State.BLOCKED}


def evaluate(
    observed: dict[str, Observed],
    paths: tuple[str, ...] = (PATH_DCF, PATH_PER_SHARE, PATH_WACC),
) -> ContractResult:
    """Compare what the contract expects against what the run holds.

    A field the contract expects and ``observed`` does not mention is MISSING.
    That single line is the structural fix: the state exists whether or not
    the extractor ever said anything, so an omission cannot vanish.
    """
    needed = requirements_for(paths)
    rows: list[Observed] = []
    reasons: list[str] = []
    blocked_paths: set[str] = set()

    satisfied: set[str] = {
        name for name, row in observed.items()
        if row.state in (State.VERIFIED, State.DERIVED)
    }

    for req in needed:
        row = observed.get(req.field)
        if row is None and req.depends_on:
            # THE DEPENDENCY GRAPH DOING ITS JOB. A field that is computed
            # later in the run is not missing at gate time - it is pending on
            # inputs the gate CAN check now. discount_rate is derived by
            # build_wacc, which runs after this gate; blocking on its absence
            # would refuse every valid run. What matters is whether everything
            # it is computed FROM is present, and that is checkable here.
            unmet = [d for d in req.depends_on if d not in satisfied]
            if not unmet:
                row = Observed(
                    field=req.field, state=State.EXPECTED,
                    detail=("derived later in the run; every input it depends "
                            f"on is satisfied ({len(req.depends_on)} of "
                            f"{len(req.depends_on)})"),
                )
            else:
                row = Observed(
                    field=req.field, state=State.BLOCKED,
                    detail=("cannot be derived: depends on "
                            f"{', '.join(unmet)}, which are not verified"),
                )
        if row is None:
            row = Observed(
                field=req.field, state=State.MISSING,
                detail=("expected by the contract and never returned by "
                        f"extraction. Required for: {', '.join(req.required_for)}"),
            )
        rows.append(row)

        if row.state in _BAD:
            for path in req.required_for:
                if path in paths:
                    blocked_paths.add(path)
            reasons.append(
                f"{req.field} is {row.state.value}"
                + (f" - {row.detail}" if row.detail else "")
                + f". Blocks: {', '.join(p for p in req.required_for if p in paths)}"
            )

    optional_gaps = [
        r.field for r in REQUIREMENTS
        if r.kind is Kind.OPTIONAL
        and (r.field not in observed or observed[r.field].state in _BAD)
    ]

    if blocked_paths:
        status = Status.BLOCKED
    elif optional_gaps:
        status = Status.PASS_WITH_WARNINGS
    else:
        status = Status.PASS

    notes = []
    if optional_gaps:
        notes.append(
            f"optional diagnostics unavailable: {', '.join(optional_gaps)}. "
            "No valuation path depends on these.")
    overrides = [r for r in rows if r.override]
    if overrides:
        notes.append(
            f"{len(overrides)} analyst override(s), labelled and not counted "
            "as filing evidence: "
            + "; ".join(f"{r.field} ({r.override_reason[:60]})" for r in overrides))

    return ContractResult(
        status=status, rows=tuple(rows),
        expected_count=len(needed),
        verified_count=sum(1 for r in rows
                           if r.state in (State.VERIFIED, State.DERIVED)),
        blocked_paths=tuple(sorted(blocked_paths)),
        reasons=tuple(reasons), notes=tuple(notes),
    )
