"""P5 - valuation robustness & economic-correctness audit.

Grouped by the audit phase. The DCF-engine guard tests (Phase 6) and the
isolation tests (Phase 9-equivalent) are the load-bearing ones.
"""
import math

import pytest

import aleph.valuation.pipeline as pipeline
from aleph.valuation.dcf_engine import DCFConsistencyError, DCFInputs, run_dcf
from aleph.valuation.robustness import (
    ANCHOR_SPREAD_HIGH,
    EV_TO_FCFF_SANE_HIGH,
    PER_SHARE_SANE_LOW,
    FailureCategory,
    RobustnessReport,
    Sensitivity,
    Severity,
    assess_robustness,
    categorize_failure,
)


def mk(**kw) -> DCFInputs:
    d = dict(cash_flow_type="FCFF", base_cash_flow=1000.0,
             growth_rates=[0.05] * 10, terminal_growth=0.025,
             discount_rate=0.09, net_debt=100.0, shares_outstanding=1000.0,
             assumptions=[])
    d.update(kw)
    return DCFInputs(**d)


class _Run:
    """Minimal stand-in for ValuationRun that assess_robustness reads."""
    def __init__(self, inputs, *, fcff_by_period=None, market_price=None,
                 implied_growth=None, tornado_rows=None):
        self.doc_id = "SYNTH"
        self.bridged = type("B", (), {
            "inputs": inputs,
            "base_cash_flow_bound": ({"available": True,
                                      "fcff_by_period": fcff_by_period}
                                     if fcff_by_period else {"available": False}),
        })()
        self.result = run_dcf(inputs)
        self.market_price = market_price
        self.implied_growth = implied_growth
        self.tornado_rows = tornado_rows or []


# =========================================================================== #
# Phase 6 - DCF mathematical extremes: fail closed, never NaN/inf/crash
# =========================================================================== #
class TestDCFEngineGuards:
    @pytest.mark.parametrize("kw,frag", [
        (dict(base_cash_flow=0.0), "zero"),
        (dict(base_cash_flow=math.inf), "non-finite"),
        (dict(base_cash_flow=math.nan), "non-finite"),
        (dict(base_cash_flow=-math.inf), "non-finite"),
        (dict(net_debt=math.inf), "non-finite"),
        (dict(net_debt=math.nan), "non-finite"),
        (dict(discount_rate=math.nan), "non-finite"),
        (dict(discount_rate=-1.0, terminal_growth=-1.5), "-100%"),
        (dict(discount_rate=-2.0, terminal_growth=-3.0), "-100%"),
        (dict(shares_outstanding=0.0), "positive"),
        (dict(shares_outstanding=-5.0), "positive"),
        (dict(growth_rates=[0.05, math.inf, 0.05]), "non-finite"),
    ])
    def test_ill_posed_inputs_fail_closed(self, kw, frag):
        with pytest.raises(DCFConsistencyError) as e:
            run_dcf(mk(**kw))
        assert frag in str(e.value)

    @pytest.mark.parametrize("kw", [
        dict(base_cash_flow=1e300),
        dict(base_cash_flow=-500.0),          # negative but finite: engine allows
        dict(base_cash_flow=1e-9),
        dict(discount_rate=1e-6, terminal_growth=-0.01),
    ])
    def test_finite_inputs_give_finite_output(self, kw):
        r = run_dcf(mk(**kw))
        for v in (r.value_per_share, r.enterprise_or_equity_value,
                  r.equity_value, r.pv_terminal, r.pv_explicit, r.terminal_pct):
            assert math.isfinite(v)

    @pytest.mark.needs_filings
    def test_anchor_stays_at_77_08(self):
        # the guards must not perturb the real valuation
        run = pipeline.value_filing("UBER_FY2024", 76.95)
        assert run.result.value_per_share == pytest.approx(77.08, abs=0.01)

    def test_zero_base_is_rejected_by_its_own_guard(self):
        # pins guard 0c specifically: the message must name the zero base,
        # not merely be caught by the downstream total==0 guard.
        with pytest.raises(DCFConsistencyError, match="no cash flow to discount"):
            run_dcf(mk(base_cash_flow=1000.0, growth_rates=[0.0] * 10,
                       terminal_growth=0.025, discount_rate=0.09) if False
                    else mk(base_cash_flow=0.0))

    def test_growth_path_that_zeroes_cash_flow_is_rejected_not_crashed(self):
        # a -100% growth year drives cf to 0 mid-forecast; base != 0 so guard
        # 0c does not fire - the total==0 / non-finite guard must.
        with pytest.raises(DCFConsistencyError, match="collapsed|NOT_SOLVABLE"):
            run_dcf(mk(base_cash_flow=1000.0,
                       growth_rates=[-1.0] + [0.05] * 9))


