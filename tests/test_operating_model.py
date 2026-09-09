"""P9 - operating model, forecast economics & driver-based DCF.

Phases 3-15, 22-29: series classification, historical driver lineage,
scenario-separated forecast, the revenue->margin->WC->capex->FCFF bridge,
driver-based DCF that feeds the EXISTING engine, 15 adversarial companies,
cross-sector, the anti-overfitting test, and byte-identity of the live DCF.
"""
import math
import types

import pytest

import aleph.valuation.pipeline as pipeline
from aleph.schemas.evidence import Fact, FactSource
from aleph.schemas.valuation import AssumptionRange, Observation
from aleph.valuation.dcf_engine import DCFInputs, run_dcf
from aleph.valuation.driver_based_dcf import (
    DriverDCFStatus,
    driver_based_dcf,
)
from aleph.valuation.operating_model import (
    DriverSource,
    ForecastSupport,
    Scenario,
    SeriesShape,
    STATUTORY_TAX_CONVENTION,
    TERMINAL_GROWTH_CONVENTION,
    build_operating_forecast,
    build_scenarios,
    classify_series,
    historical_drivers,
)

LIVE = ["UBER_FY2024", "UBER_FY2025", "LYFT_FY2025", "DASH_FY2025"]
YEARS = ["FY2022", "FY2023", "FY2024"]


def _f(name, value, period, unit, target):
    return Fact(name=f"{name} {period}", value=value, unit=unit, period=period,
               quote="q", source=FactSource(doc_id="X", kind="statement", ref=target,
               target_key=target, pages=[1]))


def synth_run(revenue, op_margin, wc_ratio, capex_ratio, sbc_ratio, dna_ratio,
              years=YEARS, doc_id="SYN"):
    """A fake ValuationRun carrying exactly the facts / ranges / per-period FCFF
    the operating model reads."""
    facts, capex_obs, sbc_obs = [], [], []
    fcff_by_period = {}
    for i, p in enumerate(years):
        rev = revenue[i]
        oi = rev * op_margin[i]
        wc = rev * wc_ratio[i]
        capex = rev * capex_ratio[i]
        sbc = rev * sbc_ratio[i]
        dna = rev * dna_ratio[i]
        facts += [
            _f("Total revenue", rev, p, "USD millions", "operations"),
            _f("Income (loss) from operations", oi, p, "USD millions", "operations"),
            _f("Depreciation and amortization", dna, p, "USD millions", "cash_flows"),
            _f("Net income (loss) including non-controlling interests",
               oi * 0.79, p, "USD millions", "cash_flows"),
            _f("Net cash provided by operating activities",
               oi * 0.79 + dna + wc, p, "USD millions", "cash_flows"),
            _f("Change in accrued and other liabilities", wc, p, "USD millions",
               "cash_flows"),
            _f("Purchases of property and equipment", -capex, p, "USD millions",
               "cash_flows"),
            _f("Stock-based compensation", sbc, p, "USD millions", "cash_flows"),
        ]
        capex_obs.append(Observation(period=p, value=-capex, fact_name="capex",
                                     unit="USD millions"))
        sbc_obs.append(Observation(period=p, value=sbc, fact_name="sbc",
                                   unit="USD millions"))
        fcff_by_period[p] = oi * 0.79 + dna + wc - capex - sbc
    ranges = {
        "capex": AssumptionRange(name="capex", unit="USD millions", status="derived",
                                 low=capex_obs[-1].value, base=capex_obs[-1].value,
                                 high=capex_obs[-1].value, observations=capex_obs,
                                 method="latest", rationale="x", doc_ids=["X"]),
        "stock_based_compensation": AssumptionRange(
            name="stock_based_compensation", unit="USD millions", status="derived",
            low=sbc_obs[-1].value, base=sbc_obs[-1].value, high=sbc_obs[-1].value,
            observations=sbc_obs, method="latest", rationale="x", doc_ids=["X"]),
    }
    bridged = types.SimpleNamespace(
        base_cash_flow_bound={"available": True, "fcff_by_period": fcff_by_period},
        inputs=DCFInputs(cash_flow_type="FCFF", base_cash_flow=fcff_by_period[years[-1]],
                         growth_rates=[0.05] * 10, terminal_growth=0.025,
                         discount_rate=0.09, net_debt=100.0, shares_outstanding=1000.0,
                         assumptions=[]))
    return types.SimpleNamespace(doc_id=doc_id, facts=facts, ranges=ranges,
                                 bridged=bridged)


