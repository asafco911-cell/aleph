"""Run the full valuation for one filing and return the result as data.

This is the orchestration every caller shares: extract, derive, build a
bottom-up WACC, bridge to DCF inputs, value, and run the sensitivity and
reverse DCF. It exists so there is exactly ONE implementation of that
sequence. A second caller that re-ran the same steps in its own order
would be a second pipeline that can silently disagree with the first about
what this project's own numbers are.

Nothing here prints and nothing here exits. A library raises; the CLI
decides the exit code and the presentation - `sys.exit()` inside a library
once killed a Streamlit session instead of failing one request. Progress
that a caller wants to show while extraction is still running arrives
through the `on_target` callback, fired inside the loop, not collected and
returned at the end.
"""
import json
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

from ..extraction import extract
from ..extraction.targets import resolve_targets
from ..schemas import DocumentRecord
from ..schemas.valuation import AssumptionRange, MarketAssumption, Override
from .assumptions import derive_all
from .bridge import BridgeError, build_dcf_inputs
from .wacc import build_wacc

from .dcf_engine import (
    DCFConsistencyError,
    reverse_dcf,
    run_dcf,
    sensitivity_tornado,
)

MANIFEST = Path("data/manifest.json")
OVERRIDES = Path("data/overrides.json")
MARKET = Path("data/market.json")

BETA_BOUND_FACTORS = (0.75, 1.45)


class BlockedError(RuntimeError):
    """A required assumption is blocked, so no valuation is defensible.

    Carries the blocked ranges themselves, not just a message: a caller has
    to be able to report WHICH quantity blocked and why, and re-deriving
    that from a formatted string is how a second implementation starts.

    It also carries the evidence extracted before the block, because a block
    is not protection if the evidence it hands the analyst is incomplete
    (ISSUES.md #26). An analyst reads that evidence to decide the override
    that unblocks the run.
    """

    def __init__(
        self,
        blocked: list[AssumptionRange],
        facts: list | None = None,
        rejected: list | None = None,
    ) -> None:
        self.blocked = blocked
        self.facts = facts or []
        self.rejected = rejected or []
        super().__init__(f"blocked assumptions: {[a.name for a in blocked]}")


@dataclass
class TargetResult:
    """One extraction target's outcome, reported as it completes."""
    key: str
    target: str
    skipped: bool = False
    accepted: int = 0
    rejected: int = 0


@dataclass
class ValuationRun:
    """Everything a caller needs to render a valuation, computed once."""
    doc_id: str
    market_price: float | None
    record: DocumentRecord
    targets: list[TargetResult]
    ranges: dict[str, AssumptionRange]
    bridged: object                    # Bridged, from bridge.py
    result: object                     # DCFResult, from dcf_engine
    facts: list = field(default_factory=list)      # gate-passed Facts, with quote + source
    rejected: list = field(default_factory=list)   # Rejections, shown, never used
    wacc: object | None = None         # WACCResult, None if it could not be built
    wacc_error: str | None = None
    beta_base: float | None = None
    # WACC values, not betas: the run re-derives WACC at each beta bound
    # rather than putting a hand-picked band around the derived rate.
    wacc_at_beta_bounds: list[float] | None = None
    low_vps: float | None = None       # value per share at the low FCFF bound
    high_vps: float | None = None
    tornado_rows: list[dict] = field(default_factory=list)
    implied_growth: float | None = None


def load_record(doc_id: str) -> DocumentRecord:
    return next(
        DocumentRecord(**r)
        for r in json.loads(MANIFEST.read_text(encoding="utf-8"))
        if r["doc_id"] == doc_id
    )


def load_overrides(doc_id: str) -> dict[str, Override]:
    return {
        name: Override(**payload)
        for name, payload in json.loads(
            OVERRIDES.read_text(encoding="utf-8")
        ).get(doc_id, {}).items()
    }


class MarketDriftError(RuntimeError):
    """A per-filing block redefines an input that must be held identical."""


def load_market(doc_id: str) -> dict[str, MarketAssumption]:
    """Merge the shared market inputs with this filing's own.

    data/market.json separates inputs that MUST be identical across filers -
    risk-free rate, ERP, terminal growth, the unlevered industry beta - from
    those that legitimately differ per company: country risk premium, debt
    spread, share price. Holding the first group constant is what makes the
    cross-company comparison measure the businesses rather than the method
    choice (CLAUDE.md, "Cross-company comparability"; docs/adr/0001).

    Before this split the file was keyed by doc_id alone and the four blocks
    carried those inputs identically by DISCIPLINE, with nothing to stop one
    from drifting. Something already had: LYFT_FY2025 cited a different
    Damodaran source string for the same 0.81 beta, naming the sector table
    without its cash-corrected column - the column the 0.81 actually comes
    from (ISSUES.md #21).

    A per-filing block that redefines a shared key raises rather than
    quietly winning, so the structure enforces what discipline used to.
    """
    payload = json.loads(MARKET.read_text(encoding="utf-8"))
    shared = payload.get("shared", {})
    per_filing = payload.get("per_filing", {}).get(doc_id, {})

    collisions = sorted(set(shared) & set(per_filing))
    if collisions:
        raise MarketDriftError(
            f"{doc_id} redefines shared market input(s) {collisions} in its "
            "per_filing block. These are held identical across every filer on "
            "purpose; a per-filing override would make the cross-company "
            "comparison measure the choice instead of the businesses. Change "
            "the shared value if the method changed, and say so in its "
            "rationale."
        )

    return {
        name: MarketAssumption(**entry)
        for name, entry in {**shared, **per_filing}.items()
    }