# =========================================================================== #
# Phase 5 - WACC <= terminal growth must never enter a valid DCF
# =========================================================================== #
class TestWACCTerminalGrowthBoundary:
    @pytest.mark.parametrize("r,g,ok", [
        (0.09, 0.025, True),
        (0.09, 0.089999, False),      # g just below r but > 3% cap
        (0.03, 0.03, False),          # g == r
        (0.03, 0.0300001, False),     # g just above r
        (0.030001, 0.03, True),       # g just below r, both <= 3%
        (0.05, 0.06, False),          # g > r
        (-0.01, -0.02, True),         # negative but g < r <= 3%
    ])
    def test_boundary(self, r, g, ok):
        inp = mk(discount_rate=r, terminal_growth=g)
        if ok:
            assert math.isfinite(run_dcf(inp).value_per_share)
        else:
            with pytest.raises(DCFConsistencyError):
                run_dcf(inp)


# =========================================================================== #
# Phase 3 - FCFF anchor sensitivity is measurable and exposed
# =========================================================================== #
class TestAnchorSensitivity:
    def test_volatile_history_is_high_sensitivity(self):
        run = _Run(mk(base_cash_flow=5000.0),
                   fcff_by_period={"FY2022": -900.0, "FY2023": 1900.0,
                                   "FY2024": 5000.0})
        rob = assess_robustness(run)
        f = rob.get("ANCHOR_SENSITIVITY")
        assert f.sensitivity is Sensitivity.HIGH
        assert f.severity is Severity.HIGH
        methods = {a.method for a in rob.anchor_table}
        assert {"latest", "historical_mean", "historical_median",
                "FY2022", "FY2023", "FY2024"} <= methods
        # no anchor silently promoted
        assert "objectively correct" in f.interpretation

    def test_stable_history_is_low_sensitivity(self):
        run = _Run(mk(base_cash_flow=1000.0),
                   fcff_by_period={"FY2022": 960.0, "FY2023": 1000.0,
                                   "FY2024": 1010.0})
        f = assess_robustness(run).get("ANCHOR_SENSITIVITY")
        assert f.sensitivity is Sensitivity.LOW

    def test_insufficient_history_is_not_a_clean_bill(self):
        run = _Run(mk(), fcff_by_period={"FY2024": 1000.0})
        f = assess_robustness(run).get("ANCHOR_SENSITIVITY")
        assert f.sensitivity is Sensitivity.NOT_APPLICABLE
        assert "limitation, not a clean bill" in f.interpretation

    @pytest.mark.needs_filings
    def test_real_uber_anchor_sensitivity_is_high(self):
        rob = pipeline.value_filing("UBER_FY2024", 76.95).robustness
        f = rob.get("ANCHOR_SENSITIVITY")
        assert f.sensitivity is Sensitivity.HIGH
        vals = {a.method: a.value_per_share for a in rob.anchor_table}
        assert vals["latest"] == pytest.approx(77.08, abs=0.1)
        assert vals["historical_median"] < 40           # the spread is real


