"""P6 - sustainable / normalized FCFF framework.

Phases 5, 6, 9, 10, 12, 13, 17, 18: regime classification, range
construction, live-filing forensics, 15 adversarial synthetic cases,
cross-sector fixtures, the adjustment ledger / anti-double-counting, and the
proof that the base DCF is untouched. Every test is written to FAIL if its
safeguard is removed (mutation-tested by the P6 harness).
"""
import math

import pytest

import aleph.valuation.pipeline as pipeline
from aleph.schemas.evidence import Fact, FactSource
from aleph.schemas.valuation import AssumptionRange, Observation
from aleph.valuation.dcf_engine import DCFInputs, run_dcf
from aleph.valuation.sustainable_fcff import (
    AdjustmentClass,
    EvidenceLevel,
    FCFFAdjustment,
    PeriodFCFF,
    RegimeStatus,
    SustainableStatus,
    _double_count_ok,
    assess_sustainable_fcff,
    build_sustainable_range,
    classify_regime,
    decompose_history,
    sustainable_scenario_valuation,
)

UBER, LYFT = ("UBER_FY2024", 76.95), ("LYFT_FY2025", 17.35)


# --------------------------------------------------------------------------- #
# builders
# --------------------------------------------------------------------------- #
def mkperiod(period, fcff, wc, *, reconciles=True, evidence_missing=False):
    """A PeriodFCFF with a self-consistent FCFF / working-capital split."""
    ev = {"cfo": "OBSERVED", "capex": "OBSERVED", "sbc": "OBSERVED",
          "interest": "OBSERVED",
          "reconciliation": "OBSERVED" if reconciles else "MISSING"}
    if evidence_missing:
        ev["capex"] = "MISSING"
    comps = (
        FCFFAdjustment(f"{period}:a", period, AdjustmentClass.OPERATING_CASH_BEFORE_WC,
                       fcff - wc + 300 + 100 - 40, "USD millions", "f", ("x",),
                       EvidenceLevel.OBSERVED, "r"),
        FCFFAdjustment(f"{period}:wc", period, AdjustmentClass.WORKING_CAPITAL,
                       wc, "USD millions", "f", ("change in y",), EvidenceLevel.OBSERVED, "r"),
        FCFFAdjustment(f"{period}:i", period, AdjustmentClass.INTEREST_TAX_SHIELD,
                       40.0, "USD millions", "f", ("interest expense",),
                       EvidenceLevel.OBSERVED, "r", model_convention=True),
        FCFFAdjustment(f"{period}:c", period, AdjustmentClass.CAPEX,
                       -300.0, "USD millions", "f", ("purchases of property and equipment",),
                       EvidenceLevel.OBSERVED, "r"),
        FCFFAdjustment(f"{period}:s", period, AdjustmentClass.SBC,
                       -100.0, "USD millions", "f", ("stock-based compensation",),
                       EvidenceLevel.OBSERVED, "r", model_convention=True),
    )
    return PeriodFCFF(
        period=period, cfo=fcff - wc + 300 + 100 - 40 + wc, interest_tax_shield=40.0,
        capex=300.0, sbc=100.0, operating_cash_before_wc=fcff - wc + 300 + 100 - 40,
        working_capital_total=wc, reconstructed_fcff=fcff,
        # fcff_ex_working_capital is always finite (CFO is observed even when
        # the wider reconciliation fails); only the `reconciles` flag marks a
        # period as untrustworthy, so a guard keyed on it is what a test must
        # exercise.
        fcff_ex_working_capital=(fcff - wc),
        components=comps if reconciles else (), evidence=ev,
        reconciles=reconciles, residual=0.0 if reconciles else 400.0)


def _rng(name, unit, obs):
    return AssumptionRange(
        name=name, unit=unit, status="derived",
        low=obs[-1][1], base=obs[-1][1], high=obs[-1][1],
        observations=[Observation(period=p, value=v, fact_name=name, unit=unit)
                      for p, v in obs],
        method="latest", rationale="synthetic", doc_ids=["X"])


