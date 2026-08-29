"""Aleph valuation UI.

Design principle: no number appears without its provenance grade, and a
composite number inherits the WEAKEST grade in its chain. The headline is the
RANGE, not the point. A point estimate with a disclaimer beside it still
anchors the reader on the point; a range labelled with the judgements that
produce its ends does not.
"""
import json
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path("src/aleph/valuation")))

from aleph.extraction import extract
from aleph.schemas import DocumentRecord
from aleph.schemas.valuation import MarketAssumption, Override
from aleph.valuation import build_wacc, derive_all
from aleph.valuation.bridge import BridgeError, build_dcf_inputs

from dcf_engine import reverse_dcf, run_dcf, sensitivity_tornado

TARGETS = [
    ("note:13", "Extract revenue by reportable segment for each year."),
    ("note:13", "Extract revenue by geography."),
    ("note:11", "Extract the effective tax rate and the provision for income taxes."),
    ("statement:cash_flows",
     "Extract net cash provided by operating activities and purchases of "
     "property and equipment."),
    ("statement:operations",
     "Extract diluted weighted-average shares outstanding, interest expense, "
     "and net income attributable to Uber Technologies, Inc."),
    ("statement:balance_sheet",
     "Extract cash and cash equivalents, short-term investments, restricted "
     "cash, and long-term debt net of current portion."),
]

# Ordered weakest-last. A composite inherits the weakest grade in its chain.
GRADES = {
    "filing": ("FILING", "#1a7f37", "Extracted from the document and gate-verified"),
    "market": ("MARKET", "#0969da", "Observed market data, valid only at its as_of date"),
    "peer_group": ("PEER", "#9a6700", "Chosen comparison set; the choice is a judgement"),
    "analyst_judgment": ("JUDGEMENT", "#cf222e", "Stated by the analyst, not derived"),
}
GRADE_ORDER = ["filing", "market", "peer_group", "analyst_judgment"]


def weakest(*grades: str) -> str:
    """A derived number is only as evidenced as its weakest input."""
    return max(grades, key=lambda g: GRADE_ORDER.index(g))


def badge(grade: str) -> str:
    label, colour, _ = GRADES[grade]
    return (f"<span style='background:{colour};color:white;padding:2px 7px;"
            f"border-radius:3px;font-size:11px;font-weight:600;'>{label}</span>")


@st.cache_data(show_spinner=False)
def load_manifest() -> list[dict]:
    return json.loads(Path("data/manifest.json").read_text(encoding="utf-8"))


@st.cache_data(show_spinner="Extracting and validating facts...")
def pipeline(doc_id: str) -> dict:
    """Run the whole chain for one document. Cached at the extraction layer too."""
    record = next(DocumentRecord(**r) for r in load_manifest() if r["doc_id"] == doc_id)

    facts, rejected_all = [], []
    for target, question in TARGETS:
        accepted, rejected, _ = extract(record, target, question)
        facts.extend(accepted)
        rejected_all.extend(rejected)

    overrides = {
        name: Override(**payload)
        for name, payload in json.loads(
            Path("data/overrides.json").read_text(encoding="utf-8")
        ).get(doc_id, {}).items()
    }
    market = {
        name: MarketAssumption(**payload)
        for name, payload in json.loads(
            Path("data/market.json").read_text(encoding="utf-8")
        ).get(doc_id, {}).items()
    }

    ranges = {a.name: a for a in derive_all(facts, overrides)}
    blocked = [a for a in ranges.values() if a.status == "blocked"]

    result = {
        "record": record, "facts": facts, "rejected": rejected_all,
        "ranges": ranges, "market": market, "blocked": blocked,
    }
    if blocked:
        return result

    wacc = build_wacc(ranges, market)
    market["discount_rate"] = MarketAssumption(
        name="discount_rate", value=wacc.wacc, unit="decimal",
        as_of=market["risk_free_rate"].as_of, source="derived bottom-up",
        rationale=" | ".join(wacc.notes[:3]),
    )

    # Bounds for the discount rate come from beta bounds, not a hand-picked
    # band: once the rate is derived, an arbitrary band around it hides the
    # component that actually drives it.
    beta_base = market["unlevered_industry_beta"].value
    bounds = []
    for factor in (0.75, 1.45):
        trial = dict(market)
        trial["unlevered_industry_beta"] = market["unlevered_industry_beta"].model_copy(
            update={"value": beta_base * factor}
        )
        bounds.append(build_wacc(ranges, trial).wacc)

    bridged = build_dcf_inputs(ranges, market)
    bridged.tornado_ranges["discount_rate"] = (bounds[0], bounds[1])

    result.update({
        "wacc": wacc, "bridged": bridged,
        "dcf": run_dcf(bridged.inputs),
        "tornado": sensitivity_tornado(bridged.inputs, bridged.tornado_ranges),
        "beta_bounds": (beta_base * 0.75, beta_base, beta_base * 1.45),
        "wacc_bounds": bounds,
    })
    return result


