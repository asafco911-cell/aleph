"""P10 - model arbitration, assumption governance & valuation reconciliation.

Phases 2-27: the mandatory SBC and tax audits, the sequential reconciliation,
the base-case assumption register (1-5 evidence hierarchy + 2-D
strength x sensitivity), the contradiction engine, per-model applicability
(market-price-independent), arbitration, and the anti-market-fit /
anti-conservatism / anti-complexity gates.
"""
import types

import pytest

import aleph.valuation.pipeline as pipeline
from aleph.valuation.model_governance import (
    Applicability,
    ArbitrationOutcome,
    ContradictionStatus,
    EvidenceBand,
    EvidenceLevel,
    SensitivityBand,
    arbitrate,
    assess_model_governance,
    assumption_register,
    model_applicability,
    reconcile_live_to_p9,
    sbc_audit,
    tax_audit,
)

LIVE = ["UBER_FY2024", "UBER_FY2025", "LYFT_FY2025", "DASH_FY2025"]


def _run(doc, price=None):
    return pipeline.value_filing(doc, price)


# =========================================================================== #
# Phase 3 / 23 - MANDATORY SBC correctness gate
# =========================================================================== #
class TestSBCAudit:
    @pytest.mark.needs_filings
    def test_p9_bridge_does_not_double_count_sbc(self):
        for doc in LIVE:
            a = sbc_audit(_run(doc))
            assert a["double_count"] == "NOT_PRESENT", (doc, a["bridge_line"])
            assert not a["separate_sbc_subtraction_present"]
            assert "RESOLVED" in a["verdict"]

    @pytest.mark.needs_filings
    def test_the_audit_reads_the_actual_bridge_line(self):
        a = sbc_audit(_run("UBER_FY2024"))
        assert a["bridge_line"].startswith("fcff_t =")
        assert "sbc_t" not in a["bridge_line"]
        # a regression that re-introduces '- sbc_t' would flip this to PRESENT
        assert a["accounting_structure"].lower().startswith("sbc is a gaap")

    @pytest.mark.needs_filings
    def test_the_audit_would_catch_a_reintroduced_sbc_subtraction(self, monkeypatch):
        # the clean bridge yields NOT_PRESENT; that alone cannot prove the audit
        # can still SEE a double-count. Feed it a poisoned bridge and confirm it
        # flips to PRESENT / BLOCKED - otherwise Phase 23 is a rubber stamp.
        run = _run("UBER_FY2024")
        import inspect as _inspect
        from aleph.valuation import operating_model as _om
        real_getsource = _inspect.getsource
        poisoned = (
            "    def bridge(rev_prev, rev_t, g_t, margin_t, src_margin, yr):\n"
            "        oi_t = rev_t * margin_t\n"
            "        nopat_t = oi_t * (1 - STATUTORY_TAX_CONVENTION)\n"
            "        sbc_t = rev_t * sbc_ratio\n"
            "        fcff_t = nopat_t + dna_t + wc_t - capex_t - sbc_t\n"
        )

        def fake_getsource(obj):
            return poisoned if obj is _om else real_getsource(obj)

        monkeypatch.setattr(_inspect, "getsource", fake_getsource)
        a = sbc_audit(run)
        assert a["separate_sbc_subtraction_present"] is True
        assert a["double_count"] == "PRESENT"
        assert "BLOCKED" in a["verdict"]


# =========================================================================== #
# Phase 4 / 24 - tax convention audit (statutory != cash != effective)
# =========================================================================== #
class TestTaxAudit:
    @pytest.mark.needs_filings
    def test_uber_and_lyft_are_conservative_but_supported(self):
        for doc in ("UBER_FY2024", "LYFT_FY2025"):
            t = tax_audit(_run(doc))
            assert t["classification"] == "CONSERVATIVE_BUT_SUPPORTED"
            assert t["labels"]["statutory"] == 0.21
            assert "cash_tax" in t["labels"] and "effective_disclosed" in t["labels"]
            assert "not the expected cash rate" in t["verdict"].lower() \
                or "not read it" in t["verdict"].lower()

    @pytest.mark.needs_filings
    def test_the_three_rates_are_never_conflated(self):
        t = tax_audit(_run("UBER_FY2024"))
        # statutory, cash, effective are three separate labelled things
        assert set(t["labels"]) >= {"statutory", "cash_tax", "effective_disclosed"}
        assert t["labels"]["cash_tax"] != t["labels"]["statutory"]


