"""P7 - market-implied expectations (investor decision layer).

Phases 0, 3-9, 12-13, 17-20, 23: implied uniform growth (reuse of reverse
DCF), the new closed-form implied-base-FCFF solve, FCFF-anchor scenarios,
WACC / terminal-growth sensitivity, deterministic expectations-vs-evidence
classification, anti-circularity, 16 adversarial cases, cross-sector, and
byte-identity of the base DCF. Every test fails if its safeguard is removed.
"""
import math

import pytest

import aleph.valuation.pipeline as pipeline
from aleph.valuation.dcf_engine import (
    DCFConsistencyError,
    DCFInputs,
    reverse_dcf,
    run_dcf,
)
from aleph.valuation.market_expectations import (
    ExpectationsLevel,
    ExpectationsVsEvidence,
    Solvability,
    anchor_scenarios,
    assess_market_expectations,
    implied_base_fcff,
    implied_uniform_growth,
    terminal_growth_sensitivity,
    wacc_sensitivity,
    _classify_level,
    _classify_vs_evidence,
)

UBER24, UBER25 = ("UBER_FY2024", 76.95), ("UBER_FY2025", 79.00)
LYFT25, DASH25 = ("LYFT_FY2025", 17.35), ("DASH_FY2025", 215.00)


def mk(**kw):
    d = dict(cash_flow_type="FCFF", base_cash_flow=1000.0,
             growth_rates=[0.15, 0.13, 0.11, 0.09, 0.07, 0.05, 0.04, 0.035, 0.03, 0.025],
             terminal_growth=0.025, discount_rate=0.09, net_debt=200.0,
             shares_outstanding=500.0, assumptions=[])
    d.update(kw)
    return DCFInputs(**d)


# =========================================================================== #
# Phase 0 / 3 - implied uniform growth IS the reverse DCF, nothing new
# =========================================================================== #
class TestImpliedUniformGrowth:
    def test_it_equals_reverse_dcf(self):
        inp = mk()
        price = run_dcf(inp).value_per_share
        iq = implied_uniform_growth(inp, price)
        assert iq.value == pytest.approx(reverse_dcf(inp, price), abs=1e-9)

    def test_the_solved_variable_is_labelled_uniform_growth_not_revenue_growth(self):
        iq = implied_uniform_growth(mk(), 30.0)
        assert "uniform" in iq.solved_variable.lower()
        assert "revenue" not in iq.solved_variable.lower()
        assert "revenue" not in iq.equation.lower()

    def test_provenance_records_the_fixed_inputs_and_tolerance(self):
        iq = implied_uniform_growth(mk(discount_rate=0.088), 25.0)
        assert iq.fixed_inputs["discount_rate"] == 0.088
        assert iq.fixed_inputs["terminal_growth"] == 0.025
        assert iq.fixed_inputs["forecast_years"] == 10
        assert "base_cash_flow" in iq.fixed_inputs
        assert iq.tolerance > 0
        assert iq.solution_low == -0.50 and iq.solution_high == 1.00

    def test_non_finite_price_is_not_solvable(self):
        iq = implied_uniform_growth(mk(), float("nan"))
        assert iq.solvability is Solvability.NOT_SOLVABLE and iq.value is None

    def test_unattainable_price_is_not_solvable(self):
        # a price no uniform growth in [-50%, +100%] can reach
        v_hi = run_dcf(mk(growth_rates=[1.0] * 10)).value_per_share
        iq = implied_uniform_growth(mk(), v_hi * 100)
        assert iq.solvability is Solvability.NOT_SOLVABLE


