"""P4 - accounting-quality diagnostics.

Every dimension has at least one positive case and one negative control.
TestP4CannotTouchValuation is the critical regression: an all-HIGH-impact
report injected into the real pipeline must leave the per-share value
byte-identical.
"""
import pytest

import aleph.valuation.pipeline as pipeline
from aleph.schemas.evidence import Fact, FactSource
from aleph.valuation.accounting_quality import (
    ACCRUAL_TO_NI_HIGH,
    CashOneOff,
    Diagnostic,
    DiagnosticState,
    Direction,
    Horizon,
    ValuationImpact,
    assess_accounting_quality,
)

YEARS4 = ("FY2021", "FY2022", "FY2023", "FY2024")
YEARS3 = ("FY2022", "FY2023", "FY2024")
FLAG = DiagnosticState.FLAGGED
OK = DiagnosticState.ASSESSED_NO_ISSUE
INSUF = DiagnosticState.INSUFFICIENT_DATA


def f(name, value, period, unit="USD millions", target="cash_flows"):
    return Fact(
        name=f"{name} {period}", value=float(value), unit=unit, period=period,
        quote=f"{name} ... {value}",
        source=FactSource(doc_id="SYNTH", kind="statement", ref=target,
                          target_key=target, pages=[1]),
    )


def series(name, values, years, **kw):
    return [f(name, v, y, **kw) for v, y in zip(values, years)]


def build(**kw):
    """kw: name -> (values, years, extra). Assembles a flat fact list."""
    facts = []
    for spec in kw.values():
        facts.extend(spec)
    return facts


def ni(values, years=YEARS4):
    return series("Net income (loss) including non-controlling interests", values,
                  years, target="cash_flows")


def cfo(values, years=YEARS4):
    return series("Net cash provided by operating activities", values, years)


def revenue(values, years=YEARS4):
    return series("Total revenue", values, years, target="operations")


def capex(values, years=YEARS4):
    return series("Purchases of property and equipment", values, years)


def sbc(values, years=YEARS4):
    return series("Stock-based compensation", values, years, target="cash_flows")


def shares(values, years=YEARS4):
    return series("Diluted weighted-average shares outstanding", values, years,
                  unit="thousands", target="operations")


def ar_change(values, years=YEARS4):
    return series("Change in accounts receivable", values, years)


def get(report, key) -> Diagnostic:
    d = report.get(key)
    assert d is not None, f"{key} not in report: {[x.key for x in report.diagnostics]}"
    return d


# --------------------------------------------------------------------------- #
# A. Earnings vs cash
# --------------------------------------------------------------------------- #
class TestEarningsVsCash:
    def test_single_year_collapse_is_flagged(self):
        r = assess_accounting_quality(
            ni([100, 110, 120, 300]) + cfo([95, 100, 110, 120]))
        d = get(r, "CASH_EARNINGS_DIVERGENCE")
        assert d.state is FLAG
        assert d.horizon is Horizon.SINGLE_YEAR_ANOMALY
        assert d.direction is Direction.OVERSTATES_ECONOMIC_CASH
        assert d.potential_valuation_impact is ValuationImpact.MEDIUM
        assert "not established as a structural change" in d.interpretation

    def test_stable_conversion_is_not_flagged(self):
        r = assess_accounting_quality(
            ni([100, 110, 120, 130]) + cfo([98, 107, 118, 127]))
        assert get(r, "CASH_EARNINGS_DIVERGENCE").state is OK

    def test_issues_md_13_gentle_decline_not_flagged(self):
        r = assess_accounting_quality(
            ni([100, 100, 100, 100]) + cfo([92, 95, 91, 88]))
        assert get(r, "CASH_EARNINGS_DIVERGENCE").state is OK

    def test_issues_md_13_material_deterioration_flagged(self):
        r = assess_accounting_quality(
            ni([100, 100, 100, 100]) + cfo([95, 91, 88, 41]))
        d = get(r, "CASH_EARNINGS_DIVERGENCE")
        assert d.state is FLAG
        assert "41" in d.diagnostic and "0.41" in d.diagnostic

    def test_one_period_is_insufficient_not_clean(self):
        r = assess_accounting_quality(ni([120], ["FY2024"]) + cfo([80], ["FY2024"]))
        assert get(r, "CASH_EARNINGS_DIVERGENCE").state is INSUF

    def test_loss_year_latest_is_insufficient_for_ratio(self):
        r = assess_accounting_quality(
            ni([100, 110, 120, -50]) + cfo([95, 100, 110, 90]))
        assert get(r, "CASH_EARNINGS_DIVERGENCE").state is INSUF


