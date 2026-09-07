"""P2: historical FCFF series, starting-point scenarios, anchor sensitivity."""
import pytest

from aleph.valuation.dcf_engine import DCFInputs
from aleph.valuation.historical_fcff import (
    Comparability,
    ComparabilityEvent,
    FCFFPeriod,
    Flag,
    build_series,
    value_under_scenarios,
)


def period(fy, fcff, unit="USD millions"):
    return FCFFPeriod(fiscal_year=fy, reported_cfo=0.0, reported_capex=0.0,
                      reported_fcff=fcff, normalised_fcff=fcff,
                      normalisation_status="normalised", unit=unit)


def series(**years):
    return build_series([period(fy, v) for fy, v in years.items()])


def inputs(base=5512.0):
    return DCFInputs(
        cash_flow_type="FCFF", base_cash_flow=base,
        growth_rates=[0.175, 0.158, 0.142, 0.125, 0.108,
                      0.092, 0.075, 0.058, 0.042, 0.025],
        terminal_growth=0.025, discount_rate=0.0872,
        net_debt=3000.0, shares_outstanding=2100.0)


class TestVocabulary:
    def test_only_normalised_carries_that_word(self):
        """An arithmetic mean is not an economic normalisation. The whole
        workstream exists because those were conflated."""
        h = series(FY2022=100, FY2023=100, FY2024=100)
        fields = h.__dataclass_fields__
        assert "historical_mean_fcff" in fields
        assert "historical_median_fcff" in fields
        assert not any("normali" in f and "mean" in f for f in fields)
        assert not any("normali" in f and "median" in f for f in fields)

    def test_sensitivity_is_never_called_a_confidence_interval(self):
        h = series(FY2022=100, FY2023=200, FY2024=300)
        s = value_under_scenarios(inputs(), h)
        assert any("not a confidence interval" in n for n in s.notes)


class TestCriticalAcceptance:
    """Spec section 13: 100 / 100 / 100 / 300."""

    def test_the_system_claims_no_normalised_answer(self):
        h = series(FY2021=100, FY2022=100, FY2023=100, FY2024=300)
        assert h.latest_normalised_fcff == 300
        assert h.historical_median_fcff == 100
        assert h.historical_mean_fcff == 150
        # Neither statistic is presented as "the" normalised FCFF.
        assert h.latest_normalised_fcff != h.historical_median_fcff
        assert h.latest_normalised_fcff != h.historical_mean_fcff

    def test_all_three_anchors_are_offered_and_none_selected(self):
        h = series(FY2021=100, FY2022=100, FY2023=100, FY2024=300)
        names = {p.name for p in h.starting_points()}
        assert names == {"latest_normalized", "historical_median", "historical_mean"}
        s = value_under_scenarios(inputs(), h)
        assert len(s.scenarios) == 3
        assert all(sc.value_per_share is not None for sc in s.scenarios)

    def test_the_jump_is_flagged_as_a_possible_regime_change(self):
        """Prior years in a 0% band, latest +200% above their median."""
        h = series(FY2021=100, FY2022=100, FY2023=100, FY2024=300)
        assert Flag.POTENTIAL_BUSINESS_REGIME_CHANGE in h.flags
        assert any("equally consistent with one exceptional year" in n
                   for n in h.notes)


class TestStructuralGrowth:
    """Spec section 14: 50 / 70 / 100 / 150."""

    def test_a_trend_is_surfaced(self):
        h = series(FY2021=50, FY2022=70, FY2023=100, FY2024=150)
        assert Flag.HISTORICAL_TREND_PRESENT in h.flags

    def test_the_median_is_not_treated_as_superior(self):
        """It is offered beside the others with its own downside stated, not
        preferred because it happens to lower the valuation."""
        h = series(FY2021=50, FY2022=70, FY2023=100, FY2024=150)
        median_point = next(p for p in h.starting_points()
                            if p.name == "historical_median")
        assert "a state the company has left" in median_point.rationale
        assert "STATISTIC" in median_point.basis

    def test_the_trend_is_not_extrapolated_into_growth(self):
        h = series(FY2021=50, FY2022=70, FY2023=100, FY2024=150)
        assert any("NOT extrapolated into growth" in n for n in h.notes)