# =========================================================================== #
# Phase 6 - the NEW closed-form implied base FCFF
# =========================================================================== #
class TestImpliedBaseFCFF:
    def test_b_star_reproduces_the_market_price(self):
        inp = mk()
        target = 4.0
        iq = implied_base_fcff(inp, target)
        assert iq.solvability is Solvability.SOLVED
        trial = mk(base_cash_flow=iq.value)
        assert run_dcf(trial).value_per_share == pytest.approx(target, rel=1e-6)

    def test_value_per_share_is_linear_in_base_fcff(self):
        # implied FCFF must scale linearly with the target price (fixed path)
        inp = mk()
        a = implied_base_fcff(inp, 10.0).value
        b = implied_base_fcff(inp, 20.0).value
        c = implied_base_fcff(inp, 30.0).value
        assert (b - a) == pytest.approx(c - b, rel=1e-6)

    def test_it_differs_from_reverse_dcf(self):
        # reverse_dcf solves growth; implied_base_fcff solves level
        inp = mk()
        price = run_dcf(inp).value_per_share * 1.3
        g = reverse_dcf(inp, price)
        b = implied_base_fcff(inp, price).value
        assert g is not None and b is not None
        assert b != pytest.approx(inp.base_cash_flow)     # level moved
        # feeding the implied level back with the ORIGINAL faded path hits price
        assert run_dcf(mk(base_cash_flow=b)).value_per_share == pytest.approx(price, rel=1e-6)

    def test_implied_base_fcff_can_be_negative_without_fabricating(self):
        # a price low enough that implied equity is negative
        inp = mk(net_debt=5000.0)
        iq = implied_base_fcff(inp, 0.01)
        # either a genuine (possibly tiny/negative) solve, or NOT_SOLVABLE -
        # never a positive number invented to look reasonable
        if iq.solvability is Solvability.SOLVED:
            assert run_dcf(mk(net_debt=5000.0, base_cash_flow=iq.value)
                           ).value_per_share == pytest.approx(0.01, abs=1e-3)

    def test_non_finite_price_is_not_solvable(self):
        assert implied_base_fcff(mk(), float("inf")).solvability is Solvability.NOT_SOLVABLE

    def test_zero_implied_level_is_not_solvable(self):
        # a price that makes implied equity exactly -net_debt drives B* to 0,
        # which run_dcf's Guard 0c would reject - report NOT_SOLVABLE, not B*=0
        inp = mk(net_debt=200.0, shares_outstanding=500.0)
        price = -inp.net_debt / inp.shares_outstanding          # -> B* == 0
        assert implied_base_fcff(inp, price).solvability is Solvability.NOT_SOLVABLE

    def test_closed_form_is_exact_not_approximate(self):
        # the removed verify-by-re-run step was provably dead: value/share is
        # exactly affine in B, so B* reproduces the price to FP precision
        inp = mk()
        for target in (3.0, 12.5, 40.0, 100.0):
            b = implied_base_fcff(inp, target).value
            got = run_dcf(mk(base_cash_flow=b)).value_per_share
            assert got == pytest.approx(target, rel=1e-9)

    def test_equation_and_fixed_inputs_on_record(self):
        iq = implied_base_fcff(mk(), 12.0)
        assert "B*" in iq.equation and "Phi" in iq.equation
        assert iq.solved_variable.startswith("B")
        assert iq.fixed_inputs["growth_path"].startswith("faded")


# =========================================================================== #
# Phase 4 - implied growth under each FCFF anchor, no anchor chosen
# =========================================================================== #
class TestAnchorScenarios:
    def test_lower_anchor_needs_higher_implied_growth(self):
        inp = mk()
        price = run_dcf(inp).value_per_share
        rows = anchor_scenarios(inp, price, [("latest", 1000.0),
                                             ("sustainable_low", 700.0),
                                             ("sustainable_high", 1000.0)])
        by = {r.anchor_label: r for r in rows}
        assert by["latest"].implied_uniform_growth == pytest.approx(
            by["sustainable_high"].implied_uniform_growth, abs=1e-6)
        # a lower FCFF anchor must require MORE growth to reach the same price
        assert by["sustainable_low"].implied_uniform_growth > by["latest"].implied_uniform_growth
        assert by["sustainable_low"].delta_vs_latest_anchor > 0

    def test_missing_anchor_is_not_solvable_not_skipped(self):
        rows = anchor_scenarios(mk(), 20.0, [("latest", 1000.0),
                                             ("sustainable_low", None),
                                             ("sustainable_central", 0.0)])
        by = {r.anchor_label: r for r in rows}
        assert by["sustainable_low"].solvability is Solvability.NOT_SOLVABLE
        assert by["sustainable_central"].solvability is Solvability.NOT_SOLVABLE
        assert by["latest"].solvability is Solvability.SOLVED


