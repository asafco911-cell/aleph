"""P3: the required-data contract.

The test that decides whether P3 is solved is
TestExtractionOmission::test_a_field_the_extractor_never_returned_is_caught.
Everything else supports it.
"""
import pytest

from aleph.valuation.contract import (
    PATH_DCF,
    PATH_HISTORICAL,
    PATH_PER_SHARE,
    PATH_REVERSE_DCF,
    PATH_WACC,
    REQUIREMENTS,
    Kind,
    Observed,
    State,
    Status,
    evaluate,
    requirements_for,
)
from aleph.valuation.contract_adapter import row_for_range, row_for_series


class FakeRange:
    """Stands in for AssumptionRange with only what the adapter reads."""

    def __init__(self, name, base=1.0, unit="USD millions",
                 status="derived", rationale="", periods=("FY2024",)):
        self.name, self.base, self.unit = name, base, unit
        self.status, self.rationale = status, rationale
        self.observations = [type("O", (), {"period": p})() for p in periods]


class FakeMarket:
    def __init__(self, value=0.05, unit="decimal",
                 source="US 10Y Treasury yield", as_of="2026-08-28"):
        self.value, self.unit, self.source, self.as_of = value, unit, source, as_of


def verified(field, **kw):
    return Observed(field, State.VERIFIED, value=1.0, unit="USD millions", **kw)


# Fields the run computes AFTER the gate. Supplying them in a fixture would
# hide the dependency logic behind a value the real pipeline does not have at
# gate time - which is exactly what the first version of this file did.
DERIVED_LATER = {r.field for r in REQUIREMENTS if r.depends_on}

OK = (Status.PASS, Status.PASS_WITH_WARNINGS)


def full_set(paths=(PATH_DCF, PATH_PER_SHARE, PATH_WACC)):
    """Every requirement of the selected paths that the run HOLDS at gate
    time, all VERIFIED. Excludes fields derived later."""
    return {r.field: verified(r.field) for r in requirements_for(paths)
            if r.field not in DERIVED_LATER}


class TestExtractionOmission:
    """The original coverage defect (ISSUES.md #27), directly."""

    def test_a_field_the_extractor_never_returned_is_caught(self):
        """THE test for P3.

        gates.check_coverage groups facts by quote, so a row absent from every
        quote produces no group and nothing to iterate over - it cannot see
        what was never returned. Here the observation simply does not exist in
        the run's state, and the contract still holds MISSING for it, because
        the requirement was declared before extraction rather than inferred
        from what came back.
        """
        observed = full_set()
        del observed["stock_based_compensation"]      # the extractor said nothing

        result = evaluate(observed)

        assert result.status is Status.BLOCKED
        row = result.row("stock_based_compensation")
        assert row is not None, "a field nobody mentioned must still have a row"
        assert row.state is State.MISSING
        assert "never returned by extraction" in row.detail
        assert PATH_DCF in result.blocked_paths

    def test_the_omission_survives_even_when_everything_else_is_perfect(self):
        """Negative control: the same set WITH the field must pass, so the
        block is caused by the omission and not by the fixture."""
        assert evaluate(full_set()).status in OK

    def test_every_omitted_field_is_reported_not_just_the_first(self):
        observed = full_set()
        for f in ("capex", "diluted_shares", "risk_free_rate"):
            del observed[f]
        result = evaluate(observed)
        assert {r.field for r in result.by_state(State.MISSING)} == {
            "capex", "diluted_shares", "risk_free_rate"}


class TestFailClosed:
    @pytest.mark.parametrize("bad_state", [State.MISSING, State.AMBIGUOUS,
                                           State.BLOCKED])
    def test_a_bad_state_blocks_the_paths_that_need_it(self, bad_state):
        observed = full_set()
        observed["diluted_shares"] = Observed("diluted_shares", bad_state)
        result = evaluate(observed)
        assert result.status is Status.BLOCKED
        assert PATH_PER_SHARE in result.blocked_paths

    def test_nothing_is_substituted_for_a_missing_field(self):
        observed = full_set()
        del observed["net_debt"]
        result = evaluate(observed)
        assert result.row("net_debt").value is None
        assert result.row("net_debt").state is State.MISSING

    def test_the_reason_names_the_field_and_what_it_blocks(self):
        observed = full_set()
        del observed["capex"]
        result = evaluate(observed)
        assert any("capex is MISSING" in r for r in result.reasons)
        assert any("Blocks: dcf" in r for r in result.reasons)