def _fact(name, value, period, unit="USD millions", target="cash_flows"):
    return Fact(name=name, value=value, unit=unit, period=period, quote="q",
                source=FactSource(doc_id="X", kind="statement", ref=target,
                                  target_key=target, pages=[1]))


# =========================================================================== #
# PHASE 5 - regime classification is deterministic
# =========================================================================== #
class TestRegimeClassification:
    def test_fewer_than_three_periods_is_insufficient_history(self):
        r, _ = classify_regime([mkperiod("FY2023", 900, 100),
                                mkperiod("FY2024", 1000, 100)])
        assert r is RegimeStatus.INSUFFICIENT_HISTORY

    def test_sign_change_is_regime_uncertain_not_structural(self):
        r, why = classify_regime([mkperiod("FY2022", -400, 50),
                                  mkperiod("FY2023", 300, 50),
                                  mkperiod("FY2024", 900, 50)])
        assert r is RegimeStatus.REGIME_UNCERTAIN
        assert any("changes sign" in w for w in why)

    def test_tight_band_is_structural(self):
        r, _ = classify_regime([mkperiod("FY2022", 980, 40),
                                mkperiod("FY2023", 1000, 40),
                                mkperiod("FY2024", 1020, 40)])
        assert r is RegimeStatus.EVIDENCE_CONSISTENT_WITH_STRUCTURAL_CHANGE

    def test_isolated_final_spike_is_temporary(self):
        r, why = classify_regime([mkperiod("FY2022", 1000, 50),
                                  mkperiod("FY2023", 1010, 50),
                                  mkperiod("FY2024", 3200, 50)])
        assert r is RegimeStatus.EVIDENCE_CONSISTENT_WITH_TEMPORARY
        assert any("isolated move" in w for w in why)

    def test_monotonic_rise_no_sign_change_is_regime_uncertain(self):
        # a persistent trend, but 3 points cannot tell run-rate from waypoint
        r, why = classify_regime([mkperiod("FY2023", 1900, 100),
                                  mkperiod("FY2024", 5500, 100),
                                  mkperiod("FY2025", 8300, 100)])
        assert r is RegimeStatus.REGIME_UNCERTAIN
        assert any("monotonically up" in w for w in why)

    def test_missing_component_forces_regime_uncertain(self):
        r, _ = classify_regime([mkperiod("FY2022", 980, 40),
                                mkperiod("FY2023", 1000, 40),
                                mkperiod("FY2024", 1020, 40, evidence_missing=True)])
        assert r is RegimeStatus.REGIME_UNCERTAIN


# =========================================================================== #
# PHASE 6 - the range is built only from explicit interpretations
# =========================================================================== #
class TestSustainableRange:
    def test_low_le_central_le_high(self):
        periods = [mkperiod("FY2022", 900, 100), mkperiod("FY2023", 1000, 200),
                   mkperiod("FY2024", 1600, 700)]
        st, low, central, high, *_ = build_sustainable_range(
            periods, RegimeStatus.REGIME_UNCERTAIN)
        assert st is SustainableStatus.SUPPORTED_RANGE
        assert low <= central <= high
        assert low == pytest.approx(900)      # 1600 - 700 wc
        assert high == pytest.approx(1600)

    def test_insufficient_history_yields_no_range(self):
        st, *_ = build_sustainable_range(
            [mkperiod("FY2024", 1000, 100)], RegimeStatus.INSUFFICIENT_HISTORY)
        assert st is SustainableStatus.INSUFFICIENT_EVIDENCE

    def test_latest_period_not_reconciling_yields_no_range(self):
        periods = [mkperiod("FY2022", 900, 100), mkperiod("FY2023", 1000, 100),
                   mkperiod("FY2024", 1600, 700, reconciles=False)]
        st, *_ = build_sustainable_range(periods, RegimeStatus.REGIME_UNCERTAIN)
        assert st is SustainableStatus.INSUFFICIENT_EVIDENCE

    def test_latest_period_missing_component_yields_no_range(self):
        # latest period reconciles and >=2 periods reconcile, but a component
        # (capex) is MISSING for the latest year -> no range
        periods = [mkperiod("FY2022", 900, 100), mkperiod("FY2023", 1000, 100),
                   mkperiod("FY2024", 1600, 700, evidence_missing=True)]
        st, *rest = build_sustainable_range(periods, RegimeStatus.REGIME_UNCERTAIN)
        assert st is SustainableStatus.INSUFFICIENT_EVIDENCE
        assert any("material component of the latest period is missing"
                   in w for w in rest[-1])

    def test_fewer_than_two_reconciling_periods_yields_no_range(self):
        # latest reconciles, but the recurring working-capital level cannot be
        # established from a single clean year
        periods = [mkperiod("FY2022", 900, 100, reconciles=False),
                   mkperiod("FY2023", 1000, 100, reconciles=False),
                   mkperiod("FY2024", 1600, 700, reconciles=True)]
        st, *rest = build_sustainable_range(periods, RegimeStatus.REGIME_UNCERTAIN)
        assert st is SustainableStatus.INSUFFICIENT_EVIDENCE
        assert any("recurring working-capital level cannot be established"
                   in w for w in rest[-1])

    def test_negative_median_working_capital_clamps_central_to_low(self):
        # WC is a net USE of cash historically -> no sustainable tailwind
        periods = [mkperiod("FY2022", 1000, -300), mkperiod("FY2023", 1000, -200),
                   mkperiod("FY2024", 1000, -100)]
        st, low, central, high, lb, cb, hb, why = build_sustainable_range(
            periods, RegimeStatus.EVIDENCE_CONSISTENT_WITH_STRUCTURAL_CHANGE)
        assert st is SustainableStatus.SUPPORTED_RANGE
        assert central == pytest.approx(low)
        assert any("net USE of cash" in w for w in why)

    def test_central_uses_the_median_not_the_latest_working_capital(self):
        # latest WC is a big peak; central must lean on the median, not it
        periods = [mkperiod("FY2022", 1000, 100), mkperiod("FY2023", 1000, 150),
                   mkperiod("FY2024", 3000, 2100)]
        _, low, central, high, *_ = build_sustainable_range(
            periods, RegimeStatus.REGIME_UNCERTAIN)
        assert low == pytest.approx(900)                 # 3000 - 2100
        assert central == pytest.approx(1050)            # 900 + median(100,150,2100)=150
        assert central < high


