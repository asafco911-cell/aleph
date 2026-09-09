"""P3 final adversarial run: the eight cases, driven through the real pipeline.

Every blocked case here calls ``pipeline.value_filing`` - not ``evaluate`` in
isolation - with spies on ``build_wacc``, ``build_dcf_inputs`` and ``run_dcf``.
The assertion that matters in each is the same: when the contract blocks, none
of the three downstream valuation functions runs. ``test_the_spies_fire_on_a_
clean_run`` is the negative control; without it a renamed spy target would make
every "calls == []" assertion vacuous.

The perturbations are deterministic monkeypatches of ``derive_all`` output or
``load_market``, never real bad data - the point is the pipeline's response to
a bad input, reproducibly, on the cached UBER_FY2024 extraction.
"""
import pytest

import aleph.valuation.pipeline as pipeline
from aleph.valuation.contract import (
    PATH_DCF,
    PATH_HISTORICAL,
    PATH_PER_SHARE,
    PATH_WACC,
    REQUIREMENTS,
    Observed,
    Reason,
    State,
    Status,
    evaluate,
    requirements_for,
)
from aleph.valuation.contract_adapter import row_for_series
from aleph.valuation.pipeline import BlockedError, ContractBlockedError

DOC = "UBER_FY2024"
PRICE = 76.95
ANCHOR = 77.08
DERIVED_LATER = {r.field for r in REQUIREMENTS if r.depends_on}
OK = (Status.PASS, Status.PASS_WITH_WARNINGS)


class _DownstreamReached(RuntimeError):
    """Raised by a spy the instant a downstream valuation function is entered."""


def _spy_downstream(monkeypatch):
    """Replace every post-gate valuation function with a recorder that also
    aborts. A blocked contract must raise before any of these; a clean run
    must reach ``build_wacc`` first."""
    calls: list[str] = []

    def make(name):
        def spy(*_a, **_k):
            calls.append(name)
            raise _DownstreamReached(name)
        return spy

    for name in ("build_wacc", "build_dcf_inputs", "run_dcf"):
        monkeypatch.setattr(pipeline, name, make(name))
    return calls


def _patch_ranges(monkeypatch, mutate):
    """Run the real derivation, then let ``mutate`` edit the {name: range} dict
    in place before the pipeline sees it."""
    real = pipeline.derive_all

    def fake(facts, overrides):
        by_name = {a.name: a for a in real(facts, overrides)}
        mutate(by_name)
        return list(by_name.values())

    monkeypatch.setattr(pipeline, "derive_all", fake)


def _drop_market_key(monkeypatch, key):
    real = pipeline.load_market
    monkeypatch.setattr(
        pipeline, "load_market",
        lambda doc_id: {k: v for k, v in real(doc_id).items() if k != key},
    )


def _reprice_period(by_name, field, period):
    r = by_name[field]
    obs = [o.model_copy(update={"period": period}) for o in r.observations]
    by_name[field] = r.model_copy(update={"observations": obs})


# --------------------------------------------------------------------------- #
# The negative control comes first: it gives every "calls == []" its teeth.
# --------------------------------------------------------------------------- #
class TestNegativeControl:
    @pytest.mark.needs_filings
    def test_the_spies_fire_on_a_clean_run(self, monkeypatch):
        calls = _spy_downstream(monkeypatch)
        with pytest.raises(_DownstreamReached, match="build_wacc"):
            pipeline.value_filing(DOC, PRICE)
        assert calls == ["build_wacc"], (
            "a clean contract must reach build_wacc - if it does not, the "
            "blocked-case assertions below prove nothing")


# --------------------------------------------------------------------------- #
# Case 1 - a required field the extractor never returned.
# --------------------------------------------------------------------------- #
class TestCase1MissingRequiredField:
    @pytest.mark.needs_filings
    def test_omitted_sbc_blocks_missing_and_stops_the_pipeline(self, monkeypatch):
        calls = _spy_downstream(monkeypatch)
        _patch_ranges(monkeypatch, lambda d: d.pop("stock_based_compensation"))

        with pytest.raises(ContractBlockedError) as exc:
            pipeline.value_filing(DOC, PRICE)

        result = exc.value.result
        assert result.status is Status.BLOCKED
        assert result.row("stock_based_compensation").state is State.MISSING
        assert result.row("stock_based_compensation").reason is Reason.MISSING
        assert PATH_DCF in result.blocked_paths
        assert calls == []


# --------------------------------------------------------------------------- #
# Case 2 - two conflicting observations for one quantity.
# --------------------------------------------------------------------------- #
class TestCase2ConflictingObservations:
    """The collision is caught upstream of the gate (BlockedError), which the
    prompt accepts. The requirement is that the CAUSE survives: the final
    error must identify the ambiguity, not just report BLOCKED."""

    def _make_ambiguous(self, d):
        d["net_debt"] = d["net_debt"].model_copy(update={
            "status": "blocked",
            "rationale": (
                "ambiguous fact selection: FY2024: 'Restricted cash' and "
                "'Cash, cash equivalents and restricted cash' both match"),
        })

    @pytest.mark.needs_filings
    def test_ambiguity_is_named_in_the_final_error(self, monkeypatch):
        calls = _spy_downstream(monkeypatch)
        _patch_ranges(monkeypatch, self._make_ambiguous)

        with pytest.raises(BlockedError) as exc:
            pipeline.value_filing(DOC, PRICE)

        assert exc.value.reasons["net_debt"] is Reason.AMBIGUOUS, (
            "BLOCKED reached the caller with the ambiguity cause erased")
        assert calls == []

    @pytest.mark.needs_filings
    def test_a_plain_policy_block_is_not_mislabelled_ambiguous(self, monkeypatch):
        """Negative control for the classifier: net_debt's ordinary block
        (awaiting a cash-and-debt policy) must not read as AMBIGUOUS."""
        _spy_downstream(monkeypatch)

        def plain_block(d):
            d["net_debt"] = d["net_debt"].model_copy(update={
                "status": "blocked",
                "rationale": "net debt requires a stated cash and debt policy",
            })

        _patch_ranges(monkeypatch, plain_block)
        with pytest.raises(BlockedError) as exc:
            pipeline.value_filing(DOC, PRICE)
        assert exc.value.reasons["net_debt"] is Reason.DERIVATION_BLOCKED


# --------------------------------------------------------------------------- #
# Case 3 - a value that arrives in a unit the system cannot convert.
# --------------------------------------------------------------------------- #
class TestCase3WrongUnit:
    @pytest.mark.needs_filings
    def test_unconvertible_unit_blocks_invalid_unit_and_stops(self, monkeypatch):
        calls = _spy_downstream(monkeypatch)
        _patch_ranges(monkeypatch, lambda d: d.__setitem__(
            "operating_cash_flow",
            d["operating_cash_flow"].model_copy(update={"unit": "widgets"})))

        with pytest.raises(ContractBlockedError) as exc:
            pipeline.value_filing(DOC, PRICE)

        row = exc.value.result.row("operating_cash_flow")
        assert row.state is State.BLOCKED
        assert row.reason is Reason.INVALID_UNIT
        assert exc.value.result.status is Status.BLOCKED
        assert calls == []


# --------------------------------------------------------------------------- #
# Case 4 - required inputs that do not describe the same period.
# --------------------------------------------------------------------------- #
class TestCase4WrongPeriod:
    @pytest.mark.needs_filings
    def test_capex_a_year_off_blocks_period_mismatch_and_stops(self, monkeypatch):
        calls = _spy_downstream(monkeypatch)
        _patch_ranges(monkeypatch,
                      lambda d: _reprice_period(d, "capex", "FY2019"))

        with pytest.raises(ContractBlockedError) as exc:
            pipeline.value_filing(DOC, PRICE)

        result = exc.value.result
        assert result.row("capex").reason is Reason.PERIOD_MISMATCH
        assert result.row("operating_cash_flow").reason is Reason.PERIOD_MISMATCH
        assert any("PERIOD_MISMATCH" in r for r in result.reasons)
        assert calls == []


# --------------------------------------------------------------------------- #
# Case 5 - a genuine zero. Evidence, not an absence: the run must complete.
# --------------------------------------------------------------------------- #
class TestCase5ValidZero:
    @pytest.mark.needs_filings
    def test_zero_sbc_is_verified_not_missing_and_the_run_completes(
        self, monkeypatch
    ):
        def zero_sbc(d):
            r = d["stock_based_compensation"]
            obs = [o.model_copy(update={"value": 0.0}) for o in r.observations]
            d["stock_based_compensation"] = r.model_copy(update={
                "low": 0.0, "base": 0.0, "high": 0.0, "observations": obs})

        _patch_ranges(monkeypatch, zero_sbc)
        run = pipeline.value_filing(DOC, PRICE)

        assert run.contract.status in OK
        sbc = run.contract.row("stock_based_compensation")
        assert sbc.state in (State.VERIFIED, State.DERIVED)
        assert sbc.value == 0.0
        assert run.result.value_per_share > 0


# --------------------------------------------------------------------------- #
# Case 6 - an analyst override. Permitted, labelled, and never filing evidence.
# This is how UBER_FY2024 runs already; it doubles as the 77.08 anchor guard.
# --------------------------------------------------------------------------- #
class TestCase6AnalystOverride:
    @pytest.mark.needs_filings
    def test_overrides_are_labelled_and_the_run_reaches_the_anchor(self):
        run = pipeline.value_filing(DOC, PRICE)

        assert run.contract.status in OK
        assert run.result.value_per_share == pytest.approx(ANCHOR, abs=0.01)
        assert any("analyst override" in n for n in run.contract.notes)
        overridden = {r.field for r in run.contract.rows if r.override}
        assert {"effective_tax_rate", "net_debt"} <= overridden
        for field in overridden:
            # an override carries its own reason, separate from any filing value
            assert run.contract.row(field).override_reason


# --------------------------------------------------------------------------- #
# Case 7 - too few periods for a historical FCFF series.
# The historical path is a separate diagnostic: value_filing fixes its gate to
# (DCF, PER_SHARE, WACC) and never selects PATH_HISTORICAL, so this is exercised
# at the gate directly rather than through value_filing. Wiring it into the main
# run would be a contract redesign, which this pass explicitly does not do.
# --------------------------------------------------------------------------- #
class TestCase7InsufficientHistory:
    def _full_set(self, paths):
        return {r.field: Observed(r.field, State.VERIFIED, value=1.0,
                                  unit="USD millions")
                for r in requirements_for(paths)
                if r.field not in DERIVED_LATER}

    def test_one_period_series_blocks_insufficient_history(self):
        paths = (PATH_DCF, PATH_PER_SHARE, PATH_WACC, PATH_HISTORICAL)
        observed = self._full_set(paths)
        observed["fcff_by_period"] = row_for_series("fcff_by_period", {
            "available": True, "fcff_by_period": {"FY2024": 1.0}})

        result = evaluate(observed, paths=paths)

        row = result.row("fcff_by_period")
        assert result.status is Status.BLOCKED
        assert row.reason is Reason.INSUFFICIENT_HISTORY
        assert "HISTORICAL_DATA_INSUFFICIENT" in row.detail
        assert PATH_HISTORICAL in result.blocked_paths

    def test_three_periods_clears_it(self):
        paths = (PATH_DCF, PATH_PER_SHARE, PATH_WACC, PATH_HISTORICAL)
        observed = self._full_set(paths)
        observed["fcff_by_period"] = row_for_series("fcff_by_period", {
            "available": True,
            "fcff_by_period": {"FY2022": 1.0, "FY2023": 2.0, "FY2024": 3.0}})
        assert evaluate(observed, paths=paths).status in OK


# --------------------------------------------------------------------------- #
# Case 8 - a WACC market input the run cannot supply.
# --------------------------------------------------------------------------- #
class TestCase8MissingWACCDependency:
    @pytest.mark.needs_filings
    def test_absent_debt_spread_blocks_wacc_and_stops(self, monkeypatch):
        calls = _spy_downstream(monkeypatch)
        _drop_market_key(monkeypatch, "debt_spread")

        with pytest.raises(ContractBlockedError) as exc:
            pipeline.value_filing(DOC, PRICE)

        result = exc.value.result
        assert result.status is Status.BLOCKED
        assert result.row("debt_spread").reason is Reason.MISSING
        assert PATH_WACC in result.blocked_paths
        # the derived discount rate cannot stand on a missing input
        assert result.row("discount_rate").state is State.BLOCKED
        assert result.row("discount_rate").reason is Reason.DEPENDENCY_UNMET
        assert calls == []


# --------------------------------------------------------------------------- #
# Lifecycle states: exactly the seven the pipeline can actually observe.
# --------------------------------------------------------------------------- #
class TestLifecycleStates:
    def test_only_the_seven_reachable_states_exist(self):
        assert {s.value for s in State} == {
            "EXPECTED", "VERIFIED", "DERIVED", "MISSING",
            "AMBIGUOUS", "BLOCKED", "NOT_APPLICABLE"}

    def test_located_and_extracted_stay_removed(self):
        """Removed 2026-09-07: the adapter reads post-gate state, so nothing
        observes region resolution or pre-gate return. They return only with a
        real transition that reaches them - not to decorate the CLI."""
        assert not hasattr(State, "LOCATED")
        assert not hasattr(State, "EXTRACTED")
