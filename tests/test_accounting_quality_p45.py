"""P4.5 hardening - single-period semantics, working-capital fail-closed
coverage, and revenue-quality epistemic labelling. No new diagnostics; these
tests are about preventing false precision and false confidence.
"""
import pytest

import aleph.valuation.pipeline as pipeline
from aleph.schemas.evidence import Fact, FactSource
from aleph.valuation.accounting_quality import (
    Confidence,
    DiagnosticState,
    Horizon,
    ValuationImpact,
    WCCoverage,
    assess_accounting_quality,
)

Y1 = ("FY2024",)
Y2 = ("FY2023", "FY2024")
Y4 = ("FY2021", "FY2022", "FY2023", "FY2024")
FLAG = DiagnosticState.FLAGGED
OK = DiagnosticState.ASSESSED_NO_ISSUE
INSUF = DiagnosticState.INSUFFICIENT_DATA


def f(name, value, period, unit="USD millions", target="cash_flows"):
    return Fact(name=f"{name} {period}", value=float(value), unit=unit,
                period=period, quote=f"{name} ... {value}",
                source=FactSource(doc_id="SYNTH", kind="statement", ref=target,
                                  target_key=target, pages=[1]))


def s(name, values, years, **kw):
    return [f(name, v, y, **kw) for v, y in zip(values, years)]


def ni(v, y=Y4):
    return s("Net income (loss) including non-controlling interests", v, y)


def cfo(v, y=Y4):
    return s("Net cash provided by operating activities", v, y)


def revenue(v, y=Y4):
    return s("Total revenue", v, y, target="operations")


def capex(v, y=Y4):
    return s("Purchases of property and equipment", v, y)


def sbc(v, y=Y4):
    return s("Stock-based compensation", v, y)


def get(r, key):
    d = r.get(key)
    assert d is not None, f"{key} missing: {[x.key for x in r.diagnostics]}"
    return d


# --------------------------------------------------------------------------- #
# 1. Single-period semantics
# --------------------------------------------------------------------------- #
class TestSinglePeriodSemantics:
    def test_one_period_ratio_is_not_called_historically_clean(self):
        r = assess_accounting_quality(
            revenue([10000], Y1) + sbc([200], Y1) + cfo([3000], Y1)
            + ni([1000], Y1) + capex([150], Y1))
        d = get(r, "HIGH_SBC")          # a LEVEL ratio, assessable from one year
        assert d.state is OK
        assert d.confidence is Confidence.LIMITED
        assert d.horizon is Horizon.SINGLE_YEAR
        blob = (d.interpretation + " " + d.limitation).lower()
        assert "observed" in blob
        for bad in ("historically clean", "structurally normal",
                    "no accounting-quality concern", "clean account"):
            assert bad not in blob
        assert "persistence" in blob

    def test_report_has_no_overclaiming_language_on_thin_data(self):
        r = assess_accounting_quality(
            revenue([10000], Y1) + sbc([200], Y1) + cfo([3000], Y1)
            + capex([150], Y1) + ni([1000], Y1))
        assert not r.has_overclaiming_language()

    def test_capex_intensity_single_period_is_limited(self):
        r = assess_accounting_quality(
            capex([100], Y1) + cfo([3000], Y1) + revenue([10000], Y1))
        d = get(r, "HIGH_CAPITAL_INTENSITY")
        assert d.state is OK
        assert d.confidence is Confidence.LIMITED
        assert d.horizon is Horizon.SINGLE_YEAR

    def test_two_periods_still_limited_but_not_single_year(self):
        r = assess_accounting_quality(
            revenue([9000, 10000], Y2) + sbc([180, 200], Y2)
            + cfo([2800, 3000], Y2) + ni([900, 1000], Y2) + capex([140, 150], Y2))
        d = get(r, "HIGH_SBC")
        assert d.confidence is Confidence.LIMITED
        assert d.horizon in (Horizon.LATEST_PERIOD, Horizon.TREND)

    def test_three_plus_periods_get_a_real_horizon_and_normal_confidence(self):
        r = assess_accounting_quality(
            revenue([8000, 9000, 9500, 10000]) + sbc([160, 170, 185, 200])
            + cfo([2500, 2700, 2850, 3000]) + ni([800, 900, 950, 1000])
            + capex([120, 130, 140, 150]))
        d = get(r, "HIGH_SBC")
        assert d.confidence is Confidence.NORMAL
        assert d.horizon in (Horizon.TREND, Horizon.HISTORICAL_PATTERN,
                             Horizon.SINGLE_YEAR_ANOMALY, Horizon.LATEST_PERIOD)

    def test_flag_from_thin_history_keeps_the_flag_but_is_limited(self):
        r = assess_accounting_quality(
            ni([100, 100], Y2) + cfo([95, 55], Y2) + revenue([500, 500], Y2))
        d = get(r, "HIGH_ACCRUAL_COMPONENT")
        assert d.state is FLAG
        assert d.confidence is Confidence.LIMITED
        assert "persistence" in d.limitation.lower()