# =========================================================================== #
# Phase 0 / 1 - reconciliation LIVE -> P9 (order-dependent, residual retained)
# =========================================================================== #
class TestReconciliation:
    @pytest.mark.needs_filings
    def test_first_step_is_the_live_anchor_and_it_is_unchanged(self):
        run = _run("UBER_FY2024")
        steps, meta = reconcile_live_to_p9(run)
        assert steps[0].order == 0
        assert steps[0].fcff_after == pytest.approx(run.bridged.inputs.base_cash_flow)
        assert steps[0].value_after == pytest.approx(run.result.value_per_share, abs=0.01)
        assert meta["order_dependent"] is True

    @pytest.mark.needs_filings
    def test_the_bridge_reaches_the_p9_base_value_with_a_stated_residual(self):
        run = _run("UBER_FY2024")
        steps, meta = reconcile_live_to_p9(run)
        g = assess_model_governance(run)
        assert steps[-1].name.startswith("= P9 BASE")
        assert "residual" in steps[-1].change
        # the last step lands on the P9 BASE valuation (scenario = BASE, not
        # BULL; no double-counted WC / capex)
        assert steps[-1].value_after == pytest.approx(g.p9_base, abs=1.0)
        # interaction / order-dependence is disclosed, not hidden
        assert "interact" in " ".join(s.note for s in steps).lower()
        assert "ORDER-DEPENDENT" in " ".join(s.note for s in steps)

    @pytest.mark.needs_filings
    def test_step_one_operating_basis_is_nopat_plus_dna_minus_capex_once(self):
        # pins the arithmetic of step 1: NOPAT + D&A - capex, each term counted
        # exactly once. A bridge that subtracts capex (or D&A) twice would still
        # pass the "reaches P9 BASE" test because step 3 re-derives from
        # f.base_fcff directly - this catches it at the step it happens.
        from aleph.valuation.operating_model import (
            Scenario, build_operating_forecast, historical_drivers,
            STATUTORY_TAX_CONVENTION as TAX,
        )
        run = _run("UBER_FY2024")
        steps, _ = reconcile_live_to_p9(run)
        f = build_operating_forecast(run, Scenario.BASE)
        hd = {d.name: d for d in historical_drivers(run)}
        rev = hd["revenue"].latest
        y0 = f.years[0]
        nopat = rev * y0.operating_margin * (1 - TAX)
        dna = y0.dna / y0.revenue * rev
        capex = y0.capex / y0.revenue * rev
        s1 = next(s for s in steps if s.order == 1)
        assert s1.fcff_after == pytest.approx(nopat + dna - capex, rel=1e-6)

    @pytest.mark.needs_filings
    def test_step_two_adds_exactly_one_median_working_capital_contribution(self):
        # the stated change is "+ historical-median working capital". Verify the
        # delta equals ONE median contribution, recomputed independently from the
        # historical driver - a bridge that adds it twice is caught here.
        from aleph.valuation.operating_model import historical_drivers
        run = _run("UBER_FY2024")
        steps, _ = reconcile_live_to_p9(run)
        hd = {d.name: d for d in historical_drivers(run)}
        rev = hd["revenue"].latest
        expected_wc = hd["wc_cash_effect_over_revenue"].median * rev
        s1 = next(s for s in steps if s.order == 1)
        s2 = next(s for s in steps if s.order == 2)
        assert (s2.fcff_after - s1.fcff_after) == pytest.approx(expected_wc, rel=1e-6)
        assert s2.fcff_after == pytest.approx(s1.fcff_after + expected_wc, rel=1e-6)

    @pytest.mark.needs_filings
    def test_lyft_operating_basis_without_wc_is_non_positive(self):
        # LYFT: strip the WC tailwind and normalise tax -> the operating basis
        # FCFF is negative; the reconciliation shows it rather than clamping
        steps, _ = reconcile_live_to_p9(_run("LYFT_FY2025"))
        step1 = next(s for s in steps if s.order == 1)
        assert step1.fcff_after is not None and step1.fcff_after < 0

    @pytest.mark.needs_filings
    def test_dash_reconciliation_stops_at_the_live_anchor(self):
        steps, meta = reconcile_live_to_p9(_run("DASH_FY2025"))
        assert len(steps) == 1 and steps[0].order == 0
        assert "INSUFFICIENT_EVIDENCE" in meta["status"]