# =========================================================================== #
# PHASE 3 + 13 - decomposition provenance + adjustment ledger
# =========================================================================== #
class TestDecompositionAndLedger:
    def _synthetic(self, cfo, wc_lines, noncash_lines, capex, sbc, interest,
                   ni=None):
        # by default NI is chosen so the reconciliation closes exactly:
        # CFO = NI + non-cash (incl. SBC) + working capital
        if ni is None:
            ni = cfo - (sum(v for _, v in noncash_lines) + sbc) \
                 - sum(v for _, v in wc_lines)
        periods = ["FY2023", "FY2024", "FY2025"]
        facts = []
        for p in periods:
            facts.append(_fact("Net income (loss) including non-controlling interests", ni, p))
            for nm, v in wc_lines:
                facts.append(_fact(nm, v, p))
            for nm, v in noncash_lines:
                facts.append(_fact(nm, v, p))
            facts.append(_fact("Net cash provided by operating activities", cfo, p))
            facts.append(_fact("Purchases of property and equipment", -capex, p))
            facts.append(_fact("Stock-based compensation", sbc, p))
        ranges = {
            "operating_cash_flow": _rng("operating_cash_flow", "USD millions",
                                        [(p, cfo) for p in periods]),
            "capex": _rng("capex", "USD millions", [(p, -capex) for p in periods]),
            "stock_based_compensation": _rng("stock_based_compensation",
                                             "USD millions", [(p, sbc) for p in periods]),
            "interest_expense": _rng("interest_expense", "USD millions",
                                     [(p, -interest) for p in periods]),
        }
        fbp = {p: cfo + interest * (1 - 0.21) - capex - sbc for p in periods}
        return decompose_history(ranges, 0.21, facts, fbp)

    def test_ledger_sums_exactly_to_reconstructed_fcff(self):
        periods, ledger = self._synthetic(
            cfo=2000, wc_lines=[("Change in accounts receivable", -100),
                                ("Change in accrued insurance reserves", 500)],
            noncash_lines=[("Depreciation and amortization", 300),
                           ("Deferred income taxes", -50)],
            capex=200, sbc=400, interest=60)
        for p in periods:
            assert p.reconciles, p.residual
            assert sum(c.amount for c in p.components) == pytest.approx(
                p.reconstructed_fcff, abs=1e-6)
            assert p.working_capital_total == pytest.approx(400)     # -100 + 500
            assert p.operating_cash_before_wc == pytest.approx(1600)  # 2000 - 400

    def test_every_component_carries_full_provenance(self):
        periods, ledger = self._synthetic(
            cfo=2000, wc_lines=[("Change in accounts payable", 120)],
            noncash_lines=[("Depreciation and amortization", 300)],
            capex=200, sbc=400, interest=60)
        assert ledger
        for a in ledger:
            assert a.adjustment_id and a.period and a.formula
            assert a.source_facts and a.economic_rationale
            assert isinstance(a.evidence_level, EvidenceLevel)
            assert isinstance(a.classification, AdjustmentClass)

    def test_broken_reconciliation_fails_closed(self):
        # a missing $900 non-cash line -> residual explodes -> not reconciled
        periods, _ = self._synthetic(
            cfo=2000, wc_lines=[("Change in accounts receivable", -100)],
            noncash_lines=[("Depreciation and amortization", 300)],
            capex=200, sbc=400, interest=60,
            ni=900)   # NI far too low: reconciliation must fail
        assert not any(p.reconciles for p in periods)
        for p in periods:
            assert p.components == ()      # no ledger built on an unreconciled period

    def test_double_count_detector_flags_a_repeated_class(self):
        led = [
            FCFFAdjustment("FY24:a", "FY2024", AdjustmentClass.CAPEX, -200.0,
                           "USD millions", "f", ("purchases of property and equipment",),
                           EvidenceLevel.OBSERVED, "r"),
            FCFFAdjustment("FY24:b", "FY2024", AdjustmentClass.CAPEX, -50.0,
                           "USD millions", "f", ("more capex",),
                           EvidenceLevel.OBSERVED, "r"),
        ]
        ok, problems = _double_count_ok(led)
        assert not ok and any("CAPEX appears 2 times" in p for p in problems)

    def test_double_count_detector_flags_a_fact_added_and_subtracted(self):
        led = [
            FCFFAdjustment("FY24:c", "FY2024", AdjustmentClass.CAPEX, -200.0,
                           "USD millions", "f", ("purchases of property and equipment",),
                           EvidenceLevel.OBSERVED, "r"),
            FCFFAdjustment("FY24:o", "FY2024", AdjustmentClass.OPERATING_CASH_BEFORE_WC,
                           1000.0, "USD millions", "f",
                           ("purchases of property and equipment",),  # same fact, positive
                           EvidenceLevel.OBSERVED, "r"),
        ]
        ok, problems = _double_count_ok(led)
        assert not ok

    def test_double_count_detector_passes_a_clean_ledger(self):
        _, led = self._synthetic(
            cfo=2000, wc_lines=[("Change in accounts payable", 120)],
            noncash_lines=[("Depreciation and amortization", 300)],
            capex=200, sbc=400, interest=60)
        ok, problems = _double_count_ok(led)
        assert ok and problems == []

    def test_interest_only_as_flat_override_is_marked_inferred(self):
        periods = ["FY2023", "FY2024", "FY2025"]
        facts = []
        for p in periods:
            facts += [_fact("Net income (loss) including non-controlling interests", 1600, p),
                      _fact("Change in accounts payable", 100, p),
                      _fact("Depreciation and amortization", 300, p),
                      _fact("Net cash provided by operating activities", 2000, p),
                      _fact("Purchases of property and equipment", -200, p),
                      _fact("Stock-based compensation", 400, p)]
        ir = _rng("interest_expense", "USD millions", [("FY2025", 0.0)])
        ir.observations.clear()            # no per-period observations
        ranges = {
            "operating_cash_flow": _rng("operating_cash_flow", "USD millions",
                                        [(p, 2000) for p in periods]),
            "capex": _rng("capex", "USD millions", [(p, -200) for p in periods]),
            "stock_based_compensation": _rng("stock_based_compensation", "USD millions",
                                             [(p, 400) for p in periods]),
            "interest_expense": ir,
        }
        fbp = {p: 2000 - 200 - 400 for p in periods}
        pers, _ = decompose_history(ranges, 0.21, facts, fbp)
        assert all(p.evidence["interest"] == "INFERRED" for p in pers)


