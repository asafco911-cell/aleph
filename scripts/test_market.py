"""Prove market.json's shared/per_filing split holds (ISSUES.md #21).

Inputs that must be identical across filers - risk-free rate, ERP, terminal
growth, unlevered industry beta - used to sit in four separate per-doc_id
blocks, identical by discipline with nothing enforcing it. Something had
already drifted: LYFT_FY2025 cited a different Damodaran source string for
the same 0.81 beta, naming the sector table without the cash-corrected
column the 0.81 comes from.

Reads the committed data/market.json and needs no PDFs, so it runs in CI.
"""
import json
import sys
from pathlib import Path

from aleph.valuation.pipeline import MARKET, MarketDriftError, load_market

# Held identical across every filer on purpose. Changing this list is a
# change to the cross-company comparability policy (CLAUDE.md, docs/adr/0001),
# not a refactor.
MUST_BE_SHARED = {
    "risk_free_rate", "equity_risk_premium", "terminal_growth",
    "unlevered_industry_beta",
}
MAY_DIFFER = {"country_risk_premium", "debt_spread", "share_price"}


def payload() -> dict:
    return json.loads(MARKET.read_text(encoding="utf-8"))


def test_the_file_has_the_split_structure():
    data = payload()
    assert "shared" in data and "per_filing" in data, sorted(data)
    assert set(data["shared"]) == MUST_BE_SHARED, sorted(data["shared"])
    print(f"PASS test_the_file_has_the_split_structure "
          f"({len(data['per_filing'])} filings)")


def test_no_filing_redefines_a_shared_input():
    """The structural guarantee. Before the split this was discipline."""
    data = payload()
    for doc, block in data["per_filing"].items():
        overlap = sorted(set(block) & set(data["shared"]))
        assert not overlap, f"{doc} redefines {overlap}"
        assert set(block) <= MAY_DIFFER, f"{doc} carries unexpected {sorted(block)}"
    print("PASS test_no_filing_redefines_a_shared_input")


def test_a_redefinition_raises_rather_than_winning_quietly():
    """The negative control. Every assertion above requires the file to be
    clean; without this, they would all pass against a loader that merged a
    collision silently - which is the behaviour #21 exists to remove.
    """
    data = payload()
    doc = next(iter(data["per_filing"]))
    drifted = json.loads(json.dumps(data))
    drifted["per_filing"][doc]["unlevered_industry_beta"] = dict(
        data["shared"]["unlevered_industry_beta"], value=1.40
    )

    original = MARKET.read_text(encoding="utf-8")
    MARKET.write_text(json.dumps(drifted, indent=2), encoding="utf-8")
    try:
        load_market(doc)
    except MarketDriftError as exc:
        assert "unlevered_industry_beta" in str(exc), exc
        print(f"PASS test_a_redefinition_raises_rather_than_winning_quietly ({doc})")
        return
    finally:
        MARKET.write_text(original, encoding="utf-8")
    raise AssertionError("a per-filing redefinition was merged silently")


def test_every_valued_filing_gets_the_shared_inputs():
    data = payload()
    for doc in data["per_filing"]:
        merged = load_market(doc)
        missing = sorted(MUST_BE_SHARED - set(merged))
        assert not missing, f"{doc} missing {missing}"
        assert merged["unlevered_industry_beta"].value == 0.81, doc
        assert merged["risk_free_rate"].value == 0.0467, doc
    print(f"PASS test_every_valued_filing_gets_the_shared_inputs "
          f"({len(data['per_filing'])} filings)")


def test_a_filing_with_no_block_still_gets_the_shared_inputs():
    """DASH_FY2024 has no per_filing block. It must still see the shared
    inputs rather than an empty dict, so the run blocks on the judgements it
    actually lacks (share price, country premium) and not on the market."""
    merged = load_market("DASH_FY2024")
    assert set(merged) == MUST_BE_SHARED, sorted(merged)
    assert "share_price" not in merged
    print("PASS test_a_filing_with_no_block_still_gets_the_shared_inputs")


def test_the_beta_source_names_the_column_its_value_comes_from():
    """The drift that was actually found. 0.81 is Damodaran's unlevered beta
    CORRECTED FOR CASH; the plain unlevered figure is 0.77. A citation that
    omits the column points at the wrong number.
    """
    beta = payload()["shared"]["unlevered_industry_beta"]
    assert beta["value"] == 0.81, beta["value"]
    assert "corrected for cash" in beta["source"], beta["source"]
    print("PASS test_the_beta_source_names_the_column_its_value_comes_from")


def test_every_input_carries_a_real_source_and_date():
    data = payload()
    entries = list(data["shared"].items()) + [
        (f"{doc}.{k}", v)
        for doc, block in data["per_filing"].items() for k, v in block.items()
    ]
    for name, entry in entries:
        for field in ("value", "unit", "source", "as_of", "rationale"):
            assert field in entry, f"{name} missing {field}"
        assert entry["source"].strip().lower() not in (
            "placeholder", "todo", "tbd", "integration test"), f"{name}: {entry['source']}"
        assert len(entry["rationale"]) > 40, f"{name}: rationale too thin"
    print(f"PASS test_every_input_carries_a_real_source_and_date ({len(entries)} entries)")


if __name__ == "__main__":
    test_the_file_has_the_split_structure()
    test_no_filing_redefines_a_shared_input()
    test_a_redefinition_raises_rather_than_winning_quietly()
    test_every_valued_filing_gets_the_shared_inputs()
    test_a_filing_with_no_block_still_gets_the_shared_inputs()
    test_the_beta_source_names_the_column_its_value_comes_from()
    test_every_input_carries_a_real_source_and_date()
    print("\nAll tests passed.")