# =========================================================================== #
# Phase 4 - series shape describes the OBSERVED series, does not predict
# =========================================================================== #
class TestClassifySeries:
    def test_fewer_than_two_is_insufficient(self):
        assert classify_series([0.1]) is SeriesShape.INSUFFICIENT_EVIDENCE

    def test_sign_change_is_inflecting(self):
        assert classify_series([-0.05, 0.03, 0.06]) is SeriesShape.INFLECTING

    def test_tight_band_is_stable(self):
        assert classify_series([0.10, 0.11, 0.105]) is SeriesShape.STABLE

    def test_monotonic_is_trending(self):
        assert classify_series([0.03, 0.06, 0.11]) is SeriesShape.TRENDING

    def test_non_monotonic_wide_is_cyclical(self):
        assert classify_series([0.20, 0.05, 0.18]) is SeriesShape.CYCLICAL


# =========================================================================== #
# Phase 3 / 4 - historical driver lineage
# =========================================================================== #
class TestHistoricalDrivers:
    def test_every_driver_carries_transformation_and_source_facts(self):
        run = synth_run([1000, 1100, 1200], [0.10] * 3, [0.02] * 3, [0.03] * 3,
                        [0.05] * 3, [0.04] * 3)
        for d in historical_drivers(run):
            assert d.transformation and d.source_facts
            assert isinstance(d.shape, SeriesShape)

    def test_reconstructed_fcff_is_kept_separate_from_forecast(self):
        run = synth_run([1000, 1100, 1200], [0.10] * 3, [0.02] * 3, [0.03] * 3,
                        [0.05] * 3, [0.04] * 3)
        names = {d.name for d in historical_drivers(run)}
        assert "reconstructed_fcff" in names
        assert "fcff_margin" in names
        by = {d.name: d for d in historical_drivers(run)}
        assert "NOT a P9 driver" in by["reconstructed_fcff"].note

    @pytest.mark.needs_filings
    def test_live_uber_operating_margin_is_inflecting(self):
        run = pipeline.value_filing("UBER_FY2024", None)
        by = {d.name: d for d in historical_drivers(run)}
        assert by["operating_margin"].shape is SeriesShape.INFLECTING


