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

from ..extraction import extract
from ..extraction.targets import resolve_targets
from ..infra.paths import DATA_DIR
from ..schemas import DocumentRecord
from ..schemas.valuation import AssumptionRange, MarketAssumption, Override
from .accounting_quality import AccountingQualityReport, assess_accounting_quality
from .robustness import RobustnessReport, assess_robustness
from .assumptions import derive_all
from .contract import PATH_DCF, PATH_PER_SHARE, PATH_WACC, Status, evaluate
from .contract_adapter import observe, row_for_range
from .bridge import BridgeError, build_dcf_inputs
from .wacc import build_wacc

from .dcf_engine import (
    DCFConsistencyError,
    reverse_dcf,
    run_dcf,
    sensitivity_tornado,
)

MANIFEST = DATA_DIR / "manifest.json"
OVERRIDES = DATA_DIR / "overrides.json"
MARKET = DATA_DIR / "market.json"

BETA_BOUND_FACTORS = (0.75, 1.45)


class ContractBlockedError(RuntimeError):
    """The required-data contract refused the run.

    Carries the ContractResult, not a message: a caller has to be able
    to print the field-by-field table, and re-deriving it from a
    formatted string is how a second implementation starts.
    """

    def __init__(self, result, facts=None, rejected=None) -> None:
        self.result = result
        self.facts = facts or []
        self.rejected = rejected or []
        super().__init__(
            f"DATA CONTRACT BLOCKED: {'; '.join(result.reasons)}")