# =========================================================================== #
# Phase 12 / 13 - sensitivity uses the EXISTING bands, never new assumptions
# =========================================================================== #
class TestSensitivity:
    def test_wacc_sensitivity_uses_the_supplied_bounds(self):
        inp = mk()
        price = run_dcf(inp).value_per_share
        rows = wacc_sensitivity(inp, price, (0.08, 0.10))
        assert [r.param_value for r in rows] == [0.08, inp.discount_rate, 0.10]
        # higher WACC => the same price needs MORE forecast growth
        gs = {r.label: r.implied_uniform_growth for r in rows}
        assert gs["low"] < gs["base"] < gs["high"]

    def test_terminal_growth_sensitivity_uses_the_supplied_bounds(self):
        inp = mk()
        price = run_dcf(inp).value_per_share
        rows = terminal_growth_sensitivity(inp, price, (0.015, 0.029))
        assert [r.param_value for r in rows] == [0.015, inp.terminal_growth, 0.029]
        # higher terminal growth => LESS forecast growth needed for the price
        gs = {r.label: r.implied_uniform_growth for r in rows}
        assert gs["low"] > gs["base"] > gs["high"]

    def test_sensitivity_base_row_matches_the_unshifted_implied_growth(self):
        # the "base" row must solve against the ACTUAL market price and the
        # ACTUAL base parameter - a target or param shift would break this
        inp = mk()
        price = run_dcf(inp).value_per_share * 1.4
        base_g = implied_uniform_growth(inp, price).value
        w = {r.label: r for r in wacc_sensitivity(inp, price, (0.08, 0.10))}
        t = {r.label: r for r in terminal_growth_sensitivity(inp, price, (0.015, 0.029))}
        assert w["base"].implied_uniform_growth == pytest.approx(base_g, abs=1e-6)
        assert t["base"].implied_uniform_growth == pytest.approx(base_g, abs=1e-6)

    def test_a_bound_that_violates_a_guard_is_not_solvable_not_a_crash(self):
        inp = mk(terminal_growth=0.025)
        rows = terminal_growth_sensitivity(inp, 20.0, (0.02, 0.05))  # 5% > 3% cap
        assert rows[-1].solvability is Solvability.NOT_SOLVABLE


# =========================================================================== #
# Phase 8 / 16 - deterministic classification, explicit rules, no score
# =========================================================================== #
class TestClassification:
    def test_implied_fcff_inside_the_range_is_aligned(self):
        st, _ = _classify_vs_evidence(500.0, 300.0, 700.0, "SUPPORTED_RANGE")
        assert st is ExpectationsVsEvidence.MARKET_EXPECTATIONS_ALIGNED

    def test_implied_fcff_above_the_range_is_above_evidence(self):
        st, _ = _classify_vs_evidence(900.0, 300.0, 700.0, "SUPPORTED_RANGE")
        assert st is ExpectationsVsEvidence.MARKET_EXPECTATIONS_ABOVE_EVIDENCE

    def test_implied_fcff_below_the_range_is_below_evidence(self):
        st, _ = _classify_vs_evidence(100.0, 300.0, 700.0, "SUPPORTED_RANGE")
        assert st is ExpectationsVsEvidence.MARKET_EXPECTATIONS_BELOW_EVIDENCE

    def test_p6_insufficient_evidence_propagates(self):
        st, _ = _classify_vs_evidence(500.0, None, None, "INSUFFICIENT_EVIDENCE")
        assert st is ExpectationsVsEvidence.INSUFFICIENT_EVIDENCE

    def test_not_solvable_implied_fcff_short_circuits_without_raising(self):
        # implied FCFF NOT_SOLVABLE but a P6 range exists -> INSUFFICIENT, not
        # a TypeError from comparing None to a number
        st, _ = _classify_vs_evidence(None, 300.0, 700.0, "SUPPORTED_RANGE")
        assert st is ExpectationsVsEvidence.INSUFFICIENT_EVIDENCE
        lv, _ = _classify_level(500.0, None, None, None, "INSUFFICIENT_EVIDENCE", 400.0)
        # graded against latest only, explicitly labelled
        assert lv is ExpectationsLevel.EXPECTATIONS_DEMANDING     # 500/400 = 1.25x

    def test_level_modest_demanding_extreme_thresholds(self):
        # central 500, range [300, 700]
        assert _classify_level(450.0, 300, 500, 700, "SUPPORTED_RANGE", 500)[0] \
            is ExpectationsLevel.EXPECTATIONS_MODEST
        assert _classify_level(650.0, 300, 500, 700, "SUPPORTED_RANGE", 500)[0] \
            is ExpectationsLevel.EXPECTATIONS_DEMANDING
        assert _classify_level(2000.0, 300, 500, 700, "SUPPORTED_RANGE", 500)[0] \
            is ExpectationsLevel.EXPECTATIONS_EXTREME

    def test_not_solvable_implied_fcff_is_not_classified(self):
        lv, _ = _classify_level(None, 300, 500, 700, "SUPPORTED_RANGE", 500)
        assert lv is ExpectationsLevel.NOT_CLASSIFIED