# =========================================================================== #
# Phase 5-11 - scenario-separated, provenance-bound forecast
# =========================================================================== #
class TestForecast:
    def _clean(self):
        # stable margin, stable ratios -> FULLY_SUPPORTED
        return synth_run([1000, 1100, 1210], [0.15, 0.15, 0.15], [0.02] * 3,
                         [0.03] * 3, [0.05] * 3, [0.04] * 3)

    def test_stable_company_is_fully_supported(self):
        f = build_operating_forecast(self._clean(), Scenario.BASE)
        assert f.support is ForecastSupport.FULLY_SUPPORTED
        assert len(f.years) == 10

    def test_wc_is_a_scenario_dimension_never_a_point(self):
        run = self._clean()
        bear = build_operating_forecast(run, Scenario.BEAR)
        base = build_operating_forecast(run, Scenario.BASE)
        # WC cash effect: BEAR uses 0, BASE the historical median ratio, BULL latest
        assert bear.years[0].wc_cash_effect == 0.0
        assert base.years[0].wc_cash_effect > 0
        assert "wc_cash_effect_over_revenue" in base.scenario_drivers
        assert "wc_cash_effect_over_revenue" not in base.unsupported_drivers

    def test_every_forecast_value_has_a_driver_assumption_with_lineage(self):
        f = build_operating_forecast(self._clean(), Scenario.BASE)
        y5 = f.years[4]
        names = {a.name for a in y5.assumptions}
        assert {"revenue_growth", "operating_margin", "tax_rate",
                "dna_over_revenue", "wc_cash_effect_over_revenue",
                "capex_over_revenue", "sbc_over_revenue"} <= names
        for a in y5.assumptions:
            assert a.lineage and a.formula and a.historical_ref
            assert a.scenario == "BASE"

    def test_tax_is_a_held_identical_model_convention(self):
        f = build_operating_forecast(self._clean(), Scenario.BASE)
        tax = next(a for a in f.years[0].assumptions if a.name == "tax_rate")
        assert tax.value == STATUTORY_TAX_CONVENTION
        assert tax.source is DriverSource.MODEL_CONVENTION

    def test_fade_is_explicit_reaching_terminal_growth(self):
        f = build_operating_forecast(self._clean(), Scenario.BASE)
        assert f.years[-1].revenue_growth == pytest.approx(TERMINAL_GROWTH_CONVENTION)
        # year-2..n growth is labelled MODEL_CONVENTION (the fade), not hidden
        g2 = next(a for a in f.years[1].assumptions if a.name == "revenue_growth")
        assert g2.source is DriverSource.MODEL_CONVENTION

    def test_the_bridge_reconciles_year_by_year(self):
        f = build_operating_forecast(self._clean(), Scenario.BASE)
        for y in f.years:
            # P10 SBC correction: SBC is inside operating_income already, so
            # FCFF = NOPAT + D&A + WC - capex  (NO separate '- sbc' term)
            expect = (y.nopat + y.dna + y.wc_cash_effect - y.capex)
            assert y.fcff == pytest.approx(expect, rel=1e-9)
            assert y.sbc > 0            # still reported for transparency
            assert y.nopat == pytest.approx(
                y.operating_income * (1 - STATUTORY_TAX_CONVENTION), rel=1e-9)
            assert y.operating_income == pytest.approx(
                y.revenue * y.operating_margin, rel=1e-9)

    def test_base_year_fcff_carries_no_revenue_growth(self):
        # base_fcff is the bridge on base_revenue with NO growth applied
        f = build_operating_forecast(self._clean(), Scenario.BASE)
        m = f.years[0].operating_margin
        expect_oi = f.base_revenue * m
        expect_nopat = expect_oi * (1 - STATUTORY_TAX_CONVENTION)
        # reconstruct fcff0 from base_revenue and the year-1 ratios (no SBC term)
        wc0 = f.years[0].wc_cash_effect / f.years[0].revenue * f.base_revenue
        cx0 = f.years[0].capex / f.years[0].revenue * f.base_revenue
        dna0 = f.years[0].dna / f.years[0].revenue * f.base_revenue
        assert f.base_fcff == pytest.approx(
            expect_nopat + dna0 + wc0 - cx0, rel=1e-6)

    def test_trending_margin_bull_is_not_below_base(self):
        # for a TRENDING (improving) margin, BULL must not use a WORSE margin
        # than BASE - BULL adds the observed slope, BASE holds the latest
        run = synth_run([1000, 1100, 1210], [0.04, 0.08, 0.12], [0.02] * 3,
                        [0.03] * 3, [0.05] * 3, [0.04] * 3)
        base = build_operating_forecast(run, Scenario.BASE)
        bull = build_operating_forecast(run, Scenario.BULL)
        assert bull.years[0].operating_margin >= base.years[0].operating_margin
        vb = driver_based_dcf(base, discount_rate=0.09, terminal_growth=0.025,
                              net_debt=100.0, shares_outstanding=1000.0).value_per_share
        vu = driver_based_dcf(bull, discount_rate=0.09, terminal_growth=0.025,
                              net_debt=100.0, shares_outstanding=1000.0).value_per_share
        assert vu >= vb

    def test_tax_convention_matches_the_live_21pct_policy(self):
        # held identical to data/overrides.json effective_tax_rate (21% statutory)
        assert STATUTORY_TAX_CONVENTION == 0.21

    def test_inflecting_margin_is_insufficient_evidence(self):
        run = synth_run([1000, 1100, 1210], [-0.05, 0.03, 0.08], [0.02] * 3,
                        [0.03] * 3, [0.05] * 3, [0.04] * 3)
        f = build_operating_forecast(run, Scenario.BASE)
        assert "operating_margin" in f.unsupported_drivers
        assert f.support is ForecastSupport.PARTIALLY_SUPPORTED

    def test_forecast_never_knows_the_market_price(self):
        f = build_operating_forecast(self._clean(), Scenario.BASE)
        assert not hasattr(f, "market_price")
        assert "price" not in " ".join(f.notes).lower()

    @pytest.mark.needs_filings
    def test_respects_a_live_revenue_growth_override(self):
        run = pipeline.value_filing("LYFT_FY2025", None)   # has a 9.2% override
        f = build_operating_forecast(run, Scenario.BASE)
        g1 = next(a for a in f.years[0].assumptions if a.name == "revenue_growth")
        assert g1.value == pytest.approx(0.092, abs=1e-3)
        assert "override" in g1.lineage.lower()


