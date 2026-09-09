"""P8 - evidence depth, multi-period accounting & cash-flow data quality.

Phases 3-14, 19-20: caption -> category mapping, working-capital sign
integrity, CFO reconciliation with residual retention, conflicting/ambiguous
observations, period & unit integrity, the per-period evidence scorecard,
20 adversarial data fixtures, and proof that P6 numbers are unchanged.
"""
import math
import types

import pytest

import aleph.valuation.pipeline as pipeline
from aleph.schemas.evidence import Fact, FactSource
from aleph.valuation.evidence_depth import (
    Category,
    CapexSplitStatus,
    EvidenceStatus,
    MappingConfidence,
    OneOffTier,
    PeriodScore,
    ReconciliationStatus,
    SignSemantics,
    UncertaintyVerdict,
    WCSubcategory,
    assess_evidence_depth,
    map_reconciliation_caption,
    wc_sign_semantics,
)

LIVE = ["UBER_FY2024", "UBER_FY2025", "LYFT_FY2025", "DASH_FY2025"]


def cf(name, value, period, unit="USD millions"):
    return Fact(name=f"{name} {period}", value=value, unit=unit, period=period,
               quote="q", source=FactSource(doc_id="X", kind="statement",
               ref="cash_flows", target_key="cash_flows", pages=[1]))


def fake_run(doc_id, facts, ranges=None, fcff_by_period=None):
    bound = ({"available": True, "fcff_by_period": fcff_by_period}
             if fcff_by_period else {"available": False})
    bridged = types.SimpleNamespace(base_cash_flow_bound=bound)
    return types.SimpleNamespace(doc_id=doc_id, facts=facts,
                                 ranges=ranges or {}, bridged=bridged)


# =========================================================================== #
# Phase 4 / 7 / 10 - caption -> normalized category, UNCLASSIFIED not a guess
# =========================================================================== #
class TestCaptionMapping:
    @pytest.mark.parametrize("name,cat,sub", [
        ("Change in accounts receivable", Category.WORKING_CAPITAL,
         WCSubcategory.ACCOUNTS_RECEIVABLE),
        ("Change in accounts payable", Category.WORKING_CAPITAL,
         WCSubcategory.ACCOUNTS_PAYABLE),
        ("Change in accrued and other liabilities", Category.WORKING_CAPITAL,
         WCSubcategory.ACCRUED_LIABILITIES),
        ("Change in accrued insurance reserves", Category.WORKING_CAPITAL,
         WCSubcategory.INSURANCE_RESERVES),
        ("Change in prepaid expenses and other assets", Category.WORKING_CAPITAL,
         WCSubcategory.PREPAID_EXPENSES),
        ("Change in operating lease liabilities", Category.WORKING_CAPITAL,
         WCSubcategory.OPERATING_LEASE),
        ("Funds held at payment processors", Category.WORKING_CAPITAL,
         WCSubcategory.FUNDS_HELD),
        ("Deferred income taxes", Category.NON_CASH_RECONCILIATION, None),
        ("Depreciation and amortization", Category.NON_CASH_RECONCILIATION, None),
        ("Unrealized (gain) loss on debt and equity securities, net",
         Category.NON_CASH_RECONCILIATION, None),
        ("Net cash provided by operating activities", Category.CFO_SUBTOTAL, None),
        ("Purchases of property and equipment", Category.CAPEX, None),
        ("Stock-based compensation", Category.SBC, None),
        ("Net income (loss) including non-controlling interests",
         Category.NET_INCOME, None),
        ("Cash, cash equivalents - end of period", Category.CASH_BALANCE, None),
    ])
    def test_known_captions_map(self, name, cat, sub):
        m = map_reconciliation_caption(name)
        assert m.category is cat
        assert m.wc_subcategory is sub

    def test_an_unrecognised_wc_caption_is_wc_unclassified_low_confidence(self):
        m = map_reconciliation_caption("Change in widget deposits held in trust")
        assert m.category is Category.WORKING_CAPITAL
        assert m.wc_subcategory is WCSubcategory.WC_UNCLASSIFIED
        assert m.mapping_confidence is MappingConfidence.LOW

    def test_an_unmappable_caption_is_unclassified_never_forced(self):
        m = map_reconciliation_caption("Payments for operating lease liabilities")
        assert m.category is Category.UNCLASSIFIED
        assert m.mapping_confidence is MappingConfidence.LOW

    def test_a_recognised_subcategory_maps_at_high_confidence_with_a_rationale(self):
        m = map_reconciliation_caption("Change in accounts receivable")
        assert m.mapping_confidence is MappingConfidence.HIGH
        assert m.rationale and m.sign_semantics is SignSemantics.CASH_EFFECT

    def test_caption_drift_across_years_maps_to_the_same_subcategory(self):
        for v in ("Change in accrued expenses and other liabilities",
                  "Change in accrued and other liabilities",
                  "Accrued expenses and other current liabilities (change)"):
            assert map_reconciliation_caption(v).wc_subcategory is \
                WCSubcategory.ACCRUED_LIABILITIES

    def test_two_accrued_captions_are_not_merged_with_insurance(self):
        # 'accrued insurance reserves' must be INSURANCE, not generic accrued
        assert map_reconciliation_caption("Change in accrued insurance reserves"
                                          ).wc_subcategory is WCSubcategory.INSURANCE_RESERVES
        assert map_reconciliation_caption("Change in accrued expenses"
                                          ).wc_subcategory is WCSubcategory.ACCRUED_LIABILITIES


