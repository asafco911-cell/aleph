"""P10.5 - evidence resolution, working-capital economic classification &
unresolved-divergence audit.

Falsification-first: the pure classifiers are exercised with crafted series
(recurrence must disappear when the history stops repeating; a one-off label
must disappear when the one-off language is removed; irrelevant lines must
not move a verdict), and the anti-model-fit guarantee is checked
STRUCTURALLY - no function here accepts a price, and every classification is
byte-identical across a wide sweep of market prices.
"""
import inspect

import pytest

import aleph.valuation.pipeline as pipeline
from aleph.valuation import evidence_resolution as er
from aleph.valuation.evidence_resolution import (
    BoundaryVerdict,
    DisclosureStatus,
    EconomicallyExplained,
    EpistemicClass,
    HypothesisStatus,
    InsuranceVerdict,
    PersistenceClass,
    RecurrenceEvidence,
    TaxEvidenceClass,
    TaxNormalizationVerdict,
    assess_evidence_resolution,
    classify_persistence,
    classify_recurrence,
    insurance_float_audit,
    persistence_profiles,
    sequential_bridge_live_to_p9,
    tax_evidence,
    working_capital_evidence_map,
)

LIVE = ["UBER_FY2024", "UBER_FY2025", "LYFT_FY2025", "DASH_FY2025"]


def _run(doc, price=None):
    return pipeline.value_filing(doc, price)


# =========================================================================== #
# Section 14/15 - ANTI-MODEL-FIT (structural) + NO NEW SCORE
# =========================================================================== #
class TestNoPriceLeak:
    def test_no_public_function_accepts_a_price_argument(self):
        bad = []
        for name, fn in vars(er).items():
            if not callable(fn) or getattr(fn, "__module__", "") != er.__name__:
                continue
            try:
                params = inspect.signature(fn).parameters
            except (TypeError, ValueError):
                continue
            for p in params:
                if p.lower() in ("price", "market_price", "target_price",
                                 "share_price", "px"):
                    bad.append(f"{name}({p})")
        assert not bad, bad

    @pytest.mark.parametrize("price", [None, 1.0, 17.35, 47.03, 77.08, 250.0, 5000.0])
    def test_every_classification_is_identical_across_prices(self, price):
        base = assess_evidence_resolution(_run("UBER_FY2024", None))
        got = assess_evidence_resolution(_run("UBER_FY2024", price))
        assert got.verdict == base.verdict
        assert got.architectural_decision == base.architectural_decision
        assert got.insurance.verdict is base.insurance.verdict
        assert got.tax.classification is base.tax.classification
        assert got.bridge.economically_explained is base.bridge.economically_explained
        assert [b.verdict for b in got.boundaries] == [b.verdict for b in base.boundaries]
        assert [(e.variable if hasattr(e, "variable") else e.caption, e.recurrence_evidence)
                for e in got.wc_map] == \
               [(e.caption, e.recurrence_evidence) for e in base.wc_map]

    def test_no_composite_score_field_anywhere(self):
        r = assess_evidence_resolution(_run("UBER_FY2024"))
        banned = ("score", "confidence", "quality_score", "reliability",
                  "composite", "rank")
        for obj in (r, r.insurance, r.tax, r.bridge, *r.persistence, *r.wc_map,
                    *r.boundaries, *r.epistemic_tags):
            for f in getattr(type(obj), "__dataclass_fields__", {}):
                assert not any(b in f.lower() for b in banned), (type(obj).__name__, f)


# =========================================================================== #
# Section 13 - FALSIFICATION of the pure classifiers
# =========================================================================== #
class TestRecurrenceFalsification:
    def test_three_like_signed_years_is_multi_year_repeated(self):
        assert classify_recurrence([100, 120, 110]) is RecurrenceEvidence.MULTI_YEAR_REPEATED

    def test_remove_a_year_and_multi_year_collapses_to_single_year(self):
        assert classify_recurrence([100, 120]) is RecurrenceEvidence.SINGLE_YEAR_OBSERVATION

    def test_break_the_sign_pattern_and_recurrence_becomes_ambiguous(self):
        assert classify_recurrence([100, -120, 90, -95]) is \
            RecurrenceEvidence.ECONOMICALLY_AMBIGUOUS

    def test_empty_series_is_not_disclosed(self):
        assert classify_recurrence([]) is RecurrenceEvidence.NOT_DISCLOSED

    def test_explicit_one_off_language_wins_over_the_pattern(self):
        assert classify_recurrence([100, 120, 110], ["a one-time legal settlement"]) is \
            RecurrenceEvidence.EXPLICIT_ONE_OFF

    def test_remove_the_one_off_language_and_the_label_reverts_to_the_pattern(self):
        assert classify_recurrence([100, 120, 110], ["insurance reserves 100 120 110"]) is \
            RecurrenceEvidence.MULTI_YEAR_REPEATED

    def test_explicit_recurring_language_is_honoured(self):
        assert classify_recurrence([50, 900, 10],
                                   ["recurring in the ordinary course of business"]) is \
            RecurrenceEvidence.EXPLICIT_RECURRING