# =========================================================================== #
# Phase 7 - terminal value dominance
# =========================================================================== #
class TestTerminalValueDependence:
    def test_tv_dominated_dcf_is_flagged_high(self):
        # flat forecast, thin discount premium over terminal g -> TV is ~90%
        run = _Run(mk(growth_rates=[0.0] * 10, terminal_growth=0.03,
                      discount_rate=0.04))
        f = assess_robustness(run).get("TERMINAL_VALUE_DEPENDENCE")
        assert f.sensitivity is Sensitivity.HIGH
        assert f.numbers["terminal_pct"] > 0.8

    def test_forecast_driven_dcf_is_not_flagged_high(self):
        run = _Run(mk(growth_rates=[0.25] * 10, terminal_growth=0.02,
                      discount_rate=0.12))
        f = assess_robustness(run).get("TERMINAL_VALUE_DEPENDENCE")
        assert f.sensitivity in (Sensitivity.MEDIUM, Sensitivity.LOW)

    @pytest.mark.needs_filings
    def test_real_filings_report_a_tv_share(self):
        for doc, price in (("UBER_FY2024", 76.95), ("LYFT_FY2025", 17.35)):
            f = pipeline.value_filing(doc, price).robustness.get(
                "TERMINAL_VALUE_DEPENDENCE")
            assert 0 < f.numbers["terminal_pct"] < 1


# =========================================================================== #
# Phase 9 - reverse DCF consistency (round trip)
# =========================================================================== #
class TestReverseDCFConsistency:
    def test_solvable_case_round_trips(self):
        inp = mk()
        base = run_dcf(inp).value_per_share
        # pick a market price we know is reachable, then solve for it
        run = _Run(inp, market_price=base * 1.3, implied_growth=None)
        # simulate the pipeline having solved it
        from aleph.valuation.dcf_engine import reverse_dcf
        g = reverse_dcf(inp, base * 1.3)
        run.implied_growth = g
        f = assess_robustness(run).get("REVERSE_DCF_CONSISTENCY")
        assert f.headline == "REVERSE DCF: consistent"
        assert f.numbers["round_trip_error"] <= 0.01
        assert "not an independent check" in f.interpretation

    def test_unsolvable_case_reports_not_solvable(self):
        run = _Run(mk(), market_price=1e9, implied_growth=None)
        f = assess_robustness(run).get("REVERSE_DCF_CONSISTENCY")
        assert f.sensitivity is Sensitivity.NOT_SOLVABLE
        assert "NOT_SOLVABLE" in f.headline
        assert "No implied growth is reported" in f.interpretation

    def test_no_market_price_is_not_run(self):
        run = _Run(mk(), market_price=None)
        f = assess_robustness(run).get("REVERSE_DCF_CONSISTENCY")
        assert f.sensitivity is Sensitivity.NOT_APPLICABLE

    def test_a_wrong_implied_growth_is_reported_inconsistent(self):
        # the pipeline solved (say) 5% but we feed back a value that does NOT
        # reproduce the price -> the round trip must FAIL, not be waved through
        inp = mk()
        base = run_dcf(inp).value_per_share
        run = _Run(inp, market_price=base * 1.3, implied_growth=0.0)  # wrong
        f = assess_robustness(run).get("REVERSE_DCF_CONSISTENCY")
        assert "INCONSISTENT" in f.headline
        assert f.severity is Severity.HIGH
        assert f.numbers["round_trip_error"] > 0.01