# =========================================================================== #
# Phase 5 - working-capital sign integrity (9 movements)
# =========================================================================== #
class TestWCSignIntegrity:
    def test_ar_increase_is_a_cash_outflow(self):
        s = wc_sign_semantics(WCSubcategory.ACCOUNTS_RECEIVABLE, -50.0)
        assert s["cash_direction"] == "OUTFLOW"
        assert s["implied_balance_direction"] == "INCREASE"

    def test_ar_decrease_is_a_cash_inflow(self):
        s = wc_sign_semantics(WCSubcategory.ACCOUNTS_RECEIVABLE, +50.0)
        assert s["cash_direction"] == "INFLOW"
        assert s["implied_balance_direction"] == "DECREASE"

    def test_ap_increase_is_a_cash_inflow(self):
        s = wc_sign_semantics(WCSubcategory.ACCOUNTS_PAYABLE, +40.0)
        assert s["cash_direction"] == "INFLOW"
        assert s["implied_balance_direction"] == "INCREASE"

    def test_ap_decrease_is_a_cash_outflow(self):
        s = wc_sign_semantics(WCSubcategory.ACCOUNTS_PAYABLE, -40.0)
        assert s["cash_direction"] == "OUTFLOW"
        assert s["implied_balance_direction"] == "DECREASE"

    def test_accrued_liability_increase_is_a_cash_inflow(self):
        s = wc_sign_semantics(WCSubcategory.ACCRUED_LIABILITIES, +330.0)
        assert s["cash_direction"] == "INFLOW"
        assert s["implied_balance_direction"] == "INCREASE"

    def test_accrued_liability_decrease_is_a_cash_outflow(self):
        s = wc_sign_semantics(WCSubcategory.ACCRUED_LIABILITIES, -70.0)
        assert s["cash_direction"] == "OUTFLOW"
        assert s["implied_balance_direction"] == "DECREASE"

    def test_prepaid_asset_increase_is_a_cash_outflow(self):
        s = wc_sign_semantics(WCSubcategory.PREPAID_EXPENSES, -694.0)
        assert s["cash_direction"] == "OUTFLOW"
        assert s["implied_balance_direction"] == "INCREASE"

    def test_prepaid_asset_decrease_is_a_cash_inflow(self):
        s = wc_sign_semantics(WCSubcategory.PREPAID_EXPENSES, +120.0)
        assert s["cash_direction"] == "INFLOW"
        assert s["implied_balance_direction"] == "DECREASE"

    def test_mixed_wc_movement_preserves_each_components_meaning(self):
        ar = wc_sign_semantics(WCSubcategory.ACCOUNTS_RECEIVABLE, -142.0)
        ins = wc_sign_semantics(WCSubcategory.INSURANCE_RESERVES, +2819.0)
        assert ar["cash_direction"] == "OUTFLOW" and ins["cash_direction"] == "INFLOW"
        # the sum is a net inflow but the components are not collapsed
        assert ar["cash_effect"] + ins["cash_effect"] == pytest.approx(2677.0)

    def test_zero_movement_is_neutral(self):
        s = wc_sign_semantics(WCSubcategory.ACCOUNTS_PAYABLE, 0.0)
        assert s["cash_direction"] == "NEUTRAL"
        assert s["sign_semantics"] == SignSemantics.CASH_EFFECT.value


# =========================================================================== #
# Phase 6 - CFO reconciliation, residual retained
# =========================================================================== #
class TestReconciliation:
    def _run(self, cfo, ni, noncash, wc, period="FY2024"):
        facts = [cf("Net income (loss) including non-controlling interests", ni, period),
                 cf("Net cash provided by operating activities", cfo, period)]
        for i, v in enumerate(noncash):
            facts.append(cf(f"Depreciation and amortization line{i}", v, period))
        for nm, v in wc:
            facts.append(cf(nm, v, period))
        # a second period so period-depth logic has >1
        for f in list(facts):
            facts.append(cf(f.name.rsplit(" ", 1)[0], f.value, "FY2023"))
        return assess_evidence_depth(fake_run("X", facts))

    def test_a_clean_period_reconciles(self):
        r = self._run(cfo=2000, ni=1400, noncash=[300, 100],
                      wc=[("Change in accounts receivable", -50),
                          ("Change in accrued insurance reserves", 250)])
        fy24 = next(p for p in r.period_evidence if p.period == "FY2024")
        assert fy24.reconciliation_status is ReconciliationStatus.RECONCILED
        assert abs(fy24.residual) < 1

    def test_a_broken_period_reports_failed_and_keeps_the_residual(self):
        r = self._run(cfo=2000, ni=800, noncash=[300],   # NI ~900 too low
                      wc=[("Change in accounts payable", 100)])
        fy24 = next(p for p in r.period_evidence if p.period == "FY2024")
        assert fy24.reconciliation_status is ReconciliationStatus.RECONCILIATION_FAILED
        assert fy24.score is PeriodScore.RECONCILIATION_FAILED
        assert abs(fy24.residual) > 100          # retained, not discarded
        assert any("residual" in n for n in fy24.notes)

    def test_missing_cfo_subtotal_is_insufficient_evidence(self):
        facts = [cf("Net income (loss)", 1000, "FY2024"),
                 cf("Net income (loss)", 900, "FY2023"),
                 cf("Depreciation and amortization", 100, "FY2024"),
                 cf("Depreciation and amortization", 90, "FY2023")]
        r = assess_evidence_depth(fake_run("X", facts))
        fy24 = next(p for p in r.period_evidence if p.period == "FY2024")
        assert fy24.reconciliation_status is ReconciliationStatus.INSUFFICIENT_EVIDENCE

    def test_tolerance_is_not_widened_to_force_a_pass(self):
        from aleph.valuation.evidence_depth import RECON_TOL_FRAC, RECON_TOL_ABS
        from aleph.valuation.sustainable_fcff import (
            RECON_TOL_FRAC as P6_FRAC, RECON_TOL_ABS as P6_ABS)
        assert (RECON_TOL_FRAC, RECON_TOL_ABS) == (P6_FRAC, P6_ABS)