st.set_page_config(page_title="Aleph", layout="wide")
st.title("Aleph")

doc_ids = [r["doc_id"] for r in load_manifest()]
doc_id = st.sidebar.selectbox("Filing", doc_ids)
data = pipeline(doc_id)
record = data["record"]

st.sidebar.caption(
    f"{record.company}\nFY{record.fiscal_year} 10-K, {record.n_pages} pages\n"
    f"sha256 {record.sha256[:16]}"
)
st.sidebar.markdown("**Provenance grades**")
for key in GRADE_ORDER:
    _, _, meaning = GRADES[key]
    st.sidebar.markdown(f"{badge(key)} {meaning}", unsafe_allow_html=True)

if data["blocked"]:
    st.error("Valuation blocked. Unverifiable inputs are not smoothed over.")
    for item in data["blocked"]:
        st.markdown(f"**{item.name}** — {item.rationale}")
    st.stop()

dcf, tornado = data["dcf"], data["tornado"]
low_beta, base_beta, high_beta = data["beta_bounds"]
discount_row = next(r for r in tornado if r["param"] == "discount_rate")

# The range is the headline. The point estimate is deliberately secondary: it
# is a single draw from a distribution shaped by two stated judgements.
st.subheader("Value per share")
left, right = st.columns([2, 1])
with left:
    st.markdown(
        f"### ${min(discount_row['low'], discount_row['high']):,.2f} "
        f"&nbsp;to&nbsp; ${max(discount_row['low'], discount_row['high']):,.2f}",
        unsafe_allow_html=True,
    )
    st.caption(
        f"Range spans an unlevered industry beta of {low_beta:.2f} to "
        f"{high_beta:.2f} (WACC {data['wacc_bounds'][0]:.2%} to "
        f"{data['wacc_bounds'][1]:.2%}). Both ends are defensible; the choice "
        "of industry classification is a judgement, not a derivation."
    )
    st.markdown(
        f"{badge('analyst_judgment')} &nbsp;This figure inherits the weakest "
        "grade in its chain.",
        unsafe_allow_html=True,
    )
with right:
    st.metric("Point estimate", f"${dcf.value_per_share:,.2f}",
              help=f"At beta {base_beta:.2f}. One draw from the range on the left.")
    st.metric("Terminal value share", f"{dcf.terminal_pct:.0%}",
              help="Fraction of value resting on the period beyond the forecast.")

price = st.number_input("Market price for reverse DCF", value=76.95, step=0.01)
implied = reverse_dcf(data["bridged"].inputs, price)
if implied is not None:
    st.info(
        f"At \\${price:,.2f} the market implies **{implied:.1%}** annual growth "
        f"for {len(data['bridged'].inputs.growth_rates)} years. This converts a "
        "valuation question into a business question."
    )

tab_assumptions, tab_evidence, tab_sensitivity = st.tabs(
    ["Assumptions", "Evidence", "Sensitivity"]
)

with tab_assumptions:
    for assumption in data["bridged"].inputs.assumptions:
        grade = assumption.source
        if assumption.name == "discount_rate":
            # Built from a peer beta and a stated country premium.
            grade = weakest("market", "peer_group", "analyst_judgment")
        st.markdown(
            f"{badge(grade)} &nbsp;**{assumption.name}** = "
            f"`{assumption.value:,.4g}`", unsafe_allow_html=True,
        )
        st.caption(assumption.rationale)
        st.divider()

with tab_evidence:
    st.caption(
        f"{len(data['facts'])} facts passed every gate; "
        f"{len(data['rejected'])} were rejected and are not used."
    )
    for fact in data["facts"]:
        with st.expander(
            f"{fact.name} = {fact.value:,.1f} {fact.unit}"
            f"  [{fact.period or 'no period'}]"
        ):
            st.markdown(badge("filing"), unsafe_allow_html=True)
            st.code(fact.quote, language=None)
            st.caption(
                f"{record.doc_id} - {fact.source.kind} {fact.source.ref}, "
                f"PDF pages {fact.source.pages} - "
                f"file {record.file_name} - sha256 {record.sha256[:16]}"
            )
    if data["rejected"]:
        st.subheader("Rejected")
        for failure in data["rejected"]:
            st.markdown(f"`{failure.gate}` **{failure.fact_name}** — {failure.detail}")

with tab_sensitivity:
    st.caption(
        "A tornado measures the ranges it is given, so bounds are stated here "
        "rather than left implicit."
    )
    for row in tornado:
        if row["swing"] is None:
            st.markdown(f"**{row['param']}** — a bound violates a consistency guard")
            continue
        st.markdown(
            f"**{row['param']}** &nbsp; ${row['low']:,.2f} to ${row['high']:,.2f} "
            f"&nbsp; swing ${row['swing']:,.2f} ({row['swing_pct']:.0%})"
        )
        st.progress(min(row["swing_pct"], 1.0))
    st.divider()
    st.markdown("**WACC components**")
    for note in data["wacc"].notes:
        st.text(note)