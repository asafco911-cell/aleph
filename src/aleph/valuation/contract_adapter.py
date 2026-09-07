"""Turn real pipeline state into contract rows. Reports states; decides nothing.

Kept apart from contract.py so the contract stays a declaration and this stays
the reading of it. The split matters when a requirement changes: the statement
of what is needed should not move because the way it is observed did.
"""
from __future__ import annotations

import re

from .contract import KNOWN_UNITS, Observed, Reason, State

__all__ = ["row_for_range", "row_for_market", "row_for_series", "observe",
           "frequency_of"]

# "ambiguous fact selection" is the exact phrase _observations raises when two
# different captions match one query in one period. The upstream collision
# check already refuses to choose between them, and the architecture requires
# the aggregate status to be BLOCKED - but the CAUSE must survive, so a reader
# can tell two conflicting values from nothing having been returned.
_AMBIGUITY_MARKERS = ("ambiguous fact selection", "both match")

_QUARTERLY = re.compile(r"Q[1-4]", re.I)


def frequency_of(period: str | None) -> str:
    """annual or quarterly, from the period label.

    FY2025 and Q3FY2025 are both dated and both present; combining them into
    one FCFF is a mismatch no amount of label-matching catches, so frequency
    is read separately and compared by the gate.
    """
    if not period:
        return "annual"
    return "quarterly" if _QUARTERLY.search(period) else "annual"


def _unit_ok(unit: str | None) -> bool:
    """A unit must be one the system can convert. Unknown never becomes VERIFIED.

    ISSUES.md #15: an unresolved unit valued LYFT_FY2025 at 65,792 per share
    against a 17.35 market price, with no arithmetic error anywhere.
    """
    if not unit:
        return False
    lowered = unit.strip().lower()
    return any(known in lowered for known in KNOWN_UNITS)


def row_for_range(field: str, assumption) -> Observed:
    """One derived AssumptionRange, read into a contract row.

    An override is recorded as an override. Folding it into the value would
    let an analyst decision reach the DCF wearing the clothes of filing
    evidence, which is the failure the whole provenance architecture exists
    to prevent.
    """
    if assumption is None:
        return Observed(field, State.MISSING,
                        detail="no AssumptionRange was produced for this field")

    is_override = assumption.status in ("overridden", "fixed")
    reason = (assumption.rationale or "")[:200]

    if assumption.status == "blocked":
        lowered = reason.lower()
        if any(m in lowered for m in _AMBIGUITY_MARKERS):
            return Observed(field, State.AMBIGUOUS, detail=reason,
                            reason=Reason.AMBIGUOUS)
        return Observed(field, State.BLOCKED, detail=reason,
                        reason=Reason.DERIVATION_BLOCKED)

    value = getattr(assumption, "base", None)
    if value is None:
        return Observed(field, State.BLOCKED,
                        detail=f"status {assumption.status} but no base value")

    if not _unit_ok(assumption.unit):
        return Observed(
            field, State.BLOCKED, value=value, unit=assumption.unit,
            detail=(f"unit {assumption.unit!r} is not one this system can "
                    "convert; an unresolved unit must never be VERIFIED "
                    "(ISSUES.md #15)"),
            reason=Reason.INVALID_UNIT,
            override=is_override, override_reason=reason if is_override else "")

    periods = [o.period for o in getattr(assumption, "observations", []) or []]
    latest_period = periods[-1] if periods else None
    return Observed(
        field, State.DERIVED if not is_override else State.VERIFIED,
        value=value, unit=assumption.unit,
        period=latest_period, frequency=frequency_of(latest_period),
        detail=("analyst override" if is_override else
                f"derived from {len(periods)} period(s)"),
        override=is_override, override_reason=reason if is_override else "",
    )


def row_for_market(field: str, market: dict) -> Observed:
    """One market input. Requires a value, a unit, a source and an as_of date."""
    entry = market.get(field)
    if entry is None:
        return Observed(field, State.MISSING, reason=Reason.MISSING,
                        detail="not present in data/market.json")
    if not getattr(entry, "source", "").strip():
        return Observed(field, State.BLOCKED, value=entry.value,
                        detail="no source recorded",
                        reason=Reason.DERIVATION_BLOCKED)
    if not getattr(entry, "as_of", "").strip():
        return Observed(field, State.BLOCKED, value=entry.value,
                        detail="no as_of date recorded",
                        reason=Reason.DERIVATION_BLOCKED)
    if not _unit_ok(entry.unit):
        return Observed(field, State.BLOCKED, value=entry.value, unit=entry.unit,
                        detail=f"unit {entry.unit!r} is not convertible",
                        reason=Reason.INVALID_UNIT)
    return Observed(field, State.VERIFIED, value=entry.value, unit=entry.unit,
                    source_ref=f"{entry.source} (as of {entry.as_of})",
                    detail="market input")


def row_for_series(field: str, bound: dict, minimum_periods: int = 3) -> Observed:
    """The multi-period FCFF series historical analysis needs.

    Fewer than ``minimum_periods`` is BLOCKED, not a shorter series: a median
    over two points is a midpoint, and reporting one would be the silent
    calculation on an inadequate sample this contract exists to stop.
    """
    if not bound or not bound.get("available"):
        return Observed(field, State.MISSING, reason=Reason.MISSING,
                        detail=(bound or {}).get("reason", "no series available"))
    series = bound.get("fcff_by_period") or {}
    if len(series) < minimum_periods:
        return Observed(
            field, State.BLOCKED,
            reason=Reason.INSUFFICIENT_HISTORY,
            detail=(f"HISTORICAL_DATA_INSUFFICIENT: {len(series)} verified "
                    f"period(s), minimum {minimum_periods}"))
    return Observed(field, State.DERIVED, value=float(len(series)),
                    unit="periods",
                    detail=f"{len(series)} periods: {', '.join(sorted(series))}")


def observe(
    ranges: dict, market: dict, bound: dict | None = None,
    market_price: float | None = None,
) -> dict[str, Observed]:
    """Read the whole run into contract rows.

    Deliberately does NOT iterate the contract: it reports only what the run
    holds. Anything the contract expects and this does not produce becomes
    MISSING inside evaluate(), which is where an extraction omission is
    caught rather than lost.
    """
    observed: dict[str, Observed] = {}

    for field, assumption in (ranges or {}).items():
        observed[field] = row_for_range(field, assumption)

    for field in ("risk_free_rate", "equity_risk_premium",
                  "unlevered_industry_beta", "debt_spread",
                  "country_risk_premium", "terminal_growth", "discount_rate"):
        if field in (market or {}):
            observed[field] = row_for_market(field, market)

    if market_price is not None:
        observed["share_price"] = Observed(
            "share_price", State.VERIFIED, value=market_price, unit="USD",
            detail="supplied on the command line for this run")
    elif "share_price" in (market or {}):
        observed["share_price"] = row_for_market("share_price", market)

    if bound is not None:
        observed["fcff_by_period"] = row_for_series("fcff_by_period", bound)

    return observed