# =========================================================================== #
# Phase 3 / 14 - extracted vs verified vs economically usable; the scorecard
# =========================================================================== #
class TestEvidenceStatusAndScore:
    def test_quarterly_period_is_insufficient_evidence(self):
        facts = [cf("Net income (loss)", 100, "Q3 FY2024"),
                 cf("Net cash provided by operating activities", 200, "Q3 FY2024"),
                 cf("Net income (loss)", 90, "FY2023"),
                 cf("Net cash provided by operating activities", 190, "FY2023")]
        r = assess_evidence_depth(fake_run("X", facts))
        q = next(p for p in r.period_evidence if p.period == "Q3 FY2024")
        assert q.period_type == "QUARTERLY"
        assert q.score is PeriodScore.INSUFFICIENT_EVIDENCE

    def test_an_unclassified_cash_flow_caption_downgrades_the_period(self):
        facts = [cf("Net income (loss) including non-controlling interests", 1000, "FY2024"),
                 cf("Net cash provided by operating activities", 1050, "FY2024"),
                 cf("Depreciation and amortization", 60, "FY2024"),
                 cf("Payments for operating lease liabilities", -10, "FY2024"),
                 cf("Net income (loss) including non-controlling interests", 900, "FY2023"),
                 cf("Net cash provided by operating activities", 960, "FY2023"),
                 cf("Depreciation and amortization", 60, "FY2023")]
        r = assess_evidence_depth(fake_run("X", facts))
        fy24 = next(p for p in r.period_evidence if p.period == "FY2024")
        assert fy24.unclassified_wc                      # caption retained
        assert fy24.score is PeriodScore.PARTIALLY_EVIDENCED

    def test_live_filings_annual_periods_are_fully_or_reconciliation_failed(self):
        for doc in LIVE:
            r = assess_evidence_depth(pipeline.value_filing(doc, None))
            for pe in r.period_evidence:
                assert pe.period_type == "ANNUAL"
                assert pe.score in (PeriodScore.FULLY_EVIDENCED,
                                    PeriodScore.RECONCILIATION_FAILED,
                                    PeriodScore.PARTIALLY_EVIDENCED)


# =========================================================================== #
# Phase 8 - capex split evidence
# =========================================================================== #
class TestCapexEvidence:
    def test_live_filings_do_not_support_a_capex_split(self):
        for doc in LIVE:
            r = assess_evidence_depth(pipeline.value_filing(doc, None))
            assert r.capex_evidence.status is CapexSplitStatus.CAPEX_SPLIT_NOT_SUPPORTED

    def test_a_disclosed_split_is_supported(self):
        facts = [cf("Net income (loss)", 1000, "FY2024"),
                 cf("Net cash provided by operating activities", 1000, "FY2024"),
                 cf("Maintenance capital expenditures", -100, "FY2024"),
                 cf("Growth capital expenditures", -300, "FY2024"),
                 cf("Net income (loss)", 900, "FY2023"),
                 cf("Net cash provided by operating activities", 900, "FY2023"),
                 cf("Maintenance capital expenditures", -90, "FY2023"),
                 cf("Growth capital expenditures", -250, "FY2023")]
        r = assess_evidence_depth(fake_run("X", facts))
        assert r.capex_evidence.status is CapexSplitStatus.CAPEX_SPLIT_SUPPORTED

    def test_one_capex_line_plus_text_mention_is_still_not_supported(self):
        facts = [cf("Net income (loss)", 1000, "FY2024"),
                 cf("Net cash provided by operating activities", 1000, "FY2024"),
                 Fact(name="Purchases of property and equipment FY2024", value=-200,
                      unit="USD millions", period="FY2024",
                      quote="we invested in capacity expansion and new facilities",
                      source=FactSource(doc_id="X", kind="statement", ref="cash_flows",
                                        target_key="cash_flows", pages=[1])),
                 cf("Net income (loss)", 900, "FY2023"),
                 cf("Net cash provided by operating activities", 900, "FY2023"),
                 cf("Purchases of property and equipment", -180, "FY2023")]
        r = assess_evidence_depth(fake_run("X", facts))
        assert r.capex_evidence.status is CapexSplitStatus.CAPEX_SPLIT_NOT_SUPPORTED