# =========================================================================== #
# Phase 17 - anti-circularity: market price never leaks into the base DCF
# =========================================================================== #
class TestAntiCircularity:
    @pytest.mark.needs_filings
    def test_assess_does_not_mutate_the_run(self):
        run = pipeline.value_filing(*UBER24)
        before = (run.result.value_per_share, run.bridged.inputs.base_cash_flow,
                  list(run.bridged.inputs.growth_rates), run.bridged.inputs.discount_rate,
                  run.implied_growth)
        assess_market_expectations(run)
        assess_market_expectations(run, market_price=1234.0)
        after = (run.result.value_per_share, run.bridged.inputs.base_cash_flow,
                 list(run.bridged.inputs.growth_rates), run.bridged.inputs.discount_rate,
                 run.implied_growth)
        assert before == after

    def test_pipeline_has_no_market_expectations_import(self):
        import inspect
        assert "market_expectations" not in inspect.getsource(pipeline)

    def test_solvers_deepcopy_and_never_touch_the_caller_inputs(self):
        inp = mk()
        snap = (inp.base_cash_flow, list(inp.growth_rates), inp.discount_rate,
                inp.terminal_growth)
        implied_uniform_growth(inp, 25.0)
        implied_base_fcff(inp, 25.0)
        anchor_scenarios(inp, 25.0, [("latest", 1000.0), ("x", 800.0)])
        wacc_sensitivity(inp, 25.0, (0.08, 0.10))
        terminal_growth_sensitivity(inp, 25.0, (0.015, 0.029))
        assert (inp.base_cash_flow, list(inp.growth_rates), inp.discount_rate,
                inp.terminal_growth) == snap