# =========================================================================== #
# PHASE 8 - scenario layer is isolated; only base_cash_flow moves
# =========================================================================== #
class TestScenarioIsolation:
    def _inputs(self):
        return DCFInputs(cash_flow_type="FCFF", base_cash_flow=1000.0,
                         growth_rates=[0.05] * 10, terminal_growth=0.025,
                         discount_rate=0.09, net_debt=200.0,
                         shares_outstanding=500.0, assumptions=[])

    def _sust(self, low, central, high):
        return type("S", (), {
            "status": SustainableStatus.SUPPORTED_RANGE,
            "low": low, "central": central, "high": high})()

    def test_only_base_cash_flow_changes_between_scenarios(self):
        inp = self._inputs()
        rows = sustainable_scenario_valuation(inp, self._sust(600, 800, 900))
        assert [r.label for r in rows] == ["current", "sustainable_low",
                                           "sustainable_central", "sustainable_high"]
        assert rows[0].base_fcff == 1000.0 and rows[3].base_fcff == 900.0
        # a lower FCFF must value strictly lower, all else equal
        assert rows[1].value_per_share < rows[0].value_per_share

    def test_scenario_layer_does_not_mutate_the_inputs(self):
        # the sustainable HIGH (900) differs from the caller's base (1000):
        # an aliasing bug would leave inp.base_cash_flow at 900
        inp = self._inputs()
        before = (inp.base_cash_flow, list(inp.growth_rates), inp.discount_rate,
                  inp.net_debt, inp.shares_outstanding)
        sustainable_scenario_valuation(inp, self._sust(600, 800, 900))
        after = (inp.base_cash_flow, list(inp.growth_rates), inp.discount_rate,
                 inp.net_debt, inp.shares_outstanding)
        assert before == after
        assert inp.base_cash_flow == 1000.0

    def test_insufficient_evidence_emits_only_the_current_row(self):
        inp = self._inputs()
        s = type("S", (), {"status": SustainableStatus.INSUFFICIENT_EVIDENCE,
                           "low": None, "central": None, "high": None})()
        rows = sustainable_scenario_valuation(inp, s)
        assert [r.label for r in rows] == ["current"]