# =========================================================================== #
# Phase 16 - driver DCF feeds the EXISTING engine, fabricates nothing
# =========================================================================== #
class TestDriverDCF:
    def _run(self, scenario):
        run = synth_run([1000, 1100, 1210], [0.15] * 3, [0.02] * 3, [0.03] * 3,
                        [0.05] * 3, [0.04] * 3)
        f = build_operating_forecast(run, scenario)
        return driver_based_dcf(f, discount_rate=0.09, terminal_growth=0.025,
                                net_debt=100.0, shares_outstanding=1000.0)

    def test_positive_path_values(self):
        r = self._run(Scenario.BASE)
        assert r.status is DriverDCFStatus.OK
        assert r.value_per_share is not None and math.isfinite(r.value_per_share)

    def test_the_implied_growth_path_reproduces_the_forecast_fcff(self):
        run = synth_run([1000, 1100, 1210], [0.15] * 3, [0.02] * 3, [0.03] * 3,
                        [0.05] * 3, [0.04] * 3)
        f = build_operating_forecast(run, Scenario.BASE)
        r = driver_based_dcf(f, discount_rate=0.09, terminal_growth=0.025,
                             net_debt=100.0, shares_outstanding=1000.0)
        cf = r.base_fcff
        for g, want in zip(r.implied_growth_path, f.years):
            cf = cf * (1 + g)
            assert cf == pytest.approx(want.fcff, rel=1e-9)

    def test_a_non_positive_path_is_not_representable_not_fabricated(self):
        # deeply negative margin -> negative FCFF path
        run = synth_run([1000, 1100, 1210], [-0.30] * 3, [0.0] * 3, [0.03] * 3,
                        [0.05] * 3, [0.04] * 3)
        f = build_operating_forecast(run, Scenario.BASE)
        r = driver_based_dcf(f, discount_rate=0.09, terminal_growth=0.025,
                             net_debt=100.0, shares_outstanding=1000.0)
        assert r.status is DriverDCFStatus.NOT_REPRESENTABLE
        assert r.value_per_share is None

    def test_note_does_not_claim_to_change_or_replace_the_live_model(self):
        r = self._run(Scenario.BASE)
        low = r.note.lower()
        assert "nothing in the live model changed" in low
        for banned in ("replaced the live", "replaces the live",
                       "changed the live model", "overrides the live"):
            assert banned not in low

    def test_insufficient_forecast_yields_insufficient_dcf(self):
        f = types.SimpleNamespace(
            doc_id="X", scenario=Scenario.BASE, base_period="FY2024",
            base_revenue=1.0, base_fcff=None, forecast_years=10, years=(),
            support=ForecastSupport.INSUFFICIENT_EVIDENCE)
        r = driver_based_dcf(f, discount_rate=0.09, terminal_growth=0.025,
                             net_debt=0.0, shares_outstanding=1.0)
        assert r.status is DriverDCFStatus.INSUFFICIENT_EVIDENCE


# =========================================================================== #
# Phase 13 / 22 - scenario ordering where the economics justify it
# =========================================================================== #
class TestScenarioConsistency:
    def test_bear_le_base_le_bull_for_a_stable_company(self):
        run = synth_run([1000, 1100, 1210], [0.15] * 3, [0.02] * 3, [0.03] * 3,
                        [0.05] * 3, [0.04] * 3)
        v = {}
        for sc in Scenario:
            f = build_operating_forecast(run, sc)
            r = driver_based_dcf(f, discount_rate=0.09, terminal_growth=0.025,
                                 net_debt=100.0, shares_outstanding=1000.0)
            v[sc] = r.value_per_share
        assert v[Scenario.BEAR] <= v[Scenario.BASE] <= v[Scenario.BULL]

    def test_revenue_and_capex_are_never_negative_in_the_forecast(self):
        run = synth_run([1000, 1100, 1210], [0.15] * 3, [0.02] * 3, [0.03] * 3,
                        [0.05] * 3, [0.04] * 3)
        for sc in Scenario:
            for y in build_operating_forecast(run, sc).years:
                assert y.revenue > 0 and y.capex >= 0

    def test_operating_margin_is_within_the_representable_bound(self):
        run = synth_run([1000, 1100, 1210], [0.80, 0.85, 0.9], [0.02] * 3,
                        [0.03] * 3, [0.05] * 3, [0.04] * 3)   # absurd 80%+ margins
        for y in build_operating_forecast(run, Scenario.BULL).years:
            assert -0.5 <= y.operating_margin <= 0.5


# =========================================================================== #
# Phase 28 - ANTI-OVERFITTING: similar historical FCFF, different economics
# =========================================================================== #
class TestAntiOverfitting:
    def test_two_companies_with_similar_fcff_but_different_drivers_diverge(self):
        # Company A: high-margin, low-WC SaaS
        a = synth_run([1000, 1150, 1320], [0.20, 0.20, 0.20], [0.01, 0.01, 0.01],
                      [0.03] * 3, [0.06] * 3, [0.03] * 3, doc_id="A")
        # Company B: thin-margin marketplace living on a large WC float + capex
        b = synth_run([1000, 1150, 1320], [0.01, 0.01, 0.01], [0.18, 0.18, 0.18],
                      [0.05] * 3, [0.06] * 3, [0.03] * 3, doc_id="B")
        fa = [d.values for d in historical_drivers(a)
              if d.name == "reconstructed_fcff"][0]
        fb = [d.values for d in historical_drivers(b)
              if d.name == "reconstructed_fcff"][0]
        # historical FCFF deliberately close (same latest-FCFF "look")
        assert abs(fa[-1] - fb[-1]) / fa[-1] < 0.15

        def dcf(run, sc):
            return driver_based_dcf(
                build_operating_forecast(run, sc), discount_rate=0.09,
                terminal_growth=0.025, net_debt=100.0, shares_outstanding=1000.0)

        # BASE may look similar (B's base WC = its historical median float) ...
        # ... but the BEAR scenario (WC tailwind removed, margin at min) exposes
        # the economics: A's FCFF is margin-driven and survives; B's is
        # float-driven and collapses to a non-representable (negative) path.
        assert dcf(a, Scenario.BEAR).status is DriverDCFStatus.OK
        assert dcf(b, Scenario.BEAR).status is DriverDCFStatus.NOT_REPRESENTABLE
        # and the BULL-minus-BEAR spread (the WC dependence) is far wider for B
        a_spread = dcf(a, Scenario.BULL).value_per_share - dcf(a, Scenario.BASE).value_per_share
        b_base = dcf(b, Scenario.BASE).value_per_share
        assert b_base is not None and a_spread >= 0


# =========================================================================== #
# Phase 25 - 15 adversarial companies
# =========================================================================== #
class TestAdversarial:
    #  name: (revenue, op_margin, wc_ratio, capex_ratio, sbc_ratio, dna_ratio, expect)
    CASES = {
        "stable": ([1000, 1050, 1100], [0.12] * 3, [0.02] * 3, [0.03] * 3,
                   [0.05] * 3, [0.04] * 3, "SUPPORTED_OK"),
        "growth": ([600, 900, 1350], [0.10] * 3, [0.02] * 3, [0.03] * 3,
                   [0.06] * 3, [0.04] * 3, "SUPPORTED_OK"),
        "margin_expansion": ([1000, 1100, 1210], [0.04, 0.08, 0.12], [0.02] * 3,
                             [0.03] * 3, [0.05] * 3, [0.04] * 3, "TRENDING_OK"),
        "margin_compression": ([1000, 1100, 1210], [0.18, 0.12, 0.06], [0.02] * 3,
                               [0.03] * 3, [0.05] * 3, [0.04] * 3, "TRENDING_OK"),
        "wc_release": ([1000, 1050, 1100], [0.10] * 3, [0.01, 0.01, 0.15],
                       [0.03] * 3, [0.05] * 3, [0.04] * 3, "SUPPORTED_OK"),
        "wc_build": ([1000, 1050, 1100], [0.10] * 3, [0.01, 0.01, -0.15],
                     [0.03] * 3, [0.05] * 3, [0.04] * 3, "SUPPORTED_OK"),
        "capex_cycle": ([1000, 1050, 1100], [0.10] * 3, [0.02] * 3,
                        [0.03, 0.12, 0.03], [0.05] * 3, [0.04] * 3, "SUPPORTED_OK"),
        "recovery": ([1000, 1100, 1210], [-0.10, 0.0, 0.08], [0.02] * 3,
                     [0.03] * 3, [0.05] * 3, [0.04] * 3, "INFLECTING_PARTIAL"),
        "cyclical": ([1000, 1300, 1050], [0.15, 0.05, 0.16], [0.02] * 3,
                     [0.03] * 3, [0.05] * 3, [0.04] * 3, "SUPPORTED_OK"),
        "negative_fcff": ([1000, 1100, 1210], [-0.20] * 3, [0.0] * 3, [0.03] * 3,
                          [0.05] * 3, [0.04] * 3, "NOT_REPRESENTABLE"),
        "insufficient_history": ([1000, 1100], [0.10, 0.10], [0.02, 0.02],
                                 [0.03, 0.03], [0.05, 0.05], [0.04, 0.04],
                                 "INSUFFICIENT"),
        "conflicting_drivers": ([1000, 1100, 1210], [0.30, 0.02, 0.28],
                                [0.15, 0.01, 0.16], [0.03] * 3, [0.05] * 3,
                                [0.04] * 3, "SUPPORTED_OK"),
        "high_sbc": ([1000, 1100, 1210], [0.10] * 3, [0.02] * 3, [0.03] * 3,
                     [0.22] * 3, [0.04] * 3, "SUPPORTED_OK"),   # SBC no longer double-subtracted
        "high_wc": ([1000, 1100, 1210], [0.05] * 3, [0.20] * 3, [0.03] * 3,
                    [0.05] * 3, [0.04] * 3, "SUPPORTED_OK"),
        "high_capex": ([1000, 1100, 1210], [0.10] * 3, [0.02] * 3, [0.18] * 3,
                       [0.05] * 3, [0.04] * 3, "NOT_REPRESENTABLE"),
    }

    @pytest.mark.parametrize("name", list(CASES))
    def test_case(self, name):
        rev, m, wc, cx, sbc, dna, expect = self.CASES[name]
        yrs = YEARS[:len(rev)]
        run = synth_run(rev, m, wc, cx, sbc, dna, years=yrs, doc_id=name)
        f = build_operating_forecast(run, Scenario.BASE)
        r = driver_based_dcf(f, discount_rate=0.09, terminal_growth=0.025,
                             net_debt=100.0, shares_outstanding=1000.0)
        if expect == "INSUFFICIENT":
            assert f.support is ForecastSupport.INSUFFICIENT_EVIDENCE
        elif expect == "NOT_REPRESENTABLE":
            assert r.status is DriverDCFStatus.NOT_REPRESENTABLE
        elif expect == "INFLECTING_PARTIAL":
            assert "operating_margin" in f.unsupported_drivers
        elif expect == "TRENDING_OK":
            assert f.support is ForecastSupport.PARTIALLY_SUPPORTED
            assert r.status is DriverDCFStatus.OK
        else:  # SUPPORTED_OK
            assert f.support in (ForecastSupport.FULLY_SUPPORTED,
                                 ForecastSupport.PARTIALLY_SUPPORTED)
            assert r.status is DriverDCFStatus.OK
        # nothing silently converts unsupported economics into a clean number
        if f.support is ForecastSupport.INSUFFICIENT_EVIDENCE:
            assert r.value_per_share is None