# =========================================================================== #
# Phase 10 / 11 - live filings
# =========================================================================== #
class TestLiveFilings:
    @pytest.mark.needs_filings
    def test_uber_fy2024_price_mainly_needs_current_fcff_to_persist(self):
        run = pipeline.value_filing(*UBER24)
        me = assess_market_expectations(run)
        assert me.implied_base_fcff.solvability is Solvability.SOLVED
        # implied FCFF is close to the latest anchor, not a growth heroics story
        assert me.implied_base_fcff.value == pytest.approx(me.base_fcff, rel=0.05)
        assert me.vs_evidence is ExpectationsVsEvidence.MARKET_EXPECTATIONS_ALIGNED
        assert me.level is ExpectationsLevel.EXPECTATIONS_DEMANDING

    @pytest.mark.needs_filings
    def test_uber_fy2025_market_prices_fcff_below_the_evidence_floor(self):
        run = pipeline.value_filing(*UBER25)
        me = assess_market_expectations(run)
        assert me.implied_base_fcff.value < me.sustainable_fcff_low
        assert me.vs_evidence is ExpectationsVsEvidence.MARKET_EXPECTATIONS_BELOW_EVIDENCE
        assert me.level is ExpectationsLevel.EXPECTATIONS_MODEST

    @pytest.mark.needs_filings
    def test_lyft_fy2025_market_does_not_require_the_wc_inflated_fcff(self):
        run = pipeline.value_filing(*LYFT25)
        me = assess_market_expectations(run)
        # implied FCFF well below the latest reconstructed 810, and negative
        # implied growth
        assert me.implied_base_fcff.value < 0.6 * me.base_fcff
        assert me.implied_uniform_growth.value < 0
        assert me.vs_evidence is ExpectationsVsEvidence.MARKET_EXPECTATIONS_ALIGNED
        assert me.level is ExpectationsLevel.EXPECTATIONS_MODEST

    @pytest.mark.needs_filings
    def test_dash_fy2025_cannot_be_graded_against_evidence(self):
        run = pipeline.value_filing(*DASH25)
        me = assess_market_expectations(run)
        assert me.sustainable_status == "INSUFFICIENT_EVIDENCE"
        assert me.vs_evidence is ExpectationsVsEvidence.INSUFFICIENT_EVIDENCE
        # implied growth is still computable and the interpretation names it
        assert me.implied_uniform_growth.solvability is Solvability.SOLVED
        assert "INSUFFICIENT_EVIDENCE" in me.interpretation

    @pytest.mark.needs_filings
    def test_interpretation_never_says_buy_or_sell_or_cheap(self):
        import re
        for doc, px in (UBER24, UBER25, LYFT25, DASH25):
            me = assess_market_expectations(pipeline.value_filing(doc, px))
            low = me.interpretation.lower()
            for banned in ("buy", "sell", "hold", "cheap", "expensive",
                           "undervalued", "overvalued", "confidence", "score",
                           "rating", "signal"):
                assert not re.search(rf"\b{banned}\b", low), (doc, banned)


# =========================================================================== #
# Phase 23 - the base DCF is byte-identical with P7 present
# =========================================================================== #
class TestRegression:
    @pytest.mark.needs_filings
    def test_point_values_unchanged(self):
        for doc, px, want in (("UBER_FY2024", 76.95, 77.08),
                              ("UBER_FY2025", 79.00, 119.95),
                              ("LYFT_FY2025", 17.35, 49.06),
                              ("DASH_FY2025", 215.00, 124.27)):
            run = pipeline.value_filing(doc, px)
            assess_market_expectations(run)     # run the layer
            r = run.result
            assert r.value_per_share == pytest.approx(want, abs=0.01), doc
            # EV / equity / WACC / base FCFF / terminal value identities intact
            i = run.bridged.inputs
            assert r.equity_value == pytest.approx(
                r.enterprise_or_equity_value - i.net_debt, rel=1e-9)
            assert r.pv_terminal > 0 and math.isfinite(r.pv_terminal)
            assert 0.07 < run.wacc.wacc < 0.11