# =========================================================================== #
# Phase 9-12 - assumption register + evidence hierarchy + 2-D + contradiction
# =========================================================================== #
class TestAssumptionRegister:
    @pytest.mark.needs_filings
    def test_every_entry_has_evidence_level_bands_and_contradiction(self):
        reg = assumption_register(_run("UBER_FY2024"))
        assert reg
        for e in reg:
            assert isinstance(e.evidence_level, EvidenceLevel)
            assert isinstance(e.evidence_band, EvidenceBand)
            assert isinstance(e.sensitivity_band, SensitivityBand)
            assert isinstance(e.contradiction, ContradictionStatus)
            assert e.historical_evidence and e.economic_rationale

    @pytest.mark.needs_filings
    def test_evidence_and_sensitivity_are_two_dimensions_not_a_score(self):
        reg = assumption_register(_run("UBER_FY2024"))
        e = reg[0]
        # there is no single numeric quality/score field
        assert not hasattr(e, "quality_score")
        assert not hasattr(e, "score")
        # the two axes are independent enums
        assert e.evidence_band.value in ("STRONG", "MODERATE", "WEAK")
        assert e.sensitivity_band.value in ("HIGH", "MEDIUM", "LOW")

    @pytest.mark.needs_filings
    def test_tax_rate_is_level_5_model_convention(self):
        reg = assumption_register(_run("UBER_FY2024"))
        tax = next(e for e in reg if e.variable == "tax_rate")
        assert tax.evidence_level is EvidenceLevel.L5_MODEL_CONVENTION
        assert tax.model_convention is True
        assert tax.evidence_band is EvidenceBand.WEAK

    @pytest.mark.needs_filings
    def test_evidence_levels_are_calibrated_per_driver(self):
        reg = {e.variable: e for e in assumption_register(_run("UBER_FY2024"))}
        # INFLECTING margin held at the latest -> a genuine L4 judgement
        assert reg["operating_margin"].evidence_level is \
            EvidenceLevel.L4_PLAUSIBLE_ANALYST_ASSUMPTION
        assert reg["operating_margin"].evidence_band is EvidenceBand.WEAK
        # year-1 growth = median of a STABLE series -> L3, MODERATE band
        assert reg["revenue_growth"].evidence_level is \
            EvidenceLevel.L3_REPEATED_HISTORICAL_PATTERN
        assert reg["revenue_growth"].evidence_band is EvidenceBand.MODERATE

    @pytest.mark.needs_filings
    def test_uber_working_capital_assumption_is_contradicted_by_evidence(self):
        reg = assumption_register(_run("UBER_FY2024"))
        wc = next(e for e in reg if e.variable == "wc_cash_effect_over_revenue")
        assert wc.contradiction is ContradictionStatus.ASSUMPTION_CONTRADICTED_BY_EVIDENCE
        assert "median" in wc.contradiction_detail.lower()

    @pytest.mark.needs_filings
    def test_capex_and_dna_ratios_are_independently_supported(self):
        reg = assumption_register(_run("UBER_FY2024"))
        for name in ("capex_over_revenue", "dna_over_revenue"):
            e = next(x for x in reg if x.variable == name)
            assert e.independently_supported is True
            assert e.evidence_level in (EvidenceLevel.L2_DERIVED_FROM_FACTS,
                                        EvidenceLevel.L3_REPEATED_HISTORICAL_PATTERN)

    @pytest.mark.needs_filings
    def test_the_dominant_assumption_is_high_sensitivity_and_weak_evidence(self):
        g = assess_model_governance(_run("UBER_FY2024"))
        assert any("fragile" in d for d in g.dominant_assumptions)
        assert any("wc_cash_effect" in d for d in g.dominant_assumptions)

    @pytest.mark.needs_filings
    def test_dominant_assumptions_are_ranked_most_value_sensitive_first(self):
        # Phase 13 - the ranking IS the output. Every base-case variable appears
        # once, ordered by |d(value/share)| descending. An inverted sort would
        # surface the least decisive assumption as the "dominant" one.
        run = _run("UBER_FY2024")
        reg = {e.variable: e for e in assumption_register(run)}
        g = assess_model_governance(run)
        names = [d.split(":", 1)[0] for d in g.dominant_assumptions]
        assert set(names) == set(reg)
        assert len(names) == len(reg)          # no duplicates
        sens = [reg[n].value_sensitivity or 0.0 for n in names]
        assert sens == sorted(sens, reverse=True)
        assert len(sens) >= 3 and sens[0] > sens[-1]