# =========================================================================== #
# Phase 10 - value-bridge invariants
# =========================================================================== #
class TestValueBridgeIntegrity:
    def test_normal_bridge_is_consistent(self):
        f = assess_robustness(_Run(mk())).get("VALUE_BRIDGE_INTEGRITY")
        assert f.severity is Severity.INFO
        assert "reconciles" in f.interpretation

    @pytest.mark.parametrize("net_debt", [-5000.0, 0.0, 5000.0])
    def test_bridge_holds_across_net_debt_signs(self, net_debt):
        run = _Run(mk(net_debt=net_debt))
        f = assess_robustness(run).get("VALUE_BRIDGE_INTEGRITY")
        # arithmetic identity always holds; may or may not flag scale
        assert "BROKEN" not in f.headline

    def test_scale_anomaly_is_caught(self):
        # shares in a different scale from FCFF -> per-share value collapses
        run = _Run(mk(base_cash_flow=1000.0, shares_outstanding=1e12,
                      net_debt=0.0))
        f = assess_robustness(run).get("VALUE_BRIDGE_INTEGRITY")
        assert f.severity is Severity.HIGH
        assert "SCALE ANOMALY" in f.headline
        assert abs(f.numbers["value_per_share"]) < PER_SHARE_SANE_LOW

    def test_net_debt_scale_error_is_caught(self):
        # net debt 1000x enterprise value -> scale error
        run = _Run(mk(base_cash_flow=1000.0, net_debt=1e9,
                      shares_outstanding=1000.0))
        f = assess_robustness(run).get("VALUE_BRIDGE_INTEGRITY")
        assert "SCALE ANOMALY" in f.headline

    @pytest.mark.needs_filings
    def test_real_filings_bridge_is_consistent(self):
        for doc, price in (("UBER_FY2024", 76.95), ("LYFT_FY2025", 17.35)):
            f = pipeline.value_filing(doc, price).robustness.get(
                "VALUE_BRIDGE_INTEGRITY")
            assert f.severity is Severity.INFO

    def test_a_broken_ev_equity_link_is_caught_by_that_check_alone(self):
        # equity_value AND value_per_share are internally consistent with each
        # other, but equity != EV - net_debt. Only the EV->equity check can
        # catch this - the per-share check cannot.
        from aleph.valuation.robustness import _value_bridge_integrity
        from aleph.valuation.dcf_engine import DCFResult
        inp = mk(net_debt=100.0, shares_outstanding=1000.0)
        good = run_dcf(inp)
        tampered_equity = good.equity_value + 5000.0
        broken = DCFResult(
            enterprise_or_equity_value=good.enterprise_or_equity_value,
            equity_value=tampered_equity,
            value_per_share=tampered_equity / inp.shares_outstanding,  # consistent
            pv_explicit=good.pv_explicit, pv_terminal=good.pv_terminal,
            terminal_pct=good.terminal_pct, yearly=good.yearly)
        f = _value_bridge_integrity(inp, broken)
        assert f.headline == "VALUE BRIDGE: BROKEN"
        assert "equity_value" in f.detail and "net_debt" in f.detail
        assert f.severity is Severity.HIGH

    def test_a_broken_per_share_is_caught(self):
        from aleph.valuation.robustness import _value_bridge_integrity
        from aleph.valuation.dcf_engine import DCFResult
        inp = mk()
        good = run_dcf(inp)
        broken = DCFResult(
            enterprise_or_equity_value=good.enterprise_or_equity_value,
            equity_value=good.equity_value,
            value_per_share=good.value_per_share * 2,      # tampered
            pv_explicit=good.pv_explicit, pv_terminal=good.pv_terminal,
            terminal_pct=good.terminal_pct, yearly=good.yearly)
        f = _value_bridge_integrity(inp, broken)
        assert f.headline == "VALUE BRIDGE: BROKEN"