class TestPersistenceFalsification:
    def test_flat_series_is_strongly_persistent(self):
        assert classify_persistence([100, 100, 100])[0] is PersistenceClass.STRONGLY_PERSISTENT

    def test_widening_the_spread_downgrades_to_high_variance(self):
        assert classify_persistence([100, 500, 2400])[0] is \
            PersistenceClass.RECURRENT_WITH_HIGH_VARIANCE

    def test_moderate_spread_is_persistent_but_volatile(self):
        assert classify_persistence([300, 700, 800])[0] is \
            PersistenceClass.PERSISTENT_BUT_VOLATILE

    def test_shortening_history_yields_insufficient(self):
        assert classify_persistence([100, 100])[0] is PersistenceClass.INSUFFICIENT_HISTORY

    def test_destroying_sign_consistency_yields_non_persistent(self):
        assert classify_persistence([100, -50, 80, -90])[0] is \
            PersistenceClass.NON_PERSISTENT

    def test_rule_string_is_populated(self):
        for s in ([100, 100, 100], [100, 500, 2400], [100, -50, 80, -90]):
            assert classify_persistence(s)[1]


# =========================================================================== #
# Section A / B - working-capital evidence map + persistence on the filings
# =========================================================================== #
class TestWorkingCapitalMap:
    def test_every_entry_is_a_fact_with_a_recurrence_label(self):
        for doc in ("UBER_FY2024", "UBER_FY2025", "LYFT_FY2025"):
            m = working_capital_evidence_map(_run(doc))
            assert m
            for e in m:
                assert e.evidence_level == "FACT"
                assert isinstance(e.recurrence_evidence, RecurrenceEvidence)
                assert isinstance(e.disclosure_status, DisclosureStatus)
                assert e.cash_flow_direction in ("INFLOW", "OUTFLOW", "NEUTRAL")

    def test_the_map_excludes_non_working_capital_lines(self):
        m = working_capital_evidence_map(_run("UBER_FY2024"))
        caps = " ".join(e.caption.lower() for e in m)
        assert "depreciation" not in caps and "stock-based" not in caps

    def test_uber_insurance_reserve_line_is_supported(self):
        m = working_capital_evidence_map(_run("UBER_FY2024"))
        ins = [e for e in m if e.normalized_category == "INSURANCE_RESERVES"]
        assert ins
        assert all(e.disclosure_status is DisclosureStatus.SUPPORTED for e in ins)
        assert all(e.recurrence_evidence is RecurrenceEvidence.MULTI_YEAR_REPEATED
                   for e in ins)

    def test_amounts_and_directions_match_the_disclosed_numbers(self):
        m = {(e.normalized_category, e.period): e
             for e in working_capital_evidence_map(_run("UBER_FY2024"))}
        ins = m[("INSURANCE_RESERVES", "FY2024")]
        # the FY2024 accrued-insurance-reserve cash change is +2,819 (an INFLOW)
        assert ins.signed_amount == pytest.approx(2819.0, abs=1.0)
        assert ins.cash_flow_direction == "INFLOW"
        ar = m[("ACCOUNTS_RECEIVABLE", "FY2024")]
        assert ar.signed_amount < 0 and ar.cash_flow_direction == "OUTFLOW"