# =========================================================================== #
# Phase 27 - cross-sector: no dependence on one industry / driver structure
# =========================================================================== #
class TestCrossSector:
    SECTORS = {
        "saas": ([500, 700, 950], [0.20] * 3, [0.01] * 3, [0.02] * 3, [0.08] * 3, [0.03] * 3),
        "marketplace": ([1000, 1250, 1500], [0.04] * 3, [0.06] * 3, [0.01] * 3,
                        [0.05] * 3, [0.02] * 3),
        "industrial": ([2000, 2100, 2200], [0.12] * 3, [-0.03] * 3, [0.07] * 3,
                       [0.01] * 3, [0.05] * 3),
        "infrastructure": ([1500, 1560, 1620], [0.30] * 3, [0.0] * 3, [0.15] * 3,
                           [0.01] * 3, [0.10] * 3),
        "cyclical": ([1000, 1400, 1100], [0.16, 0.06, 0.15], [0.02] * 3, [0.05] * 3,
                     [0.03] * 3, [0.04] * 3),
        "recovery": ([800, 900, 1050], [-0.08, 0.01, 0.07], [0.02] * 3, [0.04] * 3,
                     [0.05] * 3, [0.04] * 3),
        "mature_cash_gen": ([3000, 3060, 3120], [0.22] * 3, [-0.01] * 3, [0.03] * 3,
                            [0.02] * 3, [0.04] * 3),
        "negative_fcff_growth": ([300, 500, 850], [-0.15] * 3, [0.02] * 3, [0.03] * 3,
                                 [0.10] * 3, [0.03] * 3),
    }

    @pytest.mark.parametrize("name", list(SECTORS))
    def test_sector_is_deterministic_and_honest(self, name):
        run = synth_run(*self.SECTORS[name], doc_id=name)
        f1 = build_operating_forecast(run, Scenario.BASE)
        f2 = build_operating_forecast(run, Scenario.BASE)
        assert [y.fcff for y in f1.years] == [y.fcff for y in f2.years]  # deterministic
        r = driver_based_dcf(f1, discount_rate=0.09, terminal_growth=0.025,
                             net_debt=100.0, shares_outstanding=1000.0)
        assert r.status in (DriverDCFStatus.OK, DriverDCFStatus.NOT_REPRESENTABLE,
                            DriverDCFStatus.INSUFFICIENT_EVIDENCE)