# =========================================================================== #
# Phase 20 - ANTI-MARKET-FIT: applicability does NOT depend on the price
# =========================================================================== #
class TestAntiMarketFit:
    @pytest.mark.needs_filings
    @pytest.mark.parametrize("price", [None, 1.0, 5.0, 47.03, 77.08, 250.0, 5000.0])
    def test_applicability_classification_is_identical_for_every_market_price(self, price):
        run = _run("UBER_FY2024", price)
        reports = model_applicability(run)
        got = {r.model.split()[0]: r.applicability for r in reports}
        assert got["LIVE"] is Applicability.LIMITED_APPLICABILITY
        assert got["P6"] is Applicability.CONDITIONAL_APPLICABILITY
        assert got["P9"] is Applicability.LIMITED_APPLICABILITY

    @pytest.mark.needs_filings
    def test_arbitration_outcome_is_identical_for_every_market_price(self):
        outs = set()
        for price in (None, 5.0, 47.03, 77.08, 5000.0):
            run = _run("UBER_FY2024", price)
            g = assess_model_governance(run)
            outs.add(g.arbitration)
        assert len(outs) == 1


# =========================================================================== #
# Phase 21 - ANTI-CONSERVATISM: the lower valuation is not auto-preferred
# =========================================================================== #
class TestAntiConservatism:
    @pytest.mark.needs_filings
    def test_p9_is_not_more_applicable_just_because_it_values_lower(self):
        run = _run("UBER_FY2024")
        reports = {r.model.split()[0]: r for r in model_applicability(run)}
        # P9 base ($47) < LIVE ($77) - yet P9 is NOT ranked HIGH; it is LIMITED
        assert reports["P9"].applicability is Applicability.LIMITED_APPLICABILITY
        assert reports["P9"].applicability is not Applicability.HIGH_APPLICABILITY

    @pytest.mark.needs_filings
    def test_arbitration_does_not_name_a_winner(self):
        g = assess_model_governance(_run("UBER_FY2024"))
        assert g.arbitration in (
            ArbitrationOutcome.MODEL_CONVERGENCE,
            ArbitrationOutcome.MODEL_DIVERGENCE_WITH_EVIDENCE_BASIS,
            ArbitrationOutcome.MODEL_DIVERGENCE_UNRESOLVED)
        blob = (g.headline + " ".join(g.arbitration_reasons)).lower()
        for banned in ("winner", "correct model", "use p9", "use the live",
                       "recommend", "buy", "sell"):
            assert banned not in blob


# =========================================================================== #
# Phase 22 - ANTI-COMPLEXITY: detail alone does not raise applicability
# =========================================================================== #
class TestAntiComplexity:
    @pytest.mark.needs_filings
    def test_p9_more_detailed_but_not_more_applicable_than_live(self):
        run = _run("UBER_FY2024")
        reports = {r.model.split()[0]: r for r in model_applicability(run)}
        order = {Applicability.HIGH_APPLICABILITY: 3,
                 Applicability.CONDITIONAL_APPLICABILITY: 2,
                 Applicability.LIMITED_APPLICABILITY: 1,
                 Applicability.NOT_SUPPORTED: 0}
        # the driver model is more complex, but its dominant assumption is a
        # weak L4 judgement, so it does NOT outrank LIVE on applicability
        assert order[reports["P9"].applicability] <= order[reports["LIVE"].applicability]