class BlockedError(RuntimeError):
    """A required assumption is blocked, so no valuation is defensible.

    Carries the blocked ranges themselves, not just a message: a caller has
    to be able to report WHICH quantity blocked and why, and re-deriving
    that from a formatted string is how a second implementation starts.

    It also carries the evidence extracted before the block, because a block
    is not protection if the evidence it hands the analyst is incomplete
    (ISSUES.md #26). An analyst reads that evidence to decide the override
    that unblocks the run.

    ``reasons`` maps each blocked quantity to a typed contract Reason, so a
    caller can tell an ambiguous collision (two captions matched one query)
    from a policy block (net_debt awaiting a stated cash-and-debt policy)
    from a bad unit, without parsing rationale prose. This block fires
    BEFORE the contract gate - a blocked derivation never reaches evaluate()
    - so the cause would otherwise survive only as free text. The classifier
    is contract_adapter.row_for_range, the exact one the gate uses, so the
    two surfaces cannot disagree about what a blocked range means.
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
        self.reasons = {a.name: row_for_range(a.name, a).reason for a in blocked}
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
    contract: object = None            # ContractResult, from contract.py
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
    # Why a bound is None, in the engine's own words. None when the bound
    # valued cleanly. A caller that prints "NOT_APPLICABLE" without saying
    # which period and which guard has moved the problem, not reported it.
    low_vps_note: str | None = None
    high_vps_note: str | None = None
    tornado_rows: list[dict] = field(default_factory=list)
    implied_growth: float | None = None
    # The merged market inputs this run was built on (shared + per_filing),
    # kept so the robustness layer can assess input quality (staleness,
    # UNVERIFIED markers, extreme values) without re-reading the file.
    market: dict = field(default_factory=dict)
    forecast_years: int = 10
    # P4: accounting-quality diagnostics. DIAGNOSTIC ONLY - computed after the
    # DCF is finished and with no path back into any valuation number. An
    # AccountingQualityReport, from accounting_quality.py.
    accounting_quality: object | None = None
    # P5: valuation-robustness diagnostics. DIAGNOSTIC ONLY - re-runs the pure
    # dcf_engine on COPIES to measure anchor / terminal-value / assumption
    # sensitivity and forward-reverse consistency. A RobustnessReport.
    robustness: object | None = None


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

    # THE CONTRACT GATE. The execution order is load-bearing and asserted
    # against this source by test_contract_hardening and exercised end to
    # end, case by case, by test_contract_adversarial:
    #
    #   requirements declared (contract.REQUIREMENTS, import time)
    #     -> extraction        (extract_facts)
    #     -> verification      (gates.validate, inside extract)
    #     -> derivation        (derive_all)
    #     -> blocked-derivation check   (raises BlockedError, with typed
    #                                    .reasons, before the gate)
    #     -> contract construction      (observe: run state -> rows)
    #     -> period / unit / integrity validation (inside evaluate:
    #        _period_problems delegates to identities.check_period_alignment;
    #        row_for_* reject unconvertible units)
    #     -> CONTRACT GATE     (evaluate -> Status.BLOCKED raises
    #                            ContractBlockedError)
    #     -> WACC              (build_wacc)
    #     -> FCFF bridge       (build_dcf_inputs)
    #     -> DCF               (run_dcf / sensitivity_tornado / reverse_dcf)
    #
    # The invariant: no MISSING, AMBIGUOUS, PERIOD_MISMATCH, INVALID_UNIT or
    # DEPENDENCY_UNMET observation can reach build_wacc, build_dcf_inputs or
    # run_dcf. Spies on all three prove they never execute on a blocked
    # contract, with a negative control proving the spies would fire on a
    # valid run.
    #
    # The blocked-assumption check above can only see quantities derive_all
    # produced; this gate sees quantities the contract EXPECTED and nothing
    # produced, which is the state gates.py structurally cannot hold
    # (ISSUES.md #27) - a row absent from every quote makes no group for
    # check_coverage to iterate over.
    contract = evaluate(
        observe(ranges, market, market_price=market_price),
        paths=(PATH_DCF, PATH_PER_SHARE, PATH_WACC),
    )
    if contract.status is Status.BLOCKED:
        raise ContractBlockedError(contract, facts=facts, rejected=rejected)

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
    low_vps_note = high_vps_note = None
    bound = bridged.base_cash_flow_bound
    if bound["available"]:
        low_trial, high_trial = deepcopy(bridged.inputs), deepcopy(bridged.inputs)
        low_trial.base_cash_flow = bound["low_fcff"]
        high_trial.base_cash_flow = bound["high_fcff"]
        # These two were unguarded, and they are the ONLY unguarded run_dcf
        # call on a base the caller did not choose: all fourteen other re-runs
        # in the codebase already catch DCFConsistencyError and report the
        # guard's message (tests/test_negative_base_fcff.py walks the AST and
        # fails on a fifteenth). Under Guard 0d a disclosed year with negative
        # FCFF would have taken the whole valuation down here.
        #
        # No module names in this comment on purpose: three regression tests
        # assert that the diagnostic layers are NOT wired into this
        # orchestrator by grepping this file's source, and a comment naming
        # one of them fails that check exactly as an import would.
        #
        # It must not. The base case is the LATEST period and is untouched;
        # only the BOUND is unreportable, and an unreportable bound is a
        # finding, not a failure. The note is carried so the CLI and the UI
        # can say which period and why instead of printing a bare "None".
        for label in ("low", "high"):
            trial = low_trial if label == "low" else high_trial
            try:
                value, note = run_dcf(trial).value_per_share, None
            except DCFConsistencyError as exc:
                value, note = None, str(exc)
            if label == "low":
                low_vps, low_vps_note = value, note
            else:
                high_vps, high_vps_note = value, note

    tornado_rows = []
    if bridged.tornado_ranges:
        tornado_rows = sensitivity_tornado(bridged.inputs, bridged.tornado_ranges)

    implied_growth = None
    if market_price:
        implied_growth = reverse_dcf(bridged.inputs, market_price)

    # P4 - accounting quality. Runs LAST, on the verified facts and the
    # pipeline's own per-period FCFF (bridge._per_period_fcff, not recomputed).
    # It reads; it returns a report; nothing above depends on it and nothing
    # below it exists. `result`, `bridged` and `wacc` are already final. A
    # regression test (test_accounting_quality.TestP4CannotTouchValuation)
    # replaces this call with an all-HIGH-impact report and asserts the
    # per-share value is byte-identical. cash_one_offs is analyst-supplied
    # evidence and has no filing today; the parameter is the wiring point.
    fcff_by_period = (bound.get("fcff_by_period")
                      if isinstance(bound, dict) and bound.get("available") else None)
    # P4.7: the diagnostic layer must never take down an otherwise-valid
    # valuation. `result`, `bridged` and `wacc` are already final and are NOT
    # recomputed here. An exception is captured with provenance and surfaced
    # as NOT_ASSESSED - it is never swallowed into a silent "no issue".
    try:
        accounting_quality = assess_accounting_quality(
            facts, fcff_by_period=fcff_by_period, cash_one_offs=(), doc_id=doc_id)
    except Exception as exc:  # noqa: BLE001 - deliberately broad; see docstring
        accounting_quality = AccountingQualityReport.not_assessed(
            doc_id, f"diagnostic layer failed ({type(exc).__name__}: {exc})")

    partial = ValuationRun(
        doc_id=doc_id, market_price=market_price, record=record, targets=targets,
        ranges=ranges, contract=contract, bridged=bridged, result=result,
        facts=facts, rejected=rejected, wacc=wacc, wacc_error=wacc_error,
        beta_base=beta_base, wacc_at_beta_bounds=beta_bounds, low_vps=low_vps,
        high_vps=high_vps, low_vps_note=low_vps_note, high_vps_note=high_vps_note,
        tornado_rows=tornado_rows, implied_growth=implied_growth,
        market=market, forecast_years=10,
        accounting_quality=accounting_quality,
    )
    # P5: robustness diagnostics. Same contract as P4.7 - runs LAST, reads the
    # finished run, re-runs the PURE engine on copies, and can never take down
    # or alter the valuation. An exception -> NOT_ASSESSED with provenance.
    try:
        partial.robustness = assess_robustness(partial)
    except Exception as exc:  # noqa: BLE001
        partial.robustness = RobustnessReport.not_assessed(
            doc_id, f"robustness layer failed ({type(exc).__name__}: {exc})")
    return partial