# --------------------------------------------------------------------------- #
# B. Accrual intensity
# --------------------------------------------------------------------------- #
class TestAccruals:
    def test_high_accrual_component_flagged(self):
        r = assess_accounting_quality(
            ni([100, 100, 100, 100]) + cfo([95, 95, 95, 55])
            + revenue([500, 500, 500, 500]))
        d = get(r, "HIGH_ACCRUAL_COMPONENT")
        assert d.state is FLAG
        assert d.direction is Direction.OVERSTATES_ECONOMIC_CASH
        assert f"{ACCRUAL_TO_NI_HIGH:.0%}" in d.threshold

    def test_low_accrual_component_not_flagged(self):
        r = assess_accounting_quality(
            ni([100, 100, 100, 100]) + cfo([95, 96, 97, 92])
            + revenue([500, 500, 500, 500]))
        assert get(r, "HIGH_ACCRUAL_COMPONENT").state is OK

    def test_zero_ni_is_insufficient(self):
        r = assess_accounting_quality(
            ni([100, 100, 100, 0]) + cfo([95, 95, 95, 40]))
        assert get(r, "HIGH_ACCRUAL_COMPONENT").state is INSUF


# --------------------------------------------------------------------------- #
# C. Working-capital quality
# --------------------------------------------------------------------------- #
class TestWorkingCapital:
    def test_one_year_swing_flagged(self):
        facts = (cfo([100, 100, 100, 100]) + ni([50, 50, 50, 50])
                 + ar_change([-5, -5, -5, -5])
                 + series("Change in accrued liabilities", [0, 0, 0, 40], YEARS4))
        r = assess_accounting_quality(facts)
        d = get(r, "ONE_YEAR_WORKING_CAPITAL_SWING")
        assert d.state is FLAG
        assert d.horizon is Horizon.SINGLE_YEAR_ANOMALY

    def test_modest_recurring_working_capital_not_flagged(self):
        facts = (cfo([100, 100, 100, 100]) + ni([50, 50, 50, 50])
                 + ar_change([-5, -4, -6, -5]))
        r = assess_accounting_quality(facts)
        assert r.get("ONE_YEAR_WORKING_CAPITAL_SWING") is None
        assert get(r, "WORKING_CAPITAL_DEPENDENT_CFO").state is OK

    def test_persistent_dependence_flagged_as_pattern(self):
        facts = (cfo([100, 100, 100, 100]) + ni([50, 50, 50, 50])
                 + series("Change in accrued insurance reserves",
                          [30, 32, 31, 33], YEARS4))
        d = get(assess_accounting_quality(facts), "WORKING_CAPITAL_DEPENDENT_CFO")
        assert d.state is FLAG
        assert d.horizon is Horizon.HISTORICAL_PATTERN
        assert "insurance" in d.interpretation.lower()

    def test_no_working_capital_lines_is_insufficient(self):
        r = assess_accounting_quality(cfo([100, 100, 100, 100]) + ni([50] * 4))
        assert get(r, "WORKING_CAPITAL_DEPENDENT_CFO").state is INSUF


# --------------------------------------------------------------------------- #
# D. Revenue quality (#14 adversarial)
# --------------------------------------------------------------------------- #
class TestRevenueQuality:
    def test_revenue_outrunning_collections_is_flagged_but_not_called_fake(self):
        facts = (revenue([100, 100, 100, 120]) + cfo([50, 50, 50, 45])
                 + ni([10, 10, 10, 10])
                 + ar_change([-10, -10, -10, -14.5]))
        r = assess_accounting_quality(facts)
        d = get(r, "REVENUE_CASH_DIVERGENCE")
        assert d.state is FLAG
        assert d.direction is Direction.OVERSTATES_ECONOMIC_CASH
        blob = (d.fact + d.diagnostic + d.interpretation + d.valuation_relevance).lower()
        for banned in ("fake", "fraud", "manipulat", "fictitious"):
            assert banned not in blob
        assert not r.has_forbidden_language()

    def test_collections_keeping_pace_not_flagged(self):
        facts = (revenue([100, 100, 100, 120]) + cfo([50, 50, 50, 55])
                 + ni([10, 10, 10, 10])
                 + ar_change([-10, -10, -10, -11]))
        assert get(assess_accounting_quality(facts),
                   "REVENUE_CASH_DIVERGENCE").state is OK

    def test_missing_receivables_line_is_insufficient(self):
        facts = revenue([100, 110, 120, 140]) + cfo([50, 55, 60, 70])
        assert get(assess_accounting_quality(facts),
                   "REVENUE_CASH_DIVERGENCE").state is INSUF