# =========================================================================== #
# Phase 4 - economic regime / inflection
# =========================================================================== #
class TestHistoricalRegime:
    @pytest.mark.parametrize("series,expect_high", [
        ({"FY2022": -900.0, "FY2023": 1900.0, "FY2024": 5000.0}, True),   # sign change
        ({"FY2022": 100.0, "FY2023": 105.0, "FY2024": 900.0}, True),      # level break
        ({"FY2022": 100.0, "FY2023": 400.0, "FY2024": 900.0}, False),     # monotonic -> MEDIUM
        ({"FY2022": 960.0, "FY2023": 1000.0, "FY2024": 1010.0}, False),   # comparable
    ])
    def test_regime_flags(self, series, expect_high):
        f = assess_robustness(_Run(mk(), fcff_by_period=series)).get(
            "HISTORICAL_REGIME")
        if expect_high:
            assert f.severity is Severity.HIGH
        else:
            assert f.severity in (Severity.LOW, Severity.MEDIUM)

    def test_comparable_series_is_not_called_validated(self):
        # non-monotonic, tight band, no level break -> "looks comparable"
        f = assess_robustness(_Run(mk(), fcff_by_period={
            "FY2022": 990.0, "FY2023": 1010.0, "FY2024": 1000.0})).get(
            "HISTORICAL_REGIME")
        assert "looks comparable" in f.headline
        assert "NOT a statement that the level is right" in f.interpretation

    def test_short_history_says_untested(self):
        f = assess_robustness(_Run(mk(), fcff_by_period={
            "FY2023": 100.0, "FY2024": 110.0})).get("HISTORICAL_REGIME")
        assert f.sensitivity is Sensitivity.NOT_APPLICABLE
        assert "untested" in f.interpretation


# =========================================================================== #
# Phase 3 (cont.) - negative FCFF method limitation
# =========================================================================== #
class TestMethodLimitation:
    def test_negative_base_fcff_is_flagged_as_method_limitation(self):
        run = _Run(mk(base_cash_flow=-500.0))
        f = assess_robustness(run).get("VALUATION_METHOD_LIMITATION")
        assert f is not None
        assert f.severity is Severity.HIGH
        assert "compounds a loss" in f.interpretation

    def test_positive_base_fcff_has_no_method_limitation_finding(self):
        run = _Run(mk(base_cash_flow=1000.0))
        assert assess_robustness(run).get("VALUATION_METHOD_LIMITATION") is None


# =========================================================================== #
# Phase 14 - failure taxonomy
# =========================================================================== #
class TestFailureTaxonomy:
    def test_each_exception_maps_to_a_category(self):
        from aleph.valuation.pipeline import (
            BlockedError, ContractBlockedError, MarketDriftError)
        from aleph.valuation.bridge import BridgeError

        cat, note = categorize_failure(DCFConsistencyError("NOT_SOLVABLE: zero"))
        assert cat is FailureCategory.NOT_SOLVABLE
        cat, _ = categorize_failure(DCFConsistencyError(
            "terminal_growth (9%) exceeds 3% - implies the company exceeds the economy"))
        assert cat is FailureCategory.ECONOMIC_MODEL_FAILURE
        cat, _ = categorize_failure(BridgeError("'discount_rate' is DERIVED by build_wacc"))
        assert cat is FailureCategory.MARKET_DATA_FAILURE
        cat, _ = categorize_failure(MarketDriftError("redefines shared"))
        assert cat is FailureCategory.MARKET_DATA_FAILURE
        cat, note = categorize_failure(
            ContractBlockedError.__new__(ContractBlockedError))
        assert cat is FailureCategory.INSUFFICIENT_EVIDENCE
        assert "NOT usable" in note

    def test_every_category_note_states_usability(self):
        for exc in (DCFConsistencyError("x"), DCFConsistencyError("NOT_SOLVABLE"),
                    RuntimeError("boom")):
            _, note = categorize_failure(exc)
            assert note