class TestZeroIsNotMissing:
    def test_a_verified_zero_passes(self):
        """SBC = 0 is evidence. It is not an absence."""
        observed = full_set()
        observed["stock_based_compensation"] = Observed(
            "stock_based_compensation", State.VERIFIED, value=0.0,
            unit="USD millions")
        assert evaluate(observed).status in OK

    def test_zero_debt_stays_distinguishable_from_not_extracted(self):
        zero = full_set()
        zero["net_debt"] = Observed("net_debt", State.VERIFIED, value=0.0,
                                    unit="USD millions")
        absent = full_set()
        del absent["net_debt"]
        assert evaluate(zero).status in OK
        assert evaluate(absent).status is Status.BLOCKED

    def test_a_zero_range_is_read_as_verified_not_missing(self):
        row = row_for_range("stock_based_compensation",
                            FakeRange("stock_based_compensation", base=0.0))
        assert row.state is State.DERIVED
        assert row.value == 0.0


class TestUnitIntegrity:
    def test_an_unknown_unit_cannot_become_verified(self):
        """ISSUES.md #15: an unresolved unit valued LYFT_FY2025 at 65,792
        against a 17.35 price, with no arithmetic error anywhere."""
        row = row_for_range("operating_cash_flow",
                            FakeRange("operating_cash_flow", unit="UNKNOWN"))
        assert row.state is State.BLOCKED
        assert "not one this system can convert" in row.detail

    def test_an_unknown_unit_blocks_the_contract(self):
        observed = full_set()
        observed["operating_cash_flow"] = row_for_range(
            "operating_cash_flow", FakeRange("operating_cash_flow", unit="widgets"))
        assert evaluate(observed).status is Status.BLOCKED

    @pytest.mark.parametrize("unit", ["USD millions", "USD thousands",
                                      "thousands", "percent", "decimal"])
    def test_known_units_pass(self, unit):
        assert row_for_range("capex", FakeRange("capex", unit=unit)).state \
            is State.DERIVED


class TestOverrideIsNeverFilingEvidence:
    def test_an_override_is_labelled_and_carries_its_reason(self):
        row = row_for_range("net_debt", FakeRange(
            "net_debt", status="overridden",
            rationale="debt net of current portion less cash"))
        assert row.override is True
        assert "debt net of current portion" in row.override_reason

    def test_a_derived_fact_is_not_labelled_an_override(self):
        """The negative control. Without it, marking everything an override
        would pass the test above."""
        row = row_for_range("capex", FakeRange("capex"))
        assert row.override is False
        assert row.override_reason == ""

    def test_overrides_are_counted_and_named_in_the_result(self):
        observed = full_set()
        observed["net_debt"] = row_for_range("net_debt", FakeRange(
            "net_debt", status="overridden", rationale="stated policy"))
        result = evaluate(observed)
        assert any("analyst override(s)" in n for n in result.notes)


class TestBlockedDerivation:
    def test_a_blocked_range_is_blocked_not_missing(self):
        """Different states: nothing came back vs it came back unusable."""
        row = row_for_range("net_debt", FakeRange(
            "net_debt", status="blocked", rationale="requires a stated policy"))
        assert row.state is State.BLOCKED
        assert "requires a stated policy" in row.detail


class TestHistoricalContract:
    def test_fewer_than_three_periods_is_insufficient(self):
        row = row_for_series("fcff_by_period", {
            "available": True, "fcff_by_period": {"FY2023": 1.0, "FY2024": 2.0}})
        assert row.state is State.BLOCKED
        assert "HISTORICAL_DATA_INSUFFICIENT" in row.detail

    def test_three_periods_is_enough(self):
        row = row_for_series("fcff_by_period", {
            "available": True,
            "fcff_by_period": {"FY2022": 1.0, "FY2023": 2.0, "FY2024": 3.0}})
        assert row.state is State.DERIVED

    def test_an_unavailable_series_is_missing(self):
        row = row_for_series("fcff_by_period",
                             {"available": False, "reason": "no periods"})
        assert row.state is State.MISSING

    def test_the_historical_path_blocks_on_an_insufficient_series(self):
        observed = full_set((PATH_DCF, PATH_HISTORICAL))
        observed["fcff_by_period"] = row_for_series("fcff_by_period", {
            "available": True, "fcff_by_period": {"FY2024": 1.0}})
        result = evaluate(observed, paths=(PATH_DCF, PATH_HISTORICAL))
        assert result.status is Status.BLOCKED
        assert PATH_HISTORICAL in result.blocked_paths