# =========================================================================== #
# Phase 9 - one-off evidence tiers
# =========================================================================== #
class TestOneOffEvidence:
    def test_live_filings_have_no_corroborating_cash_one_off(self):
        for doc in LIVE:
            r = assess_evidence_depth(pipeline.value_filing(doc, None))
            assert r.one_off_evidence.corroborating_items == ()
            assert r.one_off_evidence.tier in (OneOffTier.EXPLICIT,
                                               OneOffTier.PATTERN_ONLY,
                                               OneOffTier.NONE)

    def test_explicit_language_on_a_noncash_line_does_not_become_a_cash_one_off(self):
        r = assess_evidence_depth(pipeline.value_filing("UBER_FY2024", None))
        # impairments / revaluations are flagged EXPLICIT but are non-cash
        assert any("impairment" in x.lower() or "revaluation" in x.lower()
                   for x in r.one_off_evidence.explicit_items)
        assert r.one_off_evidence.corroborating_items == ()

    def test_pattern_evidence_alone_never_creates_an_adjustment(self):
        r = assess_evidence_depth(pipeline.value_filing("UBER_FY2025", None))
        assert r.one_off_evidence.tier is OneOffTier.PATTERN_ONLY
        assert "never creates an adjustment" in r.one_off_evidence.note


# =========================================================================== #
# Phase 15 - P6 numbers are UNCHANGED; only the lineage is richer
# =========================================================================== #
class TestP6Impact:
    def test_p8_wc_component_sum_equals_p6_wc_total(self):
        for doc in LIVE:
            r = assess_evidence_depth(pipeline.value_filing(doc, None))
            assert r.p6_p8_wc_agree, doc
            for p in r.periods:
                assert r.p6_wc_total_by_period[p] == pytest.approx(
                    r.p8_wc_component_sum_by_period[p], abs=1e-3)

    def test_p6_sustainable_range_is_unchanged_by_p8(self):
        from aleph.valuation.sustainable_fcff import assess_sustainable_fcff
        run = pipeline.value_filing("UBER_FY2024", None)
        before = assess_sustainable_fcff(run)
        assess_evidence_depth(run)             # run P8
        after = assess_sustainable_fcff(run)
        assert (before.low, before.central, before.high) == \
               (after.low, after.central, after.high)
        assert before.regime is after.regime


# =========================================================================== #
# Phase 19 - regression: base valuations and P3/P4/P5/P6 guarantees intact
# =========================================================================== #
class TestRegression:
    def test_base_point_values_unchanged(self):
        for doc, want in (("UBER_FY2024", 77.08), ("UBER_FY2025", 119.95),
                          ("LYFT_FY2025", 49.06), ("DASH_FY2025", 124.27)):
            run = pipeline.value_filing(doc, None)
            assess_evidence_depth(run)
            assert run.result.value_per_share == pytest.approx(want, abs=0.01), doc

    def test_pipeline_has_no_evidence_depth_import(self):
        import inspect
        assert "evidence_depth" not in inspect.getsource(pipeline)

    def test_assess_does_not_mutate_the_run(self):
        run = pipeline.value_filing("UBER_FY2024", None)
        i = run.bridged.inputs
        before = (run.result.value_per_share, i.base_cash_flow,
                  list(i.growth_rates), i.discount_rate, i.terminal_growth,
                  i.net_debt, i.shares_outstanding,
                  dict(run.bridged.base_cash_flow_bound.get("fcff_by_period") or {}))
        assess_evidence_depth(run)
        assess_evidence_depth(run)
        after = (run.result.value_per_share, i.base_cash_flow,
                 list(i.growth_rates), i.discount_rate, i.terminal_growth,
                 i.net_debt, i.shares_outstanding,
                 dict(run.bridged.base_cash_flow_bound.get("fcff_by_period") or {}))
        assert before == after