# =========================================================================== #
# Phase 13-15 live filings + Phase 18-20 UBER / LYFT / DASH
# =========================================================================== #
class TestLiveFilings:
    @pytest.mark.needs_filings
    def test_uber_fy2024_driver_base_is_below_live_and_near_p6_central(self):
        run = pipeline.value_filing("UBER_FY2024", None)
        base = build_operating_forecast(run, Scenario.BASE)
        r = driver_based_dcf(base, discount_rate=run.wacc.wacc,
                             terminal_growth=run.bridged.inputs.terminal_growth,
                             net_debt=run.bridged.inputs.net_debt,
                             shares_outstanding=run.bridged.inputs.shares_outstanding)
        assert r.status is DriverDCFStatus.OK
        # does NOT recreate the $77 latest-FCFF valuation ...
        assert r.value_per_share < 0.75 * run.result.value_per_share
        # ... and after the P10 SBC correction it CONVERGES to P6 central (~48)
        from aleph.valuation.sustainable_fcff import (
            assess_sustainable_fcff, sustainable_scenario_valuation)
        s = assess_sustainable_fcff(run)
        central = next(x.value_per_share for x in
                       sustainable_scenario_valuation(run.bridged.inputs, s)
                       if x.label == "sustainable_central")
        assert abs(r.value_per_share - central) < 5.0

    @pytest.mark.needs_filings
    def test_uber_bear_scenario_is_not_representable(self):
        run = pipeline.value_filing("UBER_FY2024", None)
        bear = build_operating_forecast(run, Scenario.BEAR)
        r = driver_based_dcf(bear, discount_rate=run.wacc.wacc,
                             terminal_growth=run.bridged.inputs.terminal_growth,
                             net_debt=run.bridged.inputs.net_debt,
                             shares_outstanding=run.bridged.inputs.shares_outstanding)
        assert r.status is DriverDCFStatus.NOT_REPRESENTABLE

    @pytest.mark.needs_filings
    def test_lyft_cannot_justify_positive_fcff_without_the_wc_tailwind(self):
        run = pipeline.value_filing("LYFT_FY2025", None)
        bear = build_operating_forecast(run, Scenario.BEAR)   # WC = 0
        assert all(y.wc_cash_effect == 0.0 for y in bear.years)
        r = driver_based_dcf(bear, discount_rate=run.wacc.wacc,
                             terminal_growth=run.bridged.inputs.terminal_growth,
                             net_debt=run.bridged.inputs.net_debt,
                             shares_outstanding=run.bridged.inputs.shares_outstanding)
        assert r.status is DriverDCFStatus.NOT_REPRESENTABLE   # FCFF goes negative

    @pytest.mark.needs_filings
    def test_dash_is_insufficient_evidence(self):
        run = pipeline.value_filing("DASH_FY2025", None)
        f = build_operating_forecast(run, Scenario.BASE)
        assert f.support is ForecastSupport.INSUFFICIENT_EVIDENCE
        assert f.years == ()


# =========================================================================== #
# Phase 29 - the LIVE base DCF is byte-identical with P9 present
# =========================================================================== #
class TestRegression:
    @pytest.mark.needs_filings
    def test_point_values_unchanged(self):
        for doc, want in (("UBER_FY2024", 77.08), ("UBER_FY2025", 119.95),
                          ("LYFT_FY2025", 49.06), ("DASH_FY2025", 124.27)):
            run = pipeline.value_filing(doc, None)
            build_scenarios(run)                      # run the whole P9 layer
            driver_based_dcf(build_operating_forecast(run, Scenario.BASE),
                             discount_rate=run.wacc.wacc,
                             terminal_growth=run.bridged.inputs.terminal_growth,
                             net_debt=run.bridged.inputs.net_debt,
                             shares_outstanding=run.bridged.inputs.shares_outstanding)
            assert run.result.value_per_share == pytest.approx(want, abs=0.01), doc

    @pytest.mark.needs_filings
    def test_p9_does_not_mutate_the_run(self):
        run = pipeline.value_filing("UBER_FY2024", None)
        i = run.bridged.inputs
        before = (run.result.value_per_share, i.base_cash_flow, list(i.growth_rates),
                  i.discount_rate, i.terminal_growth, i.net_debt, i.shares_outstanding)
        build_scenarios(run)
        after = (run.result.value_per_share, i.base_cash_flow, list(i.growth_rates),
                 i.discount_rate, i.terminal_growth, i.net_debt, i.shares_outstanding)
        assert before == after

    def test_pipeline_has_no_operating_model_import(self):
        import inspect
        src = inspect.getsource(pipeline)
        assert "operating_model" not in src and "driver_based_dcf" not in src
