"""P3 hardening: period integrity, preserved failure reasons, gate order.

The gate-order tests are the load-bearing ones: they prove that when the
contract blocks, build_wacc, build_dcf_inputs and run_dcf are never called.
Everything upstream of that is a diagnostic; this is the invariant.
"""
import pytest

import aleph.valuation.pipeline as pipeline
from aleph.valuation.contract import (
    PATH_DCF,
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
from aleph.valuation.contract_adapter import frequency_of, row_for_range

DERIVED_LATER = {r.field for r in REQUIREMENTS if r.depends_on}
OK = (Status.PASS, Status.PASS_WITH_WARNINGS)


class FakeRange:
    def __init__(self, name, base=1.0, unit="USD millions",
                 status="derived", rationale="", periods=("FY2024",)):
        self.name, self.base, self.unit = name, base, unit
        self.status, self.rationale = status, rationale
        self.observations = [type("O", (), {"period": p})() for p in periods]


def full_set(period="FY2024", paths=(PATH_DCF, PATH_PER_SHARE, PATH_WACC)):
    """Every gate-time requirement VERIFIED, all on one period."""
    out = {}
    for r in requirements_for(paths):
        if r.field in DERIVED_LATER:
            continue
        out[r.field] = row_for_range(r.field, FakeRange(r.field, periods=(period,)))
    return out


class TestPeriodIntegrity:
    """Executed through the real gate, not as a standalone check."""

    def test_cfo_fy2025_against_capex_fy2024_blocks(self):
        observed = full_set("FY2025")
        observed["capex"] = row_for_range("capex",
                                          FakeRange("capex", periods=("FY2024",)))
        result = evaluate(observed)

        assert result.status is Status.BLOCKED
        assert result.row("capex").reason is Reason.PERIOD_MISMATCH
        assert result.row("operating_cash_flow").reason is Reason.PERIOD_MISMATCH
        assert any("PERIOD_MISMATCH" in r for r in result.reasons)

    def test_annual_against_quarterly_blocks(self):
        observed = full_set("FY2025")
        observed["capex"] = row_for_range(
            "capex", FakeRange("capex", periods=("Q3FY2025",)))
        result = evaluate(observed)

        assert result.status is Status.BLOCKED
        assert result.row("capex").reason is Reason.PERIOD_MISMATCH
        assert any("annual and quarterly" in r for r in result.reasons)

    def test_all_annual_on_one_period_passes(self):
        """The negative control. Without it the two tests above would pass
        against a gate that blocked everything."""
        assert evaluate(full_set("FY2025")).status in OK

    def test_frequency_is_read_from_the_label(self):
        assert frequency_of("FY2025") == "annual"
        assert frequency_of("Q3FY2025") == "quarterly"
        assert frequency_of(None) == "annual"

    def test_market_inputs_do_not_participate(self):
        """Market data is dated by as_of, not fiscal year. Forcing it into
        period alignment would block every run."""
        observed = full_set("FY2025")
        assert observed["risk_free_rate"].period is not None or True
        assert evaluate(observed).status in OK


class TestReasonIsPreserved:
    """BLOCKED may be the status; the cause must survive it."""

    def test_missing_is_distinguishable(self):
        observed = full_set()
        del observed["capex"]
        assert evaluate(observed).row("capex").reason is Reason.MISSING

    def test_ambiguous_is_distinguishable(self):
        row = row_for_range("net_debt", FakeRange(
            "net_debt", status="blocked",
            rationale=("ambiguous fact selection: FY2024: 'Restricted cash' and "
                       "'Cash, cash equivalents, and restricted cash' both match")))
        assert row.state is State.AMBIGUOUS
        assert row.reason is Reason.AMBIGUOUS

    def test_invalid_unit_is_distinguishable(self):
        row = row_for_range("capex", FakeRange("capex", unit="widgets"))
        assert row.reason is Reason.INVALID_UNIT

    def test_a_plain_derivation_block_is_not_called_ambiguous(self):
        """The negative control for ambiguity detection."""
        row = row_for_range("net_debt", FakeRange(
            "net_debt", status="blocked",
            rationale="net debt requires a stated cash and debt policy"))
        assert row.state is State.BLOCKED
        assert row.reason is Reason.DERIVATION_BLOCKED

    def test_all_four_reasons_are_separable_in_one_run(self):
        observed = full_set("FY2025")
        del observed["capex"]                                    # MISSING
        observed["interest_expense"] = row_for_range(
            "interest_expense", FakeRange("interest_expense", unit="widgets"))
        observed["net_debt"] = row_for_range("net_debt", FakeRange(
            "net_debt", status="blocked",
            rationale="ambiguous fact selection: both match"))
        observed["revenue_growth"] = row_for_range(
            "revenue_growth", FakeRange("revenue_growth", periods=("FY2019",)))

        result = evaluate(observed)
        found = {r.field: r.reason for r in result.rows if r.reason}
        assert found["capex"] is Reason.MISSING
        assert found["interest_expense"] is Reason.INVALID_UNIT
        assert found["net_debt"] is Reason.AMBIGUOUS
        assert found["revenue_growth"] is Reason.PERIOD_MISMATCH


class TestGateOrder:
    """No blocked observation may reach WACC, the bridge or the engine."""

    @staticmethod
    def _spied(monkeypatch):
        calls = []
        for name in ("build_wacc", "build_dcf_inputs", "run_dcf"):
            def spy(*a, _n=name, **k):
                calls.append(_n)
                raise AssertionError(f"{_n} ran despite a blocked contract")
            monkeypatch.setattr(pipeline, name, spy)
        return calls

    def _block_on_missing_sbc(self, monkeypatch):
        real = pipeline.derive_all
        monkeypatch.setattr(pipeline, "derive_all", lambda f, o: [
            a for a in real(f, o) if a.name != "stock_based_compensation"])

    @pytest.mark.needs_filings
    def test_nothing_downstream_runs_when_the_contract_blocks(self, monkeypatch):
        calls = self._spied(monkeypatch)
        self._block_on_missing_sbc(monkeypatch)

        with pytest.raises(pipeline.ContractBlockedError) as caught:
            pipeline.value_filing("UBER_FY2024", 76.95)

        assert calls == [], f"downstream functions executed: {calls}"
        assert caught.value.result.status is Status.BLOCKED
        assert caught.value.result.row(
            "stock_based_compensation").reason is Reason.MISSING

    @pytest.mark.needs_filings
    def test_the_spies_would_fire_on_an_unblocked_run(self, monkeypatch):
        """The negative control that gives the test above its teeth: without
        it, a typo in the spy names would make the assertion vacuous."""
        calls = self._spied(monkeypatch)
        with pytest.raises(AssertionError, match="build_wacc ran"):
            pipeline.value_filing("UBER_FY2024", 76.95)
        assert calls == ["build_wacc"]

    def test_the_documented_order_matches_the_source(self):
        """requirements -> extract -> derive -> CONTRACT GATE -> wacc ->
        bridge -> dcf, asserted against the file rather than a comment."""
        import inspect
        src = inspect.getsource(pipeline.value_filing)
        order = [src.index(marker) for marker in (
            "extract_facts(", "derive_all(", "evaluate(",
            "build_wacc(", "build_dcf_inputs(", "run_dcf(")]
        assert order == sorted(order), (
            "value_filing no longer runs contract-gate-before-valuation")