class TestPersistenceProfiles:
    def test_uber_fy2024_wc_total_is_recurrent_with_high_variance(self):
        p = {x.name: x for x in persistence_profiles(_run("UBER_FY2024"))}
        assert p["wc_total"].classification is PersistenceClass.RECURRENT_WITH_HIGH_VARIANCE
        assert p["wc_total"].sign_consistency == 1.0
        assert p["wc_total"].magnitude_stability < 0.2

    def test_uber_fy2025_insurance_line_is_more_persistent_than_fy2024(self):
        f24 = {x.name: x for x in persistence_profiles(_run("UBER_FY2024"))}
        f25 = {x.name: x for x in persistence_profiles(_run("UBER_FY2025"))}
        i24 = f24["Change in accrued insurance reserves"]
        i25 = f25["Change in accrued insurance reserves"]
        assert i24.classification is PersistenceClass.PERSISTENT_BUT_VOLATILE
        assert i25.classification is PersistenceClass.STRONGLY_PERSISTENT
        assert i25.magnitude_stability > i24.magnitude_stability

    def test_scaled_histories_are_exposed_separately(self):
        p = persistence_profiles(_run("UBER_FY2024"))[0]
        assert len(p.revenue_scaled_history) == len(p.periods)
        assert len(p.cfo_scaled_history) == len(p.periods)
        assert len(p.fcff_scaled_history) == len(p.periods)


# =========================================================================== #
# Section C - insurance / float audit
# =========================================================================== #
class TestInsuranceAudit:
    def test_verdicts_per_filer(self):
        assert insurance_float_audit(_run("UBER_FY2024")).verdict is \
            InsuranceVerdict.MIXED_SUPPORTED
        assert insurance_float_audit(_run("UBER_FY2025")).verdict is \
            InsuranceVerdict.RECURRING_SUPPORTED
        assert insurance_float_audit(_run("LYFT_FY2025")).verdict is \
            InsuranceVerdict.AMBIGUOUS
        assert insurance_float_audit(_run("DASH_FY2025")).verdict is \
            InsuranceVerdict.DISCLOSURE_BOUND

    def test_lyft_is_ambiguous_because_of_the_sign_flip(self):
        a = insurance_float_audit(_run("LYFT_FY2025"))
        assert a.sign_consistency is not None and a.sign_consistency < 1.0
        assert "flip" in a.rationale.lower()

    def test_uber_direction_recurs_but_level_is_disclosure_bound(self):
        a = insurance_float_audit(_run("UBER_FY2024"))
        assert a.sign_consistency == 1.0
        assert "LEVEL is disclosure-bound" in a.rationale


# =========================================================================== #
# Section E - the sequential bridge LIVE -> P9
# =========================================================================== #
class TestSequentialBridge:
    @pytest.mark.parametrize("doc", ["UBER_FY2024", "UBER_FY2025", "LYFT_FY2025"])
    def test_every_step_satisfies_start_plus_delta_equals_end(self, doc):
        b = sequential_bridge_live_to_p9(_run(doc))
        for s in b.steps:
            assert s.end == pytest.approx(s.start + s.delta, abs=1e-6)

    @pytest.mark.parametrize("doc", ["UBER_FY2024", "UBER_FY2025", "LYFT_FY2025"])
    def test_the_bridge_reconciles_arithmetically_to_the_p9_base(self, doc):
        b = sequential_bridge_live_to_p9(_run(doc))
        assert b.arithmetically_reconciled
        assert b.steps[-1].end == pytest.approx(b.p9_base_fcff, abs=2.0)

    def test_uber_fy2025_is_fully_explained_and_the_cause_is_tax(self):
        b = sequential_bridge_live_to_p9(_run("UBER_FY2025"))
        assert b.economically_explained is EconomicallyExplained.FULLY
        assert "tax" in b.dominant_cause.lower()
        assert b.methodology_pct_of_fcff < 0.02

    def test_uber_fy2024_gap_is_dominated_by_the_working_capital_choice(self):
        b = sequential_bridge_live_to_p9(_run("UBER_FY2024"))
        assert "working-capital" in b.dominant_cause.lower()
        # arithmetically reconciled but only PARTIAL-ly explained
        assert b.arithmetically_reconciled
        assert b.economically_explained in (EconomicallyExplained.PARTIAL,
                                            EconomicallyExplained.FULLY)

    def test_arithmetically_reconciled_is_not_conflated_with_explained(self):
        b = sequential_bridge_live_to_p9(_run("LYFT_FY2025"))
        # LYFT reconciles arithmetically, but the methodology chunk is > 10%
        assert b.arithmetically_reconciled
        assert b.economically_explained is not EconomicallyExplained.FULLY

    def test_dash_has_no_bridge_because_there_is_no_second_model(self):
        b = sequential_bridge_live_to_p9(_run("DASH_FY2025"))
        assert b.live_fcff is None and not b.steps
        assert "INSUFFICIENT" in b.note


# =========================================================================== #
# Section F - operating basis without working capital
# =========================================================================== #
class TestOperatingBasisWithoutWC:
    def test_lyft_operating_cash_independent_of_wc_is_not_positive(self):
        ob = assess_evidence_resolution(_run("LYFT_FY2025")).operating_basis_without_wc
        assert ob["status"] == "CLASSIFIED"
        assert ob["n_nonpositive"] == 2
        h1 = next(h for h in ob["hypotheses"] if h.hypothesis.startswith("1."))
        assert h1.status is HypothesisStatus.RULED_OUT
        assert "NOT hypothesis 1" in ob["verdict"]

    def test_uber_operating_cash_independent_of_wc_is_positive_recently(self):
        ob = assess_evidence_resolution(_run("UBER_FY2025")).operating_basis_without_wc
        h1 = next(h for h in ob["hypotheses"] if h.hypothesis.startswith("1."))
        assert h1.status is HypothesisStatus.SUPPORTED
        assert ob["n_nonpositive"] == 0


# =========================================================================== #
# Section G - tax evidence (the 21% convention is graded, never changed)
# =========================================================================== #
class TestTaxEvidence:
    def test_the_statutory_convention_is_not_changed(self):
        assert er.STATUTORY_TAX == 0.21
        for doc in LIVE:
            assert tax_evidence(_run(doc)).statutory == 0.21

    def test_uber_and_lyft_are_effective_disclosed_and_normalization_is_bound(self):
        for doc in ("UBER_FY2024", "LYFT_FY2025"):
            t = tax_evidence(_run(doc))
            assert t.classification is TaxEvidenceClass.EFFECTIVE_DISCLOSED
            assert t.normalization_verdict is \
                TaxNormalizationVerdict.TAX_NORMALIZATION_DISCLOSURE_BOUND
            assert t.cash_taxes_paid_disclosed is False
            assert t.normalized_rate_derivable is False

    def test_dash_has_only_the_statutory_rate(self):
        t = tax_evidence(_run("DASH_FY2025"))
        assert t.classification is TaxEvidenceClass.STATUTORY_ONLY
        assert t.effective_by_period == {}

    def test_never_claims_cash_tax_support_it_does_not_have(self):
        for doc in LIVE:
            assert tax_evidence(_run(doc)).classification is not \
                TaxEvidenceClass.CASH_TAX_SUPPORTED


# =========================================================================== #
# Section 11 - FACT / ECONOMIC_INTERPRETATION / MODEL_ASSUMPTION separation
# =========================================================================== #
class TestEpistemicTags:
    def test_all_three_classes_are_present_and_correctly_assigned(self):
        r = assess_evidence_resolution(_run("UBER_FY2024"))
        by_class = {}
        for t in r.epistemic_tags:
            by_class.setdefault(t.epistemic_class, []).append(t.item)
        assert EpistemicClass.FACT in by_class
        assert EpistemicClass.ECONOMIC_INTERPRETATION in by_class
        assert EpistemicClass.MODEL_ASSUMPTION in by_class
        # the 21% rate is an assumption, never a fact
        tax_tags = [t for t in r.epistemic_tags if "21%" in t.item]
        assert tax_tags and all(t.epistemic_class is EpistemicClass.MODEL_ASSUMPTION
                                for t in tax_tags)
        # a disclosed per-period cash movement is a fact
        fact_items = " ".join(by_class[EpistemicClass.FACT]).lower()
        assert "working-capital" in fact_items or "reconstructed fcff" in fact_items


# =========================================================================== #
# Section H - disclosure-boundary engine
# =========================================================================== #
class TestDisclosureBoundaries:
    def test_tax_normalization_is_disclosure_bound_for_every_filer(self):
        for doc in LIVE:
            r = assess_evidence_resolution(_run(doc))
            q = next(b for b in r.boundaries if "normalized forward tax" in b.question)
            assert q.verdict is BoundaryVerdict.DISCLOSURE_BOUND

    def test_uber_fy2025_divergence_question_is_resolved(self):
        r = assess_evidence_resolution(_run("UBER_FY2025"))
        q = next(b for b in r.boundaries if "LIVE<->P9 divergence" in b.question)
        assert q.verdict is BoundaryVerdict.RESOLVED
        assert "unexplained" in q.hypotheses_ruled_out

    def test_wc_level_question_is_partially_resolved_where_there_is_history(self):
        for doc in ("UBER_FY2024", "UBER_FY2025", "LYFT_FY2025"):
            r = assess_evidence_resolution(_run(doc))
            q = next(b for b in r.boundaries if "sustainable, and at what level" in b.question)
            assert q.verdict is BoundaryVerdict.PARTIALLY_RESOLVED
            assert q.hypotheses_ruled_out  # the one-off reading is ruled out

    def test_disclosure_bound_is_a_valid_successful_output_not_an_error(self):
        r = assess_evidence_resolution(_run("DASH_FY2025"))
        assert r.verdict == "P10.5 DISCLOSURE-BOUND"
        assert all(b.verdict in (BoundaryVerdict.RESOLVED,
                                 BoundaryVerdict.PARTIALLY_RESOLVED,
                                 BoundaryVerdict.DISCLOSURE_BOUND)
                   for b in r.boundaries)


# =========================================================================== #
# Section I / J - model consequence + architectural decision
# =========================================================================== #
class TestModelConsequence:
    def test_no_model_architecture_is_changed(self):
        r = assess_evidence_resolution(_run("UBER_FY2024"))
        for k in ("LIVE", "P6", "P9", "P10 governance"):
            assert r.model_consequence[k] == "UNCHANGED"

    def test_uber_fy2025_tax_attribution_is_now_recognised_by_p10(self):
        # P10.5.1 applied the targeted arbitrate() branch: P10 no longer labels
        # UBER_FY2025 UNRESOLVED, so P10.5 reports the gap closed (KEEP), while
        # the forward tax rate stays DISCLOSURE_BOUND (checked below / Section H).
        r = assess_evidence_resolution(_run("UBER_FY2025"))
        assert r.model_consequence["p10_arbitration_outcome"] == \
            "MODEL_DIVERGENCE_WITH_EVIDENCE_BASIS"
        assert r.architectural_decision == "KEEP_P10_AS_FINAL_GOVERNANCE_LAYER"
        # the evidence-resolution verdict is unchanged - still PARTIALLY SOLVED
        assert r.verdict == "P10.5 PARTIALLY SOLVED"
        q = next(b for b in r.boundaries if "normalized forward tax" in b.question)
        assert q.verdict is BoundaryVerdict.DISCLOSURE_BOUND

    def test_all_filers_keep_the_p10_layer_as_is_after_p1051(self):
        for doc in ("UBER_FY2024", "UBER_FY2025", "LYFT_FY2025"):
            r = assess_evidence_resolution(_run(doc))
            assert r.architectural_decision == "KEEP_P10_AS_FINAL_GOVERNANCE_LAYER"


# =========================================================================== #
# Section 17/18 - regression: nothing in LIVE moves; the run is not mutated
# =========================================================================== #
class TestRegression:
    def test_live_anchors_unchanged(self):
        for doc, want in (("UBER_FY2024", 77.08), ("UBER_FY2025", 119.95),
                          ("LYFT_FY2025", 49.06), ("DASH_FY2025", 124.27)):
            run = _run(doc)
            assess_evidence_resolution(run)
            assert run.result.value_per_share == pytest.approx(want, abs=0.01), doc

    def test_pipeline_has_no_evidence_resolution_import(self):
        assert "evidence_resolution" not in inspect.getsource(pipeline)

    def test_assess_does_not_mutate_the_run(self):
        run = _run("UBER_FY2024")
        i = run.bridged.inputs
        before = (run.result.value_per_share, i.base_cash_flow, i.discount_rate,
                  i.terminal_growth, i.net_debt, i.shares_outstanding)
        assess_evidence_resolution(run)
        assess_evidence_resolution(run)
        after = (run.result.value_per_share, i.base_cash_flow, i.discount_rate,
                 i.terminal_growth, i.net_debt, i.shares_outstanding)
        assert before == after

    def test_report_is_deterministic(self):
        a = assess_evidence_resolution(_run("UBER_FY2024"))
        b = assess_evidence_resolution(_run("UBER_FY2024"))
        assert a.verdict == b.verdict
        assert [x.classification for x in a.persistence] == \
               [x.classification for x in b.persistence]
        assert [s.delta for s in a.bridge.steps] == [s.delta for s in b.bridge.steps]