# --------------------------------------------------------------------------- #
# E. Capital intensity (#16 adversarial)
# --------------------------------------------------------------------------- #
class TestCapitalIntensity:
    def test_capex_eight_of_ten_cfo_is_high_intensity(self):
        facts = (cfo([9000, 9000, 9000, 10000])
                 + capex([-7000, -7000, -7000, -8000])
                 + revenue([20000, 20000, 20000, 20000]))
        r = assess_accounting_quality(facts)
        d = get(r, "HIGH_CAPITAL_INTENSITY")
        assert d.state is FLAG
        assert d.potential_valuation_impact is ValuationImpact.HIGH
        # capex is not "assumed to be maintenance"
        m = get(r, "MAINTENANCE_CAPEX_UNVERIFIABLE")
        assert m.state is INSUF
        assert m.potential_valuation_impact is ValuationImpact.UNKNOWN

    def test_asset_light_not_flagged(self):
        facts = (cfo([9000, 9000, 9000, 10000])
                 + capex([-150, -160, -170, -200])
                 + revenue([20000, 20000, 20000, 20000]))
        r = assess_accounting_quality(facts)
        assert get(r, "HIGH_CAPITAL_INTENSITY").state is OK
        # still unverifiable - the negative control does not make maintenance known
        assert get(r, "MAINTENANCE_CAPEX_UNVERIFIABLE").state is INSUF


# --------------------------------------------------------------------------- #
# F. SBC materiality (#15 adversarial)
# --------------------------------------------------------------------------- #
class TestSBCMateriality:
    def test_sbc_two_billion_on_ten_revenue_is_high(self):
        facts = (revenue([10000, 10000]) + sbc([2000, 2000], YEARS4[-2:])
                 + cfo([3000, 3000], YEARS4[-2:])
                 + ni([1000, 1000], YEARS4[-2:]))
        # revenue years must line up
        facts = (revenue([10000, 10000], YEARS4[-2:])
                 + sbc([2000, 2000], YEARS4[-2:])
                 + cfo([3000, 3000], YEARS4[-2:])
                 + ni([1000, 1000], YEARS4[-2:]))
        r = assess_accounting_quality(facts)
        d = get(r, "HIGH_SBC")
        assert d.state is FLAG
        assert d.potential_valuation_impact is ValuationImpact.HIGH
        blob = (d.diagnostic + d.interpretation + d.valuation_relevance).lower()
        assert "irrelevant" not in blob
        assert "subtract" not in d.diagnostic.lower()  # not auto-applied here

    def test_modest_sbc_not_flagged(self):
        facts = (revenue([10000, 10000], YEARS4[-2:])
                 + sbc([200, 200], YEARS4[-2:])
                 + cfo([3000, 3000], YEARS4[-2:])
                 + ni([1000, 1000], YEARS4[-2:]))
        assert get(assess_accounting_quality(facts), "HIGH_SBC").state is OK

    def test_zero_sbc_is_none_impact(self):
        facts = (revenue([10000, 10000], YEARS4[-2:])
                 + sbc([0, 0], YEARS4[-2:])
                 + cfo([3000, 3000], YEARS4[-2:]))
        d = get(assess_accounting_quality(facts), "HIGH_SBC")
        assert d.state is OK
        assert d.potential_valuation_impact is ValuationImpact.NONE


# --------------------------------------------------------------------------- #
# G. SBC dilution
# --------------------------------------------------------------------------- #
class TestSBCDilution:
    def test_share_growth_is_measured_when_data_present(self):
        facts = shares([1000, 1000, 1000, 1030]) + sbc([50, 50, 50, 50])
        d = get(assess_accounting_quality(facts), "SBC_DILUTION")
        assert d.state is DiagnosticState.ASSESSED_NO_ISSUE
        assert "2.8%" in d.diagnostic or "3.0%" in d.diagnostic
        assert d.potential_valuation_impact is ValuationImpact.MEDIUM

    def test_no_share_series_is_explicitly_insufficient(self):
        facts = sbc([50, 50, 50, 900]) + shares([1000], ["FY2024"])
        d = get(assess_accounting_quality(facts), "SBC_DILUTION_DATA_INSUFFICIENT")
        assert d.state is INSUF
        assert "not inferred from SBC expense" in d.interpretation