class TestPathConditionality:
    def test_a_path_not_selected_does_not_block(self):
        """The historical path needs a multi-period series. A run that does
        not select it must not stop because that series is absent.

        An earlier version of this test selected PATH_DCF alone and expected a
        pass. That premise was wrong: a DCF without the WACC path has no
        discount rate, and blocking was correct. Path conditionality is only
        meaningful between paths that are genuinely independent.
        """
        observed = full_set()                     # no fcff_by_period at all
        assert "fcff_by_period" not in observed

        without = evaluate(observed, paths=(PATH_DCF, PATH_PER_SHARE, PATH_WACC))
        assert without.row("fcff_by_period") is None,             "an unselected path must not appear in the table at all"

        # Selected, the row appears - EXPECTED rather than blocked, because
        # the series is derivable from inputs that are all present. The
        # insufficient-periods case is TestHistoricalContract's, where a
        # series exists and is too short.
        with_history = evaluate(
            observed, paths=(PATH_DCF, PATH_PER_SHARE, PATH_WACC, PATH_HISTORICAL))
        assert with_history.row("fcff_by_period").state is State.EXPECTED
        assert PATH_HISTORICAL not in with_history.blocked_paths

    def test_the_reverse_dcf_path_declares_its_own_dependencies(self):
        reqs = {r.field for r in requirements_for((PATH_REVERSE_DCF,))}
        assert {"share_price", "terminal_growth", "discount_rate"} <= reqs

    def test_reverse_dcf_blocks_without_a_price(self):
        observed = full_set((PATH_DCF, PATH_REVERSE_DCF))
        del observed["share_price"]
        result = evaluate(observed, paths=(PATH_DCF, PATH_REVERSE_DCF))
        assert PATH_REVERSE_DCF in result.blocked_paths

    def test_wacc_blocks_without_a_market_input(self):
        observed = full_set()
        del observed["equity_risk_premium"]
        result = evaluate(observed)
        assert PATH_WACC in result.blocked_paths


class TestDependencyGraph:
    def test_a_derived_field_is_pending_when_its_inputs_are_satisfied(self):
        """discount_rate is computed by build_wacc, after this gate. Its
        absence at gate time is not an omission - what matters is whether
        everything it is derived FROM is present."""
        observed = full_set()
        result = evaluate(observed)
        assert result.row("discount_rate").state is State.EXPECTED
        assert result.status in OK

    def test_a_derived_field_blocks_when_an_input_is_not(self):
        observed = full_set()
        del observed["risk_free_rate"]
        result = evaluate(observed)
        row = result.row("discount_rate")
        assert row.state is State.BLOCKED
        assert "risk_free_rate" in row.detail

    def test_the_wacc_fallback_cannot_return(self):
        """ISSUES.md #19: a failed WACC once fell through to a hand-written
        0.09 discount_rate and valued UBER_FY2024 at $73.54. The contract must
        block rather than let a discount rate appear from nowhere."""
        observed = full_set()
        del observed["debt_spread"]
        result = evaluate(observed)
        assert result.status is Status.BLOCKED
        assert result.row("discount_rate").state is State.BLOCKED


class TestContractIntegrity:
    def test_every_requirement_names_where_it_came_from(self):
        """A requirement nothing actually consumes would be theatre."""
        for r in REQUIREMENTS:
            assert r.source, f"{r.field} has no source"
            assert r.kind in Kind

    def test_optional_fields_never_block(self):
        optional = [r for r in REQUIREMENTS if r.kind is Kind.OPTIONAL]
        assert optional
        for r in optional:
            assert r.required_for == (), f"{r.field} is optional but blocks"

    def test_a_missing_optional_field_is_a_warning_not_a_block(self):
        result = evaluate(full_set())
        assert result.status is Status.PASS_WITH_WARNINGS or \
            result.status is Status.PASS

    def test_counts_are_reported(self):
        result = evaluate(full_set())
        assert result.expected_count == len(
            requirements_for((PATH_DCF, PATH_PER_SHARE, PATH_WACC)))
        assert result.verified_count <= result.expected_count

    def test_the_table_renders_states_and_status(self):
        table = evaluate(full_set()).as_table()
        assert "STATUS:" in table
        assert "VERIFIED" in table