# =========================================================================== #
# PHASE 9 + 12 - live filings, and the base DCF is untouched
# =========================================================================== #
class TestLiveFilings:
    def test_uber_fy2024_supported_range_regime_uncertain(self):
        run = pipeline.value_filing(*UBER)
        s = assess_sustainable_fcff(run)
        assert s.status is SustainableStatus.SUPPORTED_RANGE
        assert s.regime is RegimeStatus.REGIME_UNCERTAIN      # sign change in history
        assert s.low < s.central <= s.high
        assert s.high == pytest.approx(s.latest_reconstructed_fcff, abs=1.0)
        assert s.reconciliation_ok and s.double_count_ok

    def test_uber_fy2024_working_capital_tailwind_is_isolated(self):
        run = pipeline.value_filing(*UBER)
        s = assess_sustainable_fcff(run)
        fy24 = s.periods[-1]
        # FY2024 WC contribution (mostly the insurance-reserve build) dwarfs
        # the prior years - the framework must expose that, not bury it
        assert fy24.working_capital_total > 2000
        assert fy24.working_capital_total > 3 * abs(s.periods[0].working_capital_total)

    def test_lyft_fy2025_supported_range_and_low_is_near_zero(self):
        run = pipeline.value_filing(*LYFT)
        s = assess_sustainable_fcff(run)
        assert s.status is SustainableStatus.SUPPORTED_RANGE
        assert s.low < 100          # ex-working-capital, Lyft FY2025 FCFF is ~0
        assert s.high == pytest.approx(s.latest_reconstructed_fcff, abs=1.0)

    def test_dash_fy2025_is_insufficient_evidence_not_a_forced_number(self):
        run = pipeline.value_filing("DASH_FY2025", 215.0)
        s = assess_sustainable_fcff(run)
        assert s.status is SustainableStatus.INSUFFICIENT_EVIDENCE
        assert s.low is None and s.central is None and s.high is None

    def test_base_point_values_are_untouched_by_p6(self):
        assert pipeline.value_filing(*UBER).result.value_per_share == \
            pytest.approx(77.08, abs=0.01)
        assert pipeline.value_filing(*LYFT).result.value_per_share == \
            pytest.approx(49.06, abs=0.01)

    def test_scenario_current_row_equals_the_base_dcf(self):
        run = pipeline.value_filing(*UBER)
        s = assess_sustainable_fcff(run)
        rows = sustainable_scenario_valuation(run.bridged.inputs, s)
        cur = next(r for r in rows if r.label == "current")
        assert cur.value_per_share == pytest.approx(
            run.result.value_per_share, abs=0.01)
        assert cur.base_fcff == pytest.approx(run.bridged.inputs.base_cash_flow)