# --------------------------------------------------------------------------- #
# H. One-off items
# --------------------------------------------------------------------------- #
class TestOneOffItems:
    def test_large_non_cash_adjustments_flagged(self):
        facts = (ni([1000, 1000, 1000, 8000])
                 + cfo([900, 900, 900, 2000])
                 + series("Deferred income taxes", [-40, 20, -30, -6000], YEARS4))
        d = get(assess_accounting_quality(facts),
                "LARGE_NON_CASH_EARNINGS_ADJUSTMENTS")
        assert d.state is FLAG
        assert "Deferred income taxes" in d.fact

    def test_supplied_cash_one_off_is_identified(self):
        facts = ni([1000] * 4) + cfo([1000, 1000, 1000, 10000])
        one_off = CashOneOff(amount=-2000.0, unit="USD millions",
                             fiscal_year="FY2024",
                             description="litigation settlement paid",
                             source="8-K filed 2024-03-01")
        r = assess_accounting_quality(facts, cash_one_offs=(one_off,))
        d = get(r, "DOCUMENTED_CASH_ONE_OFF")
        assert d.state is FLAG
        assert "litigation settlement" in d.fact
        assert r.get("NO_CASH_ONE_OFF_IDENTIFIED") is None

    def test_absent_cash_evidence_is_insufficient_not_a_clean_bill(self):
        facts = ni([1000] * 4) + cfo([1000] * 4)
        d = get(assess_accounting_quality(facts), "NO_CASH_ONE_OFF_IDENTIFIED")
        assert d.state is INSUF
        assert "NOT NO_CASH_ONE_OFF_EXISTS" in d.interpretation


# --------------------------------------------------------------------------- #
# #12 - diagnostic states; INSUFFICIENT_DATA is never a silent pass
# --------------------------------------------------------------------------- #
class TestDiagnosticStates:
    def test_thin_data_yields_insufficient_not_no_issue(self):
        facts = ni([120], ["FY2024"]) + cfo([80], ["FY2024"]) + revenue([500], ["FY2024"])
        r = assess_accounting_quality(facts)
        thin = {"CASH_EARNINGS_DIVERGENCE", "HIGH_ACCRUAL_COMPONENT",
                "REVENUE_CASH_DIVERGENCE"}
        for key in thin:
            assert get(r, key).state is INSUF, key

    def test_every_diagnostic_has_a_state_and_nothing_is_missing(self):
        facts = ni([100] * 4) + cfo([100] * 4)
        r = assess_accounting_quality(facts)
        dims = {d.dimension for d in r.diagnostics}
        assert dims == {"earnings_vs_cash", "accruals", "working_capital",
                        "revenue_quality", "capital_intensity", "sbc",
                        "sbc_dilution", "one_off_items"}
        for d in r.diagnostics:
            assert d.state in DiagnosticState
            assert d.potential_valuation_impact in ValuationImpact


# --------------------------------------------------------------------------- #
# #18 - cross-diagnostic convergence (qualitative, not a score)
# --------------------------------------------------------------------------- #
class TestConvergingRisks:
    def _converging_facts(self):
        # earnings/cash collapse + high accruals + revenue/collection divergence
        return (ni([100, 100, 100, 100]) + cfo([95, 95, 95, 45])
                + revenue([100, 100, 100, 130])
                + ar_change([-8, -8, -8, -20])
                + sbc([12, 12, 12, 12]))

    def test_multiple_aligned_flags_converge(self):
        r = assess_accounting_quality(self._converging_facts())
        assert r.converging_risks is not None
        assert r.converging_risks.present
        assert len(r.converging_risks.diagnostics) >= 3
        assert "not a score" in r.converging_risks.summary

    def test_a_single_flag_does_not_converge(self):
        facts = (ni([100, 100, 100, 100]) + cfo([95, 95, 95, 45])
                 + revenue([100, 100, 100, 105])
                 + ar_change([-8, -8, -8, -8]))
        r = assess_accounting_quality(facts)
        assert r.converging_risks is None

    def test_convergence_is_not_a_number(self):
        r = assess_accounting_quality(self._converging_facts())
        assert not hasattr(r.converging_risks, "score")


# --------------------------------------------------------------------------- #
# No fraud language, ever
# --------------------------------------------------------------------------- #
class TestNoFraudLanguage:
    @pytest.mark.parametrize("facts_fn", [
        lambda: (TestConvergingRisks()._converging_facts()),
        lambda: (assessable_real_uber_like()),
    ])
    def test_report_never_contains_fraud_words(self, facts_fn):
        r = assess_accounting_quality(facts_fn())
        assert not r.has_forbidden_language()