class TestRegimeChangeWithEvidence:
    """Spec section 15: 50 / 55 / 60 / 150 with supplied structural evidence."""

    def test_supplied_evidence_lowers_comparability(self):
        event = ComparabilityEvent(
            fiscal_year="FY2024", kind="acquisition",
            description="acquired a business doubling the addressable market",
            source="10-K Note 3")
        h = build_series([period("FY2021", 50), period("FY2022", 55),
                          period("FY2023", 60), period("FY2024", 150)],
                         comparability_events=(event,))
        assert h.comparability is Comparability.LOW
        assert Flag.HISTORICAL_COMPARABILITY_LOW in h.flags
        assert any("no statistic over them repairs that" in n for n in h.notes)

    def test_comparability_is_never_inferred_from_the_numbers(self):
        """The negative control. The same series without supplied evidence
        must NOT claim low comparability - a jump and an acquisition look
        identical in a list of four numbers."""
        h = series(FY2021=50, FY2022=55, FY2023=60, FY2024=150)
        assert h.comparability is Comparability.UNKNOWN
        assert Flag.HISTORICAL_COMPARABILITY_LOW not in h.flags
        assert any("Absence of supplied events is absence of evidence" in n
                   for n in h.notes)

    def test_comparability_is_never_high_without_evidence(self):
        """UNKNOWN, not HIGH. Nothing here can establish that acquisitions and
        accounting changes did not happen."""
        h = series(FY2022=100, FY2023=101, FY2024=102)
        assert h.comparability is not Comparability.HIGH


class TestNegativeAndZero:
    def test_all_positive_is_unremarkable(self):
        h = series(FY2022=100, FY2023=110, FY2024=120)
        assert Flag.MIXED_SIGN_HISTORY not in h.flags
        assert Flag.VALUATION_METHOD_LIMITATION not in h.flags

    def test_one_negative_year_is_flagged_as_mixed_sign(self):
        h = series(FY2022=-957, FY2023=1927, FY2024=5512)
        assert Flag.MIXED_SIGN_HISTORY in h.flags

    def test_a_negative_median_surfaces_a_method_limitation(self):
        h = series(FY2022=-100, FY2023=-50, FY2024=10)
        assert Flag.NEGATIVE_CENTRAL_TENDENCY in h.flags
        assert Flag.VALUATION_METHOD_LIMITATION in h.flags
        assert any("not silently switched" in n for n in h.notes)

    def test_all_negative_history(self):
        h = series(FY2022=-100, FY2023=-200, FY2024=-300)
        assert Flag.VALUATION_METHOD_LIMITATION in h.flags

    def test_zero_fcff_does_not_crash_the_deviation(self):
        h = series(FY2022=0, FY2023=0, FY2024=0)
        assert h.latest_deviation_from_median is None
        assert h.sufficient

    def test_a_rejected_scenario_is_reported_with_its_guard(self):
        """A negative anchor the engine refuses must be visible, not dropped."""
        h = series(FY2022=-100, FY2023=-50, FY2024=10)
        s = value_under_scenarios(inputs(), h)
        assert len(s.scenarios) == 3
        assert all(sc.value_per_share is not None or sc.rejected
                   for sc in s.scenarios)