# =========================================================================== #
# PHASE 10 - 15 adversarial synthetic cases
# =========================================================================== #
class TestAdversarialSynthetic:
    #   (name, [(period, fcff, wc)...], expected_regime, notes)
    CASES = {
        "one_year_wc_release":
            ([("FY2022", 1000, 50), ("FY2023", 1000, 50), ("FY2024", 1000, 900)],
             RegimeStatus.EVIDENCE_CONSISTENT_WITH_STRUCTURAL_CHANGE),
        "one_year_wc_build":
            ([("FY2022", 1000, 50), ("FY2023", 1000, 50), ("FY2024", 1000, -900)],
             RegimeStatus.EVIDENCE_CONSISTENT_WITH_STRUCTURAL_CHANGE),
        "persistent_wc_improvement":
            ([("FY2022", 800, 100), ("FY2023", 1000, 300), ("FY2024", 1250, 600)],
             RegimeStatus.REGIME_UNCERTAIN),
        "persistent_deterioration":
            ([("FY2022", 1500, 100), ("FY2023", 1100, 100), ("FY2024", 700, 100)],
             RegimeStatus.REGIME_UNCERTAIN),
        "structural_margin_expansion":
            ([("FY2022", 400, 50), ("FY2023", 800, 50), ("FY2024", 1200, 50)],
             RegimeStatus.REGIME_UNCERTAIN),
        "temporary_margin_spike":
            ([("FY2022", 1000, 50), ("FY2023", 1020, 50), ("FY2024", 2600, 50)],
             RegimeStatus.EVIDENCE_CONSISTENT_WITH_TEMPORARY),
        "genuine_capex_cycle":
            ([("FY2022", 1000, 50), ("FY2023", 990, 50), ("FY2024", 1010, 50)],
             RegimeStatus.EVIDENCE_CONSISTENT_WITH_STRUCTURAL_CHANGE),
        "sharp_capex_step_down":
            # a downward step is NOT labelled temporary without filing
            # evidence - calling it one-off argues the company is better than
            # it looks. The framework must recognise the ambiguity.
            ([("FY2022", 1000, 50), ("FY2023", 1000, 50), ("FY2024", 200, 50)],
             RegimeStatus.REGIME_UNCERTAIN),
        "recovery_from_trough":
            ([("FY2022", -600, 50), ("FY2023", 200, 50), ("FY2024", 900, 50)],
             RegimeStatus.REGIME_UNCERTAIN),
        "collapse_from_peak":
            ([("FY2022", 2000, 50), ("FY2023", 900, 50), ("FY2024", -300, 50)],
             RegimeStatus.REGIME_UNCERTAIN),
        "negative_fcff_growth":
            ([("FY2022", -900, 50), ("FY2023", -600, 50), ("FY2024", -300, 50)],
             RegimeStatus.REGIME_UNCERTAIN),
        "flat_mature":
            ([("FY2022", 1000, 100), ("FY2023", 1000, 100), ("FY2024", 1000, 100)],
             RegimeStatus.EVIDENCE_CONSISTENT_WITH_STRUCTURAL_CHANGE),
        "sbc_heavy_but_stable":
            ([("FY2022", 950, 50), ("FY2023", 1000, 50), ("FY2024", 1050, 50)],
             RegimeStatus.EVIDENCE_CONSISTENT_WITH_STRUCTURAL_CHANGE),
        "two_periods_only":
            ([("FY2023", 900, 50), ("FY2024", 1000, 50)],
             RegimeStatus.INSUFFICIENT_HISTORY),
        "high_wc_dependence":
            ([("FY2022", 300, 700), ("FY2023", 350, 800), ("FY2024", 400, 900)],
             RegimeStatus.REGIME_UNCERTAIN),
    }

    @pytest.mark.parametrize("name", list(CASES))
    def test_case(self, name):
        series, expected = self.CASES[name]
        periods = [mkperiod(p, f, w) for p, f, w in series]
        regime, _ = classify_regime(periods)
        assert regime is expected, (name, regime)

        st, low, central, high, *_ = build_sustainable_range(periods, regime)
        if regime is RegimeStatus.INSUFFICIENT_HISTORY:
            assert st is SustainableStatus.INSUFFICIENT_EVIDENCE
        else:
            assert st is SustainableStatus.SUPPORTED_RANGE
            assert low <= central <= high
            # HIGH is always the latest reconstructed FCFF - a structural
            # improvement is never erased
            assert high == pytest.approx(periods[-1].reconstructed_fcff)

    def test_high_wc_dependence_low_case_strips_the_tailwind(self):
        periods = [mkperiod(p, f, w) for p, f, w
                   in self.CASES["high_wc_dependence"][0]]
        _, low, central, high, *_ = build_sustainable_range(
            periods, RegimeStatus.REGIME_UNCERTAIN)
        assert low == pytest.approx(400 - 900)     # latest fcff - latest wc, negative
        assert low < 0 < high

    def test_structural_improvement_is_not_smoothed_into_the_mean(self):
        periods = [mkperiod(p, f, w) for p, f, w
                   in self.CASES["structural_margin_expansion"][0]]
        _, low, central, high, *_ = build_sustainable_range(
            periods, RegimeStatus.REGIME_UNCERTAIN)
        # HIGH keeps the FY2024 level (1200); the framework never replaces it
        # with mean(400,800,1200)=800
        assert high == pytest.approx(1200)
        assert central > 800