def extract_facts(record: DocumentRecord, on_target=None) -> tuple[list, list]:
    """Extract every resolved target, reporting each one AS it completes.

    on_target fires inside the loop, immediately after each target, so a CLI
    can show progress during a cold-cache run instead of sitting silent and
    then printing everything at once.

    Returns accepted and rejected separately. Rejections are never used in a
    derivation - they are returned so a caller can SHOW what failed which
    gate. A rejection silently dropped here is a gate that fired invisibly.
    """
    facts, rejected_all = [], []
    for key, target, question, required in resolve_targets(record):
        if target.startswith("UNRESOLVED"):
            if on_target:
                on_target(TargetResult(key=key, target=target, skipped=True))
            continue
        accepted, rejected, _ = extract(record, target, question, target_key=key)
        if on_target:
            on_target(TargetResult(
                key=key, target=target, skipped=False,
                accepted=len(accepted), rejected=len(rejected),
            ))
        facts.extend(accepted)
        rejected_all.extend(rejected)
    return facts, rejected_all


def range_position(price: float, low: float, high: float) -> str:
    """Describe where a market price sits relative to a value-per-share
    range - inside it, or how far outside on either side. "Inside" is
    measured as a share of the range's own width; outside either end is
    measured as a plain ratio to that end, since there is no range width
    left to measure against beyond it.
    """
    if low <= price <= high:
        span = high - low
        pct = (price - low) / span * 100 if span else 0.0
        return f"inside the range, {pct:.1f}% of the way up"
    if price > high:
        pct = (price / high - 1) * 100 if high else float("inf")
        return f"{pct:.1f}% ABOVE the top of the range"
    pct = (1 - price / low) * 100 if low else float("inf")
    return f"{pct:.1f}% BELOW the bottom of the range"


def value_filing(
    doc_id: str, market_price: float | None = None, on_target=None
) -> ValuationRun:
    """Value one filing end to end.

    Raises BlockedError when a required assumption is blocked, BridgeError
    when DCF inputs cannot be assembled, and DCFConsistencyError when the
    engine's own guards reject the inputs. None of those is smoothed over
    here: a valuation built on a blocked input looks exactly like one built
    on evidence.
    """
    record = load_record(doc_id)

    targets: list[TargetResult] = []

    def collect(target_result: TargetResult) -> None:
        targets.append(target_result)
        if on_target:
            on_target(target_result)

    facts, rejected = extract_facts(record, on_target=collect)

    overrides = load_overrides(doc_id)
    market = load_market(doc_id)

    ranges = {a.name: a for a in derive_all(facts, overrides)}
    blocked = [a for a in ranges.values() if a.status == "blocked"]
    if blocked:
        raise BlockedError(blocked, facts=facts, rejected=rejected)

    wacc = None
    wacc_error = None
    beta_base = None
    beta_bounds = None
    try:
        wacc = build_wacc(ranges, market)
    except BridgeError as exc:
        wacc_error = str(exc)

    if wacc:
        market["discount_rate"] = MarketAssumption(
            name="discount_rate", value=wacc.wacc, unit="decimal",
            as_of=market["risk_free_rate"].as_of, source="derived bottom-up",
            rationale=" | ".join(wacc.notes[:3]),
        )

        # Once the discount rate is derived, a hand-picked band around it is
        # arbitrary and hides the component actually driving it. Bounds come
        # from rerunning WACC at the beta bounds instead.
        beta_base = market["unlevered_industry_beta"].value
        beta_bounds = []
        for factor in BETA_BOUND_FACTORS:
            trial = dict(market)
            trial["unlevered_industry_beta"] = market["unlevered_industry_beta"].model_copy(
                update={"value": beta_base * factor}
            )
            beta_bounds.append(build_wacc(ranges, trial).wacc)

    bridged = build_dcf_inputs(ranges, market)

    if beta_bounds:
        bridged.tornado_ranges["discount_rate"] = (beta_bounds[0], beta_bounds[1])

    result = run_dcf(bridged.inputs)

    low_vps = high_vps = None
    bound = bridged.base_cash_flow_bound
    if bound["available"]:
        low_trial, high_trial = deepcopy(bridged.inputs), deepcopy(bridged.inputs)
        low_trial.base_cash_flow = bound["low_fcff"]
        high_trial.base_cash_flow = bound["high_fcff"]
        low_vps = run_dcf(low_trial).value_per_share
        high_vps = run_dcf(high_trial).value_per_share

    tornado_rows = []
    if bridged.tornado_ranges:
        tornado_rows = sensitivity_tornado(bridged.inputs, bridged.tornado_ranges)

    implied_growth = None
    if market_price:
        implied_growth = reverse_dcf(bridged.inputs, market_price)

    return ValuationRun(
        doc_id=doc_id,
        market_price=market_price,
        record=record,
        targets=targets,
        ranges=ranges,
        bridged=bridged,
        result=result,
        facts=facts,
        rejected=rejected,
        wacc=wacc,
        wacc_error=wacc_error,
        beta_base=beta_base,
        wacc_at_beta_bounds=beta_bounds,
        low_vps=low_vps,
        high_vps=high_vps,
        tornado_rows=tornado_rows,
        implied_growth=implied_growth,
    )