# --------------------------------------------------------------------------- #
# 2. Working-capital fail-closed coverage
# --------------------------------------------------------------------------- #
class TestWorkingCapitalCoverage:
    def test_complete_coverage_when_every_line_is_bucketed(self):
        facts = (cfo([100, 100, 100, 100]) + ni([50, 50, 50, 50])
                 + s("Change in accounts receivable", [-5, -5, -5, -5], Y4)
                 + s("Change in accounts payable", [3, 3, 3, 3], Y4))
        d = get(assess_accounting_quality(facts), "WORKING_CAPITAL_DEPENDENT_CFO")
        assert d.coverage is not None
        assert d.coverage.status is WCCoverage.FULL_COVERAGE
        assert d.confidence is Confidence.NORMAL

    def test_unknown_change_line_is_visible_and_counted(self):
        facts = (cfo([100, 100, 100, 100]) + ni([50, 50, 50, 50])
                 + s("Change in accounts receivable", [-5, -5, -5, -5], Y4)
                 + s("Change in widget escrow balances", [-40, 0, 0, -40], Y4))
        d = get(assess_accounting_quality(facts), "WORKING_CAPITAL_DEPENDENT_CFO")
        cov = d.coverage
        assert cov.status in (WCCoverage.PARTIAL_COVERAGE, WCCoverage.NO_COVERAGE)
        assert any("widget escrow" in n for n in cov.unknown_components)
        # the unknown component is inside the net total, not dropped
        assert abs(cov.unclassified) > 1e-6
        assert "not presented as a full" in d.interpretation.lower() \
            or "not fully" in (d.interpretation + d.limitation).lower()

    def test_low_coverage_downgrades_to_insufficient(self):
        facts = (cfo([100, 100, 100, 100]) + ni([50, 50, 50, 50])
                 + s("Change in accounts receivable", [-2, -2, -2, -2], Y4)
                 + s("Change in mystery operating balances", [-60, -60, -60, -60], Y4))
        d = get(assess_accounting_quality(facts), "WORKING_CAPITAL_DEPENDENT_CFO")
        assert d.state is INSUF
        assert d.coverage.status in (WCCoverage.PARTIAL_COVERAGE,
                                     WCCoverage.NO_COVERAGE)
        assert "composition is not" in d.interpretation.lower()

    def test_deterministic(self):
        facts = (cfo([100, 100, 100, 100]) + ni([50, 50, 50, 50])
                 + s("Change in accounts receivable", [-5, -5, -5, -5], Y4)
                 + s("Change in customer-related balances", [-40, 0, 0, -40], Y4)
                 + s("Change in unfamiliar thing", [-3, -3, -3, -3], Y4))
        a = assess_accounting_quality(facts).get("WORKING_CAPITAL_DEPENDENT_CFO")
        b = assess_accounting_quality(facts).get("WORKING_CAPITAL_DEPENDENT_CFO")
        assert a.coverage.render() == b.coverage.render()
        assert a.state == b.state


# --------------------------------------------------------------------------- #
# Unfamiliar fifth-company captions
# --------------------------------------------------------------------------- #
class TestFifthCompanyCaptions:
    """Deliberately unfamiliar wording. At least one line must stay UNKNOWN,
    stay visible, and stop the diagnostic claiming full WC attribution."""

    def _facts(self):
        return (cfo([2000, 2100, 2200, 2300]) + ni([1000, 1000, 1000, 1000])
                + s("Change in accounts receivable", [-50, -50, -50, -50], Y4)
                + s("Operating assets and liabilities, net (change)",
                    [-30, -30, -30, -400], Y4)
                + s("Other operating assets (change)", [-10, -10, -10, -10], Y4)
                + s("Customer-related balances (change)", [5, 5, 5, 5], Y4))

    def test_unknown_component_is_visible_not_swallowed(self):
        d = get(assess_accounting_quality(self._facts()),
                "WORKING_CAPITAL_DEPENDENT_CFO")
        names = " ".join(d.coverage.unknown_components).lower()
        assert "operating assets and liabilities, net" in names
        # counted, not excluded
        assert abs(d.coverage.unclassified) > 1e-6

    def test_cannot_claim_full_attribution(self):
        d = get(assess_accounting_quality(self._facts()),
                "WORKING_CAPITAL_DEPENDENT_CFO")
        assert d.coverage.status is not WCCoverage.FULL_COVERAGE

    def test_customer_related_and_other_operating_assets_do_bucket(self):
        d = get(assess_accounting_quality(self._facts()),
                "WORKING_CAPITAL_DEPENDENT_CFO")
        classified_labels = " ".join(
            e.label for e in d.evidence
            if not e.label.startswith("UNKNOWN_OPERATING_COMPONENT")).lower()
        assert "customer-related" in classified_labels
        assert "other operating assets" in classified_labels

    def test_no_issuer_specific_hack_present(self):
        import aleph.valuation.accounting_quality as m
        src = m.__file__
        text = open(src, encoding="utf-8").read().lower()
        for banned in ('== "uber"', "== 'uber'", '== "lyft"', '== "doordash"',
                       '== "dash"', "doc_id ==", "company ==", "== 'dash'"):
            assert banned not in text


# --------------------------------------------------------------------------- #
# 3 & 5. Revenue quality - proxy limitation and the A/B/C/D matrix
# --------------------------------------------------------------------------- #
def ar_change(v, y=Y4):
    return s("Change in accounts receivable", v, y)


class TestRevenueQualityMatrix:
    def test_case_a_strong_proxy_signal_flags(self):
        facts = (revenue([100, 100, 100, 120]) + cfo([50, 50, 50, 45])
                 + ni([10, 10, 10, 10]) + ar_change([-10, -10, -10, -14.5]))
        d = get(assess_accounting_quality(facts), "REVENUE_CASH_DIVERGENCE")
        assert d.state is FLAG
        assert d.key == "REVENUE_CASH_DIVERGENCE"
        assert "REVENUE_QUALITY_ASSESSMENT" in d.limitation
        assert "proxy" in d.limitation.lower()

    def test_case_b_one_year_divergence_not_called_structural(self):
        # drag spikes in FY2023 then eases in FY2024 -> timing, not structural
        facts = (revenue([100, 100, 110, 132]) + cfo([50, 50, 50, 48])
                 + ni([10, 10, 10, 10]) + ar_change([-8, -8, -25, -34]))
        d = get(assess_accounting_quality(facts), "REVENUE_CASH_DIVERGENCE")
        blob = (d.interpretation + d.diagnostic).lower()
        assert "structural revenue-quality deterioration" in d.interpretation.lower()
        assert "not described as" in blob or "not established" in blob
        assert d.confidence is Confidence.LIMITED

    def test_case_c_missing_balance_sheet_evidence_states_limitation(self):
        facts = (revenue([100, 110, 120, 140]) + cfo([50, 55, 60, 70])
                 + ni([10, 10, 10, 10]))                     # no AR line at all
        d = get(assess_accounting_quality(facts), "REVENUE_CASH_DIVERGENCE")
        assert d.state is INSUF
        assert "accounts-receivable balance" in d.limitation.lower()
        assert "not sufficient by itself" in d.limitation.lower()

    def test_case_d_no_signal_no_flag(self):
        facts = (revenue([100, 100, 100, 120]) + cfo([50, 50, 50, 60])
                 + ni([10, 10, 10, 10]) + ar_change([-10, -10, -10, -12]))
        d = get(assess_accounting_quality(facts), "REVENUE_CASH_DIVERGENCE")
        assert d.state is OK
        assert "REVENUE_QUALITY_ASSESSMENT" in d.limitation

    def test_flag_key_is_divergence_never_quality_problem(self):
        facts = (revenue([100, 100, 100, 120]) + cfo([50, 50, 50, 45])
                 + ni([10, 10, 10, 10]) + ar_change([-10, -10, -10, -14.5]))
        r = assess_accounting_quality(facts)
        assert r.get("REVENUE_QUALITY_PROBLEM") is None
        assert r.get("REVENUE_QUALITY_ASSESSMENT") is None
        assert r.get("REVENUE_CASH_DIVERGENCE") is not None


# --------------------------------------------------------------------------- #
# 6. Still cannot change valuation
# --------------------------------------------------------------------------- #
class TestP45CannotTouchValuation:
    ANCHOR = 77.08

    def test_anchor_holds_and_new_fields_are_present(self):
        run = pipeline.value_filing("UBER_FY2024", 76.95)
        assert run.result.value_per_share == pytest.approx(self.ANCHOR, abs=0.01)
        aq = run.accounting_quality
        assert aq is not None
        wc = aq.get("ONE_YEAR_WORKING_CAPITAL_SWING") or \
            aq.get("WORKING_CAPITAL_DEPENDENT_CFO")
        assert wc.coverage is not None
        assert any(d.confidence is Confidence.LIMITED for d in aq.diagnostics)

    def test_valuation_numbers_unchanged_vs_recorded(self):
        run = pipeline.value_filing("UBER_FY2024", 76.95)
        assert run.result.value_per_share == pytest.approx(77.08, abs=0.01)
        assert run.bridged.inputs.base_cash_flow == pytest.approx(5512.0, abs=1.0)
        assert 0.08 < run.wacc.wacc < 0.10
        # equity and EV are internally consistent (P4.5 touched none of it)
        assert run.result.equity_value == pytest.approx(
            run.result.enterprise_or_equity_value - run.bridged.inputs.net_debt,
            rel=1e-9)

    def test_no_overclaiming_language_on_any_real_filing(self):
        for doc in ("UBER_FY2024", "LYFT_FY2025"):
            run = pipeline.value_filing(
                doc, 76.95 if doc.startswith("UBER") else 17.35)
            assert not run.accounting_quality.has_overclaiming_language()
            assert not run.accounting_quality.has_forbidden_language()