# =========================================================================== #
# PHASE 18 - cross-sector
# =========================================================================== #
class TestCrossSector:
    SECTORS = {
        "mature_cash_generator": ([("FY22", 2000, 200), ("FY23", 2050, 210),
                                   ("FY24", 2100, 220)],
                                  RegimeStatus.EVIDENCE_CONSISTENT_WITH_STRUCTURAL_CHANGE,
                                  SustainableStatus.SUPPORTED_RANGE),
        "saas_growth": ([("FY22", 300, 120), ("FY23", 600, 260), ("FY24", 1000, 480)],
                        RegimeStatus.REGIME_UNCERTAIN, SustainableStatus.SUPPORTED_RANGE),
        "marketplace_inflecting": ([("FY22", -400, 80), ("FY23", 200, 150),
                                    ("FY24", 700, 400)],
                                   RegimeStatus.REGIME_UNCERTAIN,
                                   SustainableStatus.SUPPORTED_RANGE),
        "industrial_cyclical": ([("FY22", 1200, 100), ("FY23", 700, -150),
                                 ("FY24", 1100, 120)],
                                RegimeStatus.REGIME_UNCERTAIN,
                                SustainableStatus.SUPPORTED_RANGE),
        "infrastructure_stable": ([("FY22", 900, 60), ("FY23", 930, 60),
                                   ("FY24", 950, 60)],
                                  RegimeStatus.EVIDENCE_CONSISTENT_WITH_STRUCTURAL_CHANGE,
                                  SustainableStatus.SUPPORTED_RANGE),
        "recovery": ([("FY22", -800, 40), ("FY23", -100, 40), ("FY24", 600, 40)],
                     RegimeStatus.REGIME_UNCERTAIN, SustainableStatus.SUPPORTED_RANGE),
        "high_capex": ([("FY22", 400, 50), ("FY23", 420, 50), ("FY24", 440, 50)],
                       RegimeStatus.EVIDENCE_CONSISTENT_WITH_STRUCTURAL_CHANGE,
                       SustainableStatus.SUPPORTED_RANGE),
        "high_working_capital": ([("FY22", 200, 900), ("FY23", 210, 950),
                                  ("FY24", 220, 1000)],
                                 # the FCFF SERIES is stable; the WC DEPENDENCE
                                 # shows up in the width of the range, not the
                                 # regime label
                                 RegimeStatus.EVIDENCE_CONSISTENT_WITH_STRUCTURAL_CHANGE,
                                 SustainableStatus.SUPPORTED_RANGE),
        "short_history_startup": ([("FY23", 100, 20), ("FY24", 300, 40)],
                                  RegimeStatus.INSUFFICIENT_HISTORY,
                                  SustainableStatus.INSUFFICIENT_EVIDENCE),
    }

    @pytest.mark.parametrize("name", list(SECTORS))
    def test_sector(self, name):
        series, exp_regime, exp_status = self.SECTORS[name]
        periods = [mkperiod(p, f, w) for p, f, w in series]
        regime, _ = classify_regime(periods)
        assert regime is exp_regime, (name, regime)
        st, low, central, high, *_ = build_sustainable_range(periods, regime)
        assert st is exp_status, (name, st)
        if st is SustainableStatus.SUPPORTED_RANGE:
            assert low <= central <= high

    def test_high_working_capital_sector_low_case_is_far_below_high(self):
        periods = [mkperiod(p, f, w) for p, f, w
                   in self.SECTORS["high_working_capital"][0]]
        _, low, central, high, *_ = build_sustainable_range(
            periods, RegimeStatus.REGIME_UNCERTAIN)
        assert high - low > 900          # the WC dependence is made visible


# =========================================================================== #
# PHASE 7 / 14 - the base DCF path is byte-identical with P6 present
# =========================================================================== #
class TestBaseDCFUntouched:
    def test_assess_sustainable_fcff_does_not_mutate_the_run(self):
        run = pipeline.value_filing(*UBER)
        before = (run.result.value_per_share, run.bridged.inputs.base_cash_flow,
                  list(run.bridged.inputs.growth_rates), run.implied_growth)
        assess_sustainable_fcff(run)
        assess_sustainable_fcff(run)
        after = (run.result.value_per_share, run.bridged.inputs.base_cash_flow,
                 list(run.bridged.inputs.growth_rates), run.implied_growth)
        assert before == after

    def test_pipeline_has_no_sustainable_fcff_import(self):
        # P6 must not be wired into the orchestrator
        import aleph.valuation.pipeline as p
        import inspect
        src = inspect.getsource(p)
        assert "sustainable_fcff" not in src