def assessable_real_uber_like():
    return (ni([-9138, 2156, 9845], YEARS3)
            + cfo([642, 3585, 7137], YEARS3)
            + revenue([31877, 37281, 43978], YEARS3)
            + capex([-252, -223, -242], YEARS3)
            + sbc([1793, 1935, 1796], YEARS3)
            + shares([1974928, 2091782, 2150508], YEARS3)
            + series("Deferred income taxes", [-441, 26, -6027], YEARS3)
            + series("Change in accounts receivable", [-542, -758, -142], YEARS3))


# --------------------------------------------------------------------------- #
# Evidence / traceability (#3, acceptance criterion)
# --------------------------------------------------------------------------- #
class TestTraceability:
    def test_every_assessed_or_flagged_diagnostic_cites_evidence(self):
        r = assess_accounting_quality(assessable_real_uber_like())
        for d in r.diagnostics:
            if d.state in (FLAG, OK):
                assert d.evidence, f"{d.key} has no evidence"
                assert d.formula, f"{d.key} has no formula"

    def test_evidence_values_match_the_source_facts(self):
        facts = assessable_real_uber_like()
        r = assess_accounting_quality(facts)
        d = get(r, "HIGH_SBC")
        sbc_ev = [e for e in d.evidence if "SBC" in e.label]
        assert any(abs(e.value - 1796) < 1e-6 for e in sbc_ev)

    def test_computed_numbers_name_the_facts_they_came_from(self):
        r = assess_accounting_quality(assessable_real_uber_like())
        d = get(r, "HIGH_SBC")
        ratio_ev = [e for e in d.evidence if e.computed_from]
        assert ratio_ev
        assert all(e.computed_from for e in ratio_ev)


# --------------------------------------------------------------------------- #
# #23 CRITICAL - P4 cannot change any valuation number
# --------------------------------------------------------------------------- #
class TestP4CannotTouchValuation:
    ANCHOR = 77.08

    def _known_good(self):
        run = pipeline.value_filing("UBER_FY2024", 76.95)
        return {
            "vps": run.result.value_per_share,
            "ev": run.result.enterprise_or_equity_value,
            "equity": run.result.equity_value,
            "wacc": run.wacc.wacc,
            "fcff": run.bridged.inputs.base_cash_flow,
        }

    @pytest.mark.needs_filings
    def test_baseline_anchor_holds_with_p4_present(self):
        run = pipeline.value_filing("UBER_FY2024", 76.95)
        assert run.result.value_per_share == pytest.approx(self.ANCHOR, abs=0.01)
        assert run.accounting_quality is not None
        assert run.accounting_quality.assessed

    @pytest.mark.needs_filings
    def test_all_high_impact_report_does_not_move_the_valuation(self, monkeypatch):
        good = self._known_good()

        from aleph.valuation.accounting_quality import (
            AccountingQualityReport, ConvergingRisks)

        def all_high(*_a, **_k):
            bogus = Diagnostic(
                key="HIGH_EVERYTHING", dimension="earnings_vs_cash",
                state=DiagnosticState.FLAGGED, horizon=Horizon.TREND,
                fact="synthetic", diagnostic="synthetic",
                interpretation="synthetic", valuation_relevance="synthetic",
                potential_valuation_impact=ValuationImpact.HIGH,
                direction=Direction.OVERSTATES_ECONOMIC_CASH)
            return AccountingQualityReport(
                doc_id="UBER_FY2024", assessed=True, diagnostics=(bogus,) * 5,
                converging_risks=ConvergingRisks(
                    True, Direction.OVERSTATES_ECONOMIC_CASH,
                    ("HIGH_EVERYTHING",), "synthetic - not a score"),
                periods=("FY2024",), notes=())

        monkeypatch.setattr(pipeline, "assess_accounting_quality", all_high)
        run = pipeline.value_filing("UBER_FY2024", 76.95)

        assert run.result.value_per_share == good["vps"]
        assert run.result.enterprise_or_equity_value == good["ev"]
        assert run.result.equity_value == good["equity"]
        assert run.wacc.wacc == good["wacc"]
        assert run.bridged.inputs.base_cash_flow == good["fcff"]
        assert run.accounting_quality.get("HIGH_EVERYTHING") is not None

    def test_p4_runs_after_the_dcf_in_source_order(self):
        import inspect
        src = inspect.getsource(pipeline.value_filing)
        assert src.index("run_dcf(") < src.index("assess_accounting_quality(")
        assert src.index("reverse_dcf(") < src.index("assess_accounting_quality(")