# =========================================================================== #
# Isolation - P5 cannot alter or crash the valuation
# =========================================================================== #
class TestP5Isolation:
    def test_robustness_module_imports_nothing_from_the_model_layers(self):
        import inspect
        import aleph.valuation.robustness as m
        src = inspect.getsource(m)
        for banned in ("from .bridge", "from .wacc", "from .assumptions",
                       "from .accounting_quality", "import bridge",
                       "build_wacc", "build_dcf_inputs", "assess_accounting_quality"):
            assert banned not in src, f"robustness imports {banned!r}"

    @pytest.mark.needs_filings
    def test_absurd_robustness_report_does_not_move_valuation(self, monkeypatch):
        good = pipeline.value_filing("UBER_FY2024", 76.95)
        gv = (good.result.value_per_share, good.result.enterprise_or_equity_value,
              good.result.equity_value, good.wacc.wacc,
              good.bridged.inputs.base_cash_flow, good.result.pv_terminal,
              good.implied_growth)

        def absurd(_run):
            return RobustnessReport(
                doc_id="X", assessed=True,
                findings=(), anchor_table=(), primary_driver="nonsense",
                notes=("garbage",))
        monkeypatch.setattr(pipeline, "assess_robustness", absurd)
        bad = pipeline.value_filing("UBER_FY2024", 76.95)
        assert (bad.result.value_per_share, bad.result.enterprise_or_equity_value,
                bad.result.equity_value, bad.wacc.wacc,
                bad.bridged.inputs.base_cash_flow, bad.result.pv_terminal,
                bad.implied_growth) == gv

    @pytest.mark.needs_filings
    def test_robustness_exception_does_not_take_down_the_valuation(self, monkeypatch):
        def boom(_run):
            raise RuntimeError("robustness blew up")
        monkeypatch.setattr(pipeline, "assess_robustness", boom)
        run = pipeline.value_filing("UBER_FY2024", 76.95)
        assert run.result.value_per_share == pytest.approx(77.08, abs=0.01)
        assert run.robustness.assessed is False
        assert "RuntimeError" in run.robustness.not_assessed_reason
        assert run.robustness.findings == ()

    @pytest.mark.needs_filings
    def test_assess_robustness_never_mutates_the_run(self):
        run = pipeline.value_filing("UBER_FY2024", 76.95)
        before = (run.result.value_per_share, run.bridged.inputs.base_cash_flow,
                  list(run.bridged.inputs.growth_rates))
        assess_robustness(run)
        after = (run.result.value_per_share, run.bridged.inputs.base_cash_flow,
                 list(run.bridged.inputs.growth_rates))
        assert before == after