# =========================================================================== #
# Phase 14 - arbitration on the live filings
# =========================================================================== #
class TestArbitration:
    @pytest.mark.needs_filings
    def test_uber_and_lyft_diverge_with_an_evidence_basis(self):
        for doc in ("UBER_FY2024", "LYFT_FY2025"):
            g = assess_model_governance(_run(doc))
            assert g.arbitration is ArbitrationOutcome.MODEL_DIVERGENCE_WITH_EVIDENCE_BASIS
            joined = " ".join(g.arbitration_reasons).lower()
            # the divergence is attributed to identified assumptions
            assert "converge" in joined and "sbc double-count" in joined
            assert "latest fcff" in joined or "working-capital" in joined

    @pytest.mark.needs_filings
    def test_p9_and_p6_converge_after_the_sbc_correction(self):
        g = assess_model_governance(_run("UBER_FY2024"))
        assert isinstance(g.p9_base, float) and g.p6_central is not None
        assert abs(g.p9_base - g.p6_central) / g.p6_central < 0.10

    @pytest.mark.needs_filings
    def test_dash_is_unresolved_only_one_model_produces_a_value(self):
        g = assess_model_governance(_run("DASH_FY2025"))
        assert g.arbitration is ArbitrationOutcome.MODEL_DIVERGENCE_UNRESOLVED


# =========================================================================== #
# P10.5.1 - targeted governance fix: the UBER_FY2025 LIVE<->P9 divergence is
# attributed to the 21% tax convention, WITHOUT validating 21% as the forward
# cash-tax rate (that stays DISCLOSURE_BOUND, P10.5).
# =========================================================================== #
class TestP1051TaxAttribution:
    @pytest.mark.needs_filings
    def test_uber_fy2025_divergence_is_no_longer_unresolved(self):
        g = assess_model_governance(_run("UBER_FY2025"))
        assert g.arbitration is ArbitrationOutcome.MODEL_DIVERGENCE_WITH_EVIDENCE_BASIS
        joined = " ".join(g.arbitration_reasons)
        assert "21% statutory convention" in joined
        assert "DIVERGENCE ATTRIBUTION = RESOLVED" in joined

    @pytest.mark.needs_filings
    def test_the_attribution_does_not_validate_the_forward_tax_rate(self):
        g = assess_model_governance(_run("UBER_FY2025"))
        joined = " ".join(g.arbitration_reasons)
        # the reason must say, in so many words, that 21% is NOT established as
        # the forward rate and that the question stays disclosure-bound
        assert "does NOT establish 21% as the normalised forward cash-tax rate" in joined
        assert "DISCLOSURE_BOUND" in joined
        # tax_audit must NOT have been silently upgraded
        t = tax_audit(_run("UBER_FY2025"))
        assert t["classification"] == "CONSERVATIVE_BUT_SUPPORTED"
        blob = joined.lower()
        for banned in ("verified", "validated", "confirmed", "normalized_cash_tax",
                       "winner", "correct model", "recommend", "buy", "sell"):
            assert banned not in blob

    @pytest.mark.needs_filings
    def test_the_branch_is_evidence_keyed_not_p9_below_live(self):
        # LYFT_FY2025 also has P9 < LIVE, but the P10.5 bridge is NOT fully
        # tax-explained there (WC is the dominant delta), so the tax-attribution
        # reason must NOT appear - the branch is keyed to the reconciliation.
        g = assess_model_governance(_run("LYFT_FY2025"))
        joined = " ".join(g.arbitration_reasons)
        assert "21% statutory convention" not in joined
        assert "DIVERGENCE ATTRIBUTION = RESOLVED" not in joined

    @pytest.mark.needs_filings
    @pytest.mark.parametrize("price", [None, 1.0, 17.35, 119.95, 250.0, 5000.0])
    def test_the_tax_attribution_is_price_independent(self, price):
        g = assess_model_governance(_run("UBER_FY2025", price))
        assert g.arbitration is ArbitrationOutcome.MODEL_DIVERGENCE_WITH_EVIDENCE_BASIS
        assert any("21% statutory convention" in r for r in g.arbitration_reasons)

    @pytest.mark.needs_filings
    def test_uber_fy2024_and_dash_arbitration_are_unchanged_by_p1051(self):
        assert assess_model_governance(_run("UBER_FY2024")).arbitration is \
            ArbitrationOutcome.MODEL_DIVERGENCE_WITH_EVIDENCE_BASIS
        assert assess_model_governance(_run("DASH_FY2025")).arbitration is \
            ArbitrationOutcome.MODEL_DIVERGENCE_UNRESOLVED
        # and the tax-attribution reason does NOT leak into UBER_FY2024
        j = " ".join(assess_model_governance(_run("UBER_FY2024")).arbitration_reasons)
        assert "DIVERGENCE ATTRIBUTION = RESOLVED" not in j

    @pytest.mark.needs_filings
    def test_a_merely_partial_tax_bridge_does_not_yield_attribution_resolved(
            self, monkeypatch):
        # the branch requires a FULLY-explained bridge; a PARTIAL one (material
        # methodology residual) must NOT be reported as "ATTRIBUTION = RESOLVED",
        # even when its dominant cause is tax.
        from aleph.valuation import evidence_resolution as _er
        fake = _er.SequentialBridge(
            doc_id="X", live_fcff=100.0, p9_base_fcff=80.0, steps=(),
            residual=0.0, residual_kind="", arithmetically_reconciled=True,
            economically_explained=_er.EconomicallyExplained.PARTIAL,
            dominant_cause="tax normalization (21% statutory)",
            methodology_pct_of_fcff=0.18, note="")
        monkeypatch.setattr(_er, "sequential_bridge_live_to_p9", lambda run: fake)
        run = _run("UBER_FY2025")
        _, reasons = arbitrate(run, assumption_register(run),
                               model_applicability(run))
        assert "DIVERGENCE ATTRIBUTION = RESOLVED" not in " ".join(reasons)