# =========================================================================== #
# Phase 18 - 16 adversarial cases
# =========================================================================== #
class TestAdversarial:
    def _iq(self, inp, price):
        return (implied_uniform_growth(inp, price), implied_base_fcff(inp, price))

    def test_01_price_equals_forward_dcf(self):
        inp = mk()
        p = run_dcf(inp).value_per_share
        g, b = self._iq(inp, p)
        assert g.value == pytest.approx(0.0, abs=0.02) or g.solvability is Solvability.SOLVED
        assert b.value == pytest.approx(inp.base_cash_flow, rel=1e-4)

    def test_02_price_far_below_dcf(self):
        inp = mk()
        g, b = self._iq(inp, run_dcf(inp).value_per_share * 0.2)
        assert b.value < inp.base_cash_flow

    def test_03_price_far_above_dcf(self):
        inp = mk()
        g, b = self._iq(inp, run_dcf(inp).value_per_share * 3.0)
        assert b.value > inp.base_cash_flow

    def test_04_negative_base_fcff(self):
        """REWRITTEN for Guard 0d. This used to price the input off its own
        forward DCF and check the solvers stayed coherent. There is no
        forward price any more - the engine refuses a negative base - and the
        property that matters is unchanged and stronger: the solvers must
        return NOT_SOLVABLE, never crash and never fabricate a level."""
        inp = mk(base_cash_flow=-400.0, growth_rates=[0.2] * 10)
        with pytest.raises(DCFConsistencyError, match="NOT_APPLICABLE"):
            run_dcf(inp)
        g, b = self._iq(inp, 12.34)          # any target: none is reachable
        assert b.solvability is Solvability.NOT_SOLVABLE
        assert b.value is None
        assert g.solvability is Solvability.NOT_SOLVABLE
        assert g.value is None

    def test_05_zero_base_fcff_multiple_undefined(self):
        # base 0 -> run_dcf raises -> Phi undefined -> NOT_SOLVABLE
        inp = mk(base_cash_flow=1e-9)
        b = implied_base_fcff(inp, 20.0)
        assert b.solvability in (Solvability.SOLVED, Solvability.NOT_SOLVABLE)

    def test_06_unattainable_implied_fcff_via_bad_multiple(self):
        # g_T >= r makes run_dcf raise -> Phi None -> NOT_SOLVABLE
        inp = mk(discount_rate=0.02, terminal_growth=0.025)
        assert implied_base_fcff(inp, 20.0).solvability is Solvability.NOT_SOLVABLE

    def test_07_unattainable_implied_growth(self):
        v_hi = run_dcf(mk(growth_rates=[1.0] * 10)).value_per_share
        assert implied_uniform_growth(mk(), v_hi * 50).solvability is Solvability.NOT_SOLVABLE

    def test_08_near_wacc_equals_terminal_growth(self):
        inp = mk(discount_rate=0.0255, terminal_growth=0.025)
        g = implied_uniform_growth(inp, 20.0)
        b = implied_base_fcff(inp, 20.0)
        assert g.solvability in (Solvability.SOLVED, Solvability.NOT_SOLVABLE)
        assert b.solvability in (Solvability.SOLVED, Solvability.NOT_SOLVABLE)

    def test_09_high_terminal_dependence(self):
        inp = mk(growth_rates=[0.03] * 10, terminal_growth=0.029, discount_rate=0.06)
        assert implied_base_fcff(inp, run_dcf(inp).value_per_share
                                 ).value == pytest.approx(inp.base_cash_flow, rel=1e-4)

    def test_10_low_terminal_dependence(self):
        inp = mk(growth_rates=[0.5] * 10, terminal_growth=0.025, discount_rate=0.15)
        assert implied_base_fcff(inp, run_dcf(inp).value_per_share
                                 ).value == pytest.approx(inp.base_cash_flow, rel=1e-4)

    def test_11_high_sustainable_current_divergence(self):
        # anchor at 30% of latest still solves for implied growth
        inp = mk()
        rows = anchor_scenarios(inp, run_dcf(inp).value_per_share,
                                [("latest", 1000.0), ("sust_low", 300.0)])
        assert rows[1].solvability in (Solvability.SOLVED, Solvability.NOT_SOLVABLE)

    def test_12_low_sustainable_current_divergence(self):
        inp = mk()
        rows = anchor_scenarios(inp, run_dcf(inp).value_per_share,
                                [("latest", 1000.0), ("sust_low", 950.0)])
        assert rows[1].implied_uniform_growth is not None

    def test_13_zero_or_negative_equity(self):
        inp = mk(net_debt=1_000_000.0)   # equity deeply negative at any FCFF
        b = implied_base_fcff(inp, 0.01)
        assert b.solvability in (Solvability.SOLVED, Solvability.NOT_SOLVABLE)

    def test_14_extreme_wacc(self):
        inp = mk(discount_rate=0.6)
        b = implied_base_fcff(inp, 5.0)
        if b.solvability is Solvability.SOLVED:
            assert run_dcf(mk(discount_rate=0.6, base_cash_flow=b.value)
                           ).value_per_share == pytest.approx(5.0, rel=1e-4)

    def test_15_extreme_share_count(self):
        inp = mk(shares_outstanding=1e12)
        b = implied_base_fcff(inp, 0.001)
        assert b.solvability in (Solvability.SOLVED, Solvability.NOT_SOLVABLE)

    def test_16_insufficient_historical_evidence(self):
        st, _ = _classify_vs_evidence(500.0, None, None, "NOT_ASSESSED")
        assert st is ExpectationsVsEvidence.INSUFFICIENT_EVIDENCE