class TestDataContract:
    def test_two_periods_is_insufficient(self):
        """A median over two points is a midpoint; a mean is the same number.
        Neither is a statistic worth reporting."""
        h = build_series([period("FY2023", 100), period("FY2024", 300)])
        assert h.sufficient is False
        assert Flag.HISTORICAL_DATA_INSUFFICIENT in h.flags
        assert h.historical_median_fcff is None

    def test_missing_years_are_never_estimated(self):
        h = build_series([period("FY2023", 100), period("FY2024", 300)])
        assert len(h.periods) == 2
        assert "not estimated" in h.reason

    def test_mixed_units_are_refused(self):
        h = build_series([period("FY2022", 100), period("FY2023", 100),
                          period("FY2024", 100, unit="USD thousands")])
        assert h.sufficient is False
        assert "not a series" in h.reason

    def test_periods_are_ordered_regardless_of_input_order(self):
        h = build_series([period("FY2024", 300), period("FY2022", 100),
                          period("FY2023", 200)])
        assert [p.fiscal_year for p in h.periods] == ["FY2022", "FY2023", "FY2024"]


class TestUber29Regression:
    """Spec section 12. The case that motivated the whole workstream."""

    UBER_FY2024 = {"FY2022": -957, "FY2023": 1927, "FY2024": 5512}
    UBER_FY2025 = {"FY2023": 1927, "FY2024": 5512, "FY2025": 8285}

    def test_the_series_matches_the_filings(self):
        h = series(**{k: v for k, v in self.UBER_FY2024.items()})
        assert h.latest_normalised_fcff == 5512
        assert h.historical_median_fcff == 1927

    def test_anchor_choice_moves_uber_fy2024_by_98_percent(self):
        h = series(**self.UBER_FY2024)
        s = value_under_scenarios(inputs(), h)
        assert s.percentage_range > 0.90
        assert any("HIGH_ANCHOR_SENSITIVITY" in n for n in s.notes)

    def test_the_two_filings_disagree_under_every_anchor(self):
        """The finding P2 produces, and the reason it does not resolve #29.

        Anchoring on the median makes the year-over-year instability WORSE,
        not better. #29 measured the same thing for averages. No anchor
        available here removes the disagreement.

        Both filings are run through ONE fixed set of DCF inputs, so the only
        thing varying is the FCFF anchor. That isolates the anchor effect at
        +51%, below the +56% the two real runs show, because the real runs
        also differ in net debt, share count and WACC. An earlier version of
        this test asserted 56% and was comparing two different things.
        """
        a = value_under_scenarios(inputs(), series(**self.UBER_FY2024))
        b = value_under_scenarios(inputs(), series(**self.UBER_FY2025))

        def by(sens, name):
            return next(s.value_per_share for s in sens.scenarios
                        if s.starting_point.name == name)

        latest_move = by(b, "latest_normalized") / by(a, "latest_normalized") - 1
        median_move = by(b, "historical_median") / by(a, "historical_median") - 1
        assert latest_move == pytest.approx(0.512, abs=0.01)
        assert median_move > latest_move, (
            "the median anchor must be shown to be MORE unstable, not less")


class TestAnchorSensitivity:
    def test_high_sensitivity_is_flagged_above_the_threshold(self):
        h = series(FY2022=100, FY2023=100, FY2024=1000)
        s = value_under_scenarios(inputs(), h)
        assert s.percentage_range > 0.50
        assert any("HIGH_ANCHOR_SENSITIVITY" in n for n in s.notes)

    def test_low_sensitivity_is_not_flagged(self):
        """The negative control: a stable series must not trip it."""
        h = series(FY2022=100, FY2023=102, FY2024=101)
        s = value_under_scenarios(inputs(), h)
        assert s.percentage_range < 0.50
        assert not any("HIGH_ANCHOR_SENSITIVITY" in n for n in s.notes)

    def test_no_scenario_is_selected_as_the_answer(self):
        h = series(FY2022=100, FY2023=200, FY2024=300)
        s = value_under_scenarios(inputs(), h)
        assert not hasattr(s, "chosen")
        assert not hasattr(s, "fair_value")
        assert len(s.scenarios) == 3

    def test_the_dcf_itself_is_untouched_by_scenario_valuation(self):
        """Each scenario replaces only base_cash_flow."""
        base = inputs()
        h = series(FY2022=100, FY2023=200, FY2024=300)
        value_under_scenarios(base, h)
        assert base.base_cash_flow == 5512.0
        assert base.discount_rate == 0.0872