# =========================================================================== #
# Phase 20 - 20 adversarial data fixtures; fail visibly, never fabricate
# =========================================================================== #
class TestAdversarialFixtures:
    def _base(self, period="FY2024"):
        return [cf("Net income (loss) including non-controlling interests", 1000, period),
                cf("Net cash provided by operating activities", 1350, period),
                cf("Depreciation and amortization", 200, period)]

    def _two_periods(self, extra_2024, extra_2023):
        f = self._base("FY2024") + self._base("FY2023")
        return f + extra_2024 + [cf(x.name.rsplit(" ", 1)[0], x.value, "FY2023")
                                 for x in extra_2023]

    def test_01_correctly_mapped_wc(self):
        f = self._two_periods([cf("Change in accounts receivable", 150, "FY2024")],
                              [cf("Change in accounts receivable", 150, "FY2024")])
        r = assess_evidence_depth(fake_run("X", f))
        fy = next(p for p in r.period_evidence if p.period == "FY2024")
        assert "ACCOUNTS_RECEIVABLE" in fy.wc_by_subcategory

    def test_02_ambiguous_wc_caption_is_wc_unclassified(self):
        m = map_reconciliation_caption("Change in other balances, net")
        assert m.wc_subcategory is WCSubcategory.WC_UNCLASSIFIED

    def test_03_conflicting_wc_captions_both_retained(self):
        f = self._two_periods(
            [cf("Change in accounts receivable", 150, "FY2024"),
             cf("Change in trade receivables", -150, "FY2024")],
            [cf("Change in accounts receivable", 150, "FY2024"),
             cf("Change in trade receivables", -150, "FY2024")])
        r = assess_evidence_depth(fake_run("X", f))
        fy = next(p for p in r.period_evidence if p.period == "FY2024")
        # both mapped to AR; their sum is what enters - not silently one
        assert fy.wc_by_subcategory.get("ACCOUNTS_RECEIVABLE") == pytest.approx(0.0)

    def test_04_missing_wc_component_still_reconciles_or_fails_visibly(self):
        f = self._two_periods([], [])
        r = assess_evidence_depth(fake_run("X", f))
        fy = next(p for p in r.period_evidence if p.period == "FY2024")
        # NI 1000 + D&A 200 = 1200 vs CFO 1350 -> residual 150 retained
        assert fy.residual == pytest.approx(150.0)

    def test_05_sign_reversal_is_caught_by_sign_semantics(self):
        up = wc_sign_semantics(WCSubcategory.ACCOUNTS_RECEIVABLE, +100)
        down = wc_sign_semantics(WCSubcategory.ACCOUNTS_RECEIVABLE, -100)
        assert up["implied_balance_direction"] != down["implied_balance_direction"]

    def test_06_mixed_units_do_not_silently_continue(self):
        f = [cf("Net income (loss)", 1_000_000, "FY2024", "USD thousands"),
             cf("Net cash provided by operating activities", 1350, "FY2024", "USD millions"),
             cf("Net income (loss)", 900_000, "FY2023", "USD thousands"),
             cf("Net cash provided by operating activities", 1200, "FY2023", "USD millions")]
        r = assess_evidence_depth(fake_run("X", f))
        fy = next(p for p in r.period_evidence if p.period == "FY2024")
        # NI scaled to 1000 (millions), CFO 1350 -> residual 350, retained
        assert fy.reconciliation_status is ReconciliationStatus.RECONCILIATION_FAILED

    def test_07_unrecognised_unit_is_dropped_not_guessed(self):
        f = [cf("Change in accounts receivable", 100, "FY2024", "gallons")]
        f += self._base("FY2024") + self._base("FY2023")
        r = assess_evidence_depth(fake_run("X", f))
        fy = next(p for p in r.period_evidence if p.period == "FY2024")
        assert "ACCOUNTS_RECEIVABLE" not in fy.wc_by_subcategory

    def test_07b_non_usd_currency_line_is_dropped_not_converted(self):
        f = [cf("Change in accounts receivable", 100, "FY2024", "EUR millions")]
        f += self._base("FY2024") + self._base("FY2023")
        r = assess_evidence_depth(fake_run("X", f))
        fy = next(p for p in r.period_evidence if p.period == "FY2024")
        assert "ACCOUNTS_RECEIVABLE" not in fy.wc_by_subcategory

    def test_13b_two_generic_capex_lines_without_split_language_not_supported(self):
        f = self._base("FY2024") + self._base("FY2023")
        f += [cf("Purchases of property and equipment", -100, "FY2024"),
              cf("Purchases of intangible assets and capital expenditure", -40, "FY2024"),
              cf("Purchases of property and equipment", -90, "FY2023"),
              cf("Purchases of intangible assets and capital expenditure", -35, "FY2023")]
        r = assess_evidence_depth(fake_run("X", f))
        assert r.capex_evidence.status is CapexSplitStatus.CAPEX_SPLIT_NOT_SUPPORTED

    def test_08_missing_middle_year_stays_visible(self):
        f = self._base("FY2024") + self._base("FY2022")
        r = assess_evidence_depth(fake_run("X", f))
        assert set(r.periods) == {"FY2022", "FY2024"}
        assert r.oldest_period == "FY2022" and r.newest_period == "FY2024"

    def test_09_quarter_mixed_with_annual_is_not_merged(self):
        f = self._base("FY2024") + self._base("Q2 FY2024")
        r = assess_evidence_depth(fake_run("X", f))
        q = next(p for p in r.period_evidence if p.period == "Q2 FY2024")
        assert q.period_type == "QUARTERLY"
        assert q.score is PeriodScore.INSUFFICIENT_EVIDENCE

    def test_10_explicit_one_off_language_is_flagged(self):
        f = self._base("FY2024") + self._base("FY2023")
        f.append(Fact(name="Litigation settlement charge FY2024", value=-40,
                      unit="USD millions", period="FY2024",
                      quote="a one-time litigation settlement",
                      source=FactSource(doc_id="X", kind="statement", ref="cash_flows",
                                        target_key="cash_flows", pages=[1])))
        r = assess_evidence_depth(fake_run("X", f))
        assert any("litigation" in x.lower() for x in r.one_off_evidence.explicit_items)

    def test_11_pattern_only_one_off(self):
        r = assess_evidence_depth(fake_run(
            "X", self._two_periods([], []),
            fcff_by_period={"FY2023": -100.0, "FY2024": 400.0}))
        assert r.one_off_evidence.tier is OneOffTier.PATTERN_ONLY

    def test_12_no_evidence_of_one_off(self):
        r = assess_evidence_depth(fake_run(
            "X", self._two_periods([], []),
            fcff_by_period={"FY2023": 1000.0, "FY2024": 1010.0}))
        assert r.one_off_evidence.tier is OneOffTier.NONE

    def test_13_capex_split_disclosed(self):
        f = self._base("FY2024") + self._base("FY2023")
        f += [cf("Maintenance capital expenditures", -50, "FY2024"),
              cf("Growth capital expenditures", -150, "FY2024"),
              cf("Maintenance capital expenditures", -45, "FY2023"),
              cf("Growth capital expenditures", -120, "FY2023")]
        r = assess_evidence_depth(fake_run("X", f))
        assert r.capex_evidence.status is CapexSplitStatus.CAPEX_SPLIT_SUPPORTED

    def test_14_capex_split_not_disclosed(self):
        f = self._base("FY2024") + self._base("FY2023")
        f += [cf("Purchases of property and equipment", -200, "FY2024"),
              cf("Purchases of property and equipment", -180, "FY2023")]
        r = assess_evidence_depth(fake_run("X", f))
        assert r.capex_evidence.status is CapexSplitStatus.CAPEX_SPLIT_NOT_SUPPORTED

    def test_15_changed_caption_across_years_same_subcategory(self):
        assert (map_reconciliation_caption("Change in accrued expenses").wc_subcategory
                is map_reconciliation_caption("Change in accrued and other liabilities"
                                              ).wc_subcategory)

    def test_16_duplicate_observations_reconciled(self):
        f = self._two_periods(
            [cf("Change in accounts payable", 100, "FY2024"),
             cf("Increase in accounts payable balance", 0, "FY2024")],
            [cf("Change in accounts payable", 100, "FY2024"),
             cf("Increase in accounts payable balance", 0, "FY2024")])
        r = assess_evidence_depth(fake_run("X", f))
        fy = next(p for p in r.period_evidence if p.period == "FY2024")
        assert fy.wc_by_subcategory.get("ACCOUNTS_PAYABLE") == pytest.approx(100.0)

    def test_17_duplicate_observations_conflicting_are_summed_not_chosen(self):
        f = self._two_periods(
            [cf("Change in accounts payable", 100, "FY2024"),
             cf("Change in accounts payable (restated)", -30, "FY2024")],
            [cf("Change in accounts payable", 100, "FY2024"),
             cf("Change in accounts payable (restated)", -30, "FY2024")])
        r = assess_evidence_depth(fake_run("X", f))
        fy = next(p for p in r.period_evidence if p.period == "FY2024")
        assert fy.wc_by_subcategory.get("ACCOUNTS_PAYABLE") == pytest.approx(70.0)

    def test_18_residual_within_tolerance_is_reconciled(self):
        f = self._two_periods([cf("Change in accounts payable", 148, "FY2024")],
                              [cf("Change in accounts payable", 148, "FY2024")])
        # NI 1000 + D&A 200 + AP 148 = 1348 vs CFO 1350 -> residual 2
        r = assess_evidence_depth(fake_run("X", f))
        fy = next(p for p in r.period_evidence if p.period == "FY2024")
        assert fy.reconciliation_status is ReconciliationStatus.RECONCILED

    def test_19_residual_outside_tolerance_is_failed(self):
        f = self._two_periods([cf("Change in accounts payable", 900, "FY2024")],
                              [cf("Change in accounts payable", 900, "FY2024")])
        r = assess_evidence_depth(fake_run("X", f))
        fy = next(p for p in r.period_evidence if p.period == "FY2024")
        assert fy.reconciliation_status is ReconciliationStatus.RECONCILIATION_FAILED
        assert fy.residual == pytest.approx(-750.0)

    def test_20_inferred_historical_component_is_marked(self):
        # a range that is 'derived' but has no observation for FY2022 -> the
        # FY2022 cell is INFERRED, not VERIFIED
        run = pipeline.value_filing("UBER_FY2024", None)
        r = assess_evidence_depth(run)
        # every live UBER period has observations, so no INFERRED here - assert
        # the mechanism exists via a synthetic range instead
        from aleph.schemas.valuation import AssumptionRange, Observation
        rng = AssumptionRange(name="capex", unit="USD millions", status="derived",
                              low=-1, base=-1, high=-1,
                              observations=[Observation(period="FY2024", value=-1,
                                            fact_name="capex", unit="USD millions")],
                              method="latest", rationale="x", doc_ids=["X"])
        f = self._base("FY2024") + self._base("FY2022")
        rep = assess_evidence_depth(fake_run("X", f, ranges={"capex": rng}))
        fy22 = next(p for p in rep.period_evidence if p.period == "FY2022")
        assert "INFERRED" in fy22.components_by_status


# =========================================================================== #
# Phase 23 - the honesty verdict
# =========================================================================== #
class TestHonestyVerdict:
    def test_live_filings_are_disclosure_bound(self):
        for doc in LIVE:
            r = assess_evidence_depth(pipeline.value_filing(doc, None))
            assert r.reduces_uncertainty is UncertaintyVerdict.NO_DISCLOSURE_BOUND
            assert "REGIME_UNCERTAIN" in r.reduces_uncertainty_reason