# =========================================================================== #
# Phase 20 - cross-sector: no assumption of positive growth / FCFF / equity /
# high terminal value / constant regime
# =========================================================================== #
class TestCrossSector:
    SECTORS = {
        "mature": dict(base_cash_flow=2000.0, growth_rates=[0.03] * 10,
                       terminal_growth=0.025, discount_rate=0.08),
        "saas_hypergrowth": dict(base_cash_flow=200.0, growth_rates=[0.35] * 10,
                                 terminal_growth=0.025, discount_rate=0.11),
        "marketplace": dict(base_cash_flow=700.0, growth_rates=[0.2] * 10,
                            terminal_growth=0.025, discount_rate=0.10),
        "industrial": dict(base_cash_flow=1200.0, growth_rates=[0.04] * 10,
                           terminal_growth=0.02, discount_rate=0.085),
        "infrastructure": dict(base_cash_flow=900.0, growth_rates=[0.03] * 10,
                               terminal_growth=0.025, discount_rate=0.07),
        "cyclical_trough": dict(base_cash_flow=300.0, growth_rates=[0.1] * 10,
                                terminal_growth=0.02, discount_rate=0.09),
        "recovery": dict(base_cash_flow=-200.0, growth_rates=[0.4] * 10,
                         terminal_growth=0.025, discount_rate=0.10),
        "negative_fcff_growth": dict(base_cash_flow=-500.0, growth_rates=[0.3] * 10,
                                     terminal_growth=0.025, discount_rate=0.10),
    }

    # Spelled twice on purpose: a class-body comprehension cannot see other
    # class attributes, only its own iterable.
    NEGATIVE_SECTORS = ("recovery", "negative_fcff_growth")

    @pytest.mark.parametrize(
        "name",
        [n for n in SECTORS if n not in ("recovery", "negative_fcff_growth")])
    def test_sector_solvers_are_coherent_or_not_solvable(self, name):
        inp = mk(**self.SECTORS[name])
        price = run_dcf(inp).value_per_share    # a self-consistent target
        g = implied_uniform_growth(inp, price)
        b = implied_base_fcff(inp, price)
        # at its own forward price the implied base FCFF must return the anchor
        assert b.solvability is Solvability.SOLVED
        assert b.value == pytest.approx(inp.base_cash_flow, rel=1e-4)
        # implied uniform growth at the faded-path price is solvable and finite
        assert g.solvability is Solvability.SOLVED
        assert math.isfinite(g.value)

    @pytest.mark.parametrize("name", NEGATIVE_SECTORS)
    def test_negative_anchor_sectors_have_no_forward_price_to_solve_against(
            self, name):
        """The two sectors with a negative anchor are kept in SECTORS, not
        deleted: they are still the shapes this solver has to survive. What
        changed is that they no longer have a self-consistent forward price -
        Guard 0d refuses to produce one - so the whole chain must come back
        NOT_SOLVABLE rather than crash."""
        inp = mk(**self.SECTORS[name])
        with pytest.raises(DCFConsistencyError, match="NOT_APPLICABLE"):
            run_dcf(inp)
        assert implied_base_fcff(inp, 25.0).solvability is Solvability.NOT_SOLVABLE
        assert implied_uniform_growth(inp, 25.0).solvability is Solvability.NOT_SOLVABLE

    def test_negative_fcff_sector_does_not_fabricate_a_positive_expectation(self):
        """The assertion used to be `b.value < 0` - honest, because the
        implied LEVEL was negative. The honest answer is now that there is no
        level: Phi is computed from a reference run that the engine refuses,
        so nothing is implied at all. Both are refusals to fabricate; this one
        happens earlier."""
        inp = mk(**self.SECTORS["negative_fcff_growth"])
        b = implied_base_fcff(inp, 25.0)
        assert b.solvability is Solvability.NOT_SOLVABLE
        assert b.value is None