# =========================================================================== #
# Phase 13 - cross-sector / cross-economic-model
# =========================================================================== #
class TestCrossSector:
    SECTORS = {
        "asset_light_software": dict(
            base_cash_flow=800.0, growth_rates=[0.20] * 10, terminal_growth=0.025,
            discount_rate=0.11, net_debt=-500.0, shares_outstanding=200.0),
        "industrial_manufacturer": dict(
            base_cash_flow=1200.0, growth_rates=[0.03] * 10, terminal_growth=0.02,
            discount_rate=0.08, net_debt=4000.0, shares_outstanding=500.0),
        "capital_intensive_infra": dict(
            base_cash_flow=300.0, growth_rates=[0.02] * 10, terminal_growth=0.02,
            discount_rate=0.07, net_debt=15000.0, shares_outstanding=800.0),
        "financial_marketplace": dict(
            base_cash_flow=600.0, growth_rates=[0.15] * 10, terminal_growth=0.025,
            discount_rate=0.10, net_debt=-2000.0, shares_outstanding=300.0),
        "mature_cash_generator": dict(
            base_cash_flow=5000.0, growth_rates=[0.02] * 10, terminal_growth=0.02,
            discount_rate=0.08, net_debt=8000.0, shares_outstanding=2000.0),
        "cyclical": dict(
            base_cash_flow=900.0, growth_rates=[0.06] * 10, terminal_growth=0.02,
            discount_rate=0.09, net_debt=2500.0, shares_outstanding=400.0),
        # recovery: latest year is a depressed trough, growth expected to snap back
        "recovery_company": dict(
            base_cash_flow=200.0, growth_rates=[0.30, 0.25, 0.18, 0.12, 0.08,
                                                0.06, 0.05, 0.04, 0.03, 0.025],
            terminal_growth=0.025, discount_rate=0.10, net_debt=1500.0,
            shares_outstanding=300.0),
        # capex cycle: heavy near-term investment, FCFF grows as capex normalises
        "capex_cycle_company": dict(
            base_cash_flow=400.0, growth_rates=[0.02, 0.03, 0.05, 0.08, 0.10,
                                                0.09, 0.07, 0.05, 0.035, 0.025],
            terminal_growth=0.025, discount_rate=0.085, net_debt=6000.0,
            shares_outstanding=700.0),
        # highly levered -> EV below net debt -> negative equity
        "over_levered_negative_equity": dict(
            base_cash_flow=300.0, growth_rates=[0.02] * 10, terminal_growth=0.02,
            discount_rate=0.09, net_debt=20000.0, shares_outstanding=500.0),
    }

    @pytest.mark.parametrize("name", list(SECTORS))
    def test_every_sector_produces_a_full_finding_set_without_hacks(self, name):
        inp = mk(**self.SECTORS[name])
        run = _Run(inp,
                   fcff_by_period={"FY2022": inp.base_cash_flow * 0.7,
                                   "FY2023": inp.base_cash_flow * 0.85,
                                   "FY2024": inp.base_cash_flow},
                   market_price=run_dcf(inp).value_per_share)
        rob = assess_robustness(run)
        keys = {f.key for f in rob.findings}
        assert {"ANCHOR_SENSITIVITY", "TERMINAL_VALUE_DEPENDENCE",
                "REVERSE_DCF_CONSISTENCY", "VALUE_BRIDGE_INTEGRITY",
                "HISTORICAL_REGIME"} <= keys

    def test_negative_fcff_growth_company_fails_visibly(self):
        inp = mk(base_cash_flow=-400.0, growth_rates=[0.30] * 10)
        run = _Run(inp, fcff_by_period={"FY2022": -800.0, "FY2023": -600.0,
                                        "FY2024": -400.0})
        rob = assess_robustness(run)
        assert rob.get("VALUATION_METHOD_LIMITATION").severity is Severity.HIGH
        # and it does NOT silently look fine
        assert any(f.severity is Severity.HIGH for f in rob.findings)

    def test_capital_intensive_high_leverage_bridge_still_reconciles(self):
        inp = mk(**self.SECTORS["capital_intensive_infra"])
        f = assess_robustness(_Run(inp)).get("VALUE_BRIDGE_INTEGRITY")
        assert "BROKEN" not in f.headline

    def test_over_levered_company_gets_negative_equity_and_limited_applicability(self):
        from aleph.valuation.robustness import Applicability
        inp = mk(**self.SECTORS["over_levered_negative_equity"])
        rob = assess_robustness(_Run(inp, market_price=run_dcf(inp).value_per_share))
        neq = rob.get("NEGATIVE_EQUITY_VALUE")
        assert neq is not None and neq.severity is Severity.HIGH
        assert "MATHEMATICALLY VALID, ECONOMICALLY LIMITED" in neq.interpretation
        assert "bear-case" not in neq.interpretation.lower() or \
            "NOT an ordinary bear-case" in neq.interpretation
        assert rob.applicability is Applicability.LIMITED_APPLICABILITY
        assert "capital_structure" in rob.limitation_families

    def test_short_history_fixture_is_not_over_stated(self):
        inp = mk(base_cash_flow=1000.0)
        rob = assess_robustness(_Run(inp, fcff_by_period={"FY2024": 1000.0},
                                     market_price=run_dcf(inp).value_per_share))
        assert rob.get("HISTORY_COMPARABILITY").headline.endswith(
            "NO_DETERMINABLE_CONCLUSION")
        assert rob.get("ANCHOR_SENSITIVITY").sensitivity.value == "NOT_APPLICABLE"

    def test_no_company_name_in_robustness_source(self):
        import aleph.valuation.robustness as m
        src = open(m.__file__, encoding="utf-8").read().lower()
        for line in src.splitlines():
            if line.lstrip().startswith("#") or '"""' in line:
                continue
            for name in ("uber", "lyft", "doordash", "airbnb"):
                assert name not in line, f"company name in code: {line}"