# =========================================================================== #
# Phase 27 - regression: the LIVE DCF is byte-identical with P10 present
# =========================================================================== #
class TestRegression:
    @pytest.mark.needs_filings
    def test_point_values_unchanged(self):
        for doc, want in (("UBER_FY2024", 77.08), ("UBER_FY2025", 119.95),
                          ("LYFT_FY2025", 49.06), ("DASH_FY2025", 124.27)):
            run = _run(doc)
            assess_model_governance(run)
            assert run.result.value_per_share == pytest.approx(want, abs=0.01), doc

    @pytest.mark.needs_filings
    def test_governance_does_not_mutate_the_run(self):
        run = _run("UBER_FY2024")
        i = run.bridged.inputs
        before = (run.result.value_per_share, i.base_cash_flow, list(i.growth_rates),
                  i.discount_rate, i.terminal_growth, i.net_debt, i.shares_outstanding)
        assess_model_governance(run)
        assess_model_governance(run)
        after = (run.result.value_per_share, i.base_cash_flow, list(i.growth_rates),
                 i.discount_rate, i.terminal_growth, i.net_debt, i.shares_outstanding)
        assert before == after

    def test_pipeline_has_no_model_governance_import(self):
        import inspect
        assert "model_governance" not in inspect.getsource(pipeline)


# =========================================================================== #
# Phase 26 - cross-sector: governance runs deterministically on synthetics
# =========================================================================== #
class TestCrossSector:
    @pytest.mark.parametrize("name", ["saas", "marketplace", "mature_cash_gen"])
    def test_synthetic_sectors_run_deterministically(self, name):
        from test_operating_model import synth_run
        SECT = {
            "saas": ([500, 700, 950], [0.20] * 3, [0.01] * 3, [0.02] * 3, [0.08] * 3, [0.03] * 3),
            "marketplace": ([1000, 1250, 1500], [0.04] * 3, [0.06] * 3, [0.01] * 3,
                            [0.05] * 3, [0.02] * 3),
            "mature_cash_gen": ([3000, 3060, 3120], [0.22] * 3, [-0.01] * 3, [0.03] * 3,
                                [0.02] * 3, [0.04] * 3),
        }
        run = synth_run(*SECT[name], doc_id=name)
        # governance needs run.result / run.wacc-ish; synth has bridged.inputs
        run.result = types.SimpleNamespace(
            value_per_share=50.0, enterprise_or_equity_value=1.0, equity_value=1.0)
        run.robustness = None
        g1 = assess_model_governance(run)
        g2 = assess_model_governance(run)
        assert g1.arbitration is g2.arbitration
        assert [e.variable for e in g1.register] == [e.variable for e in g2.register]
        assert g1.sbc_audit["double_count"] == "NOT_PRESENT"
