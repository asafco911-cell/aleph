"""Validate the existing manifest against the canonical schema, and prove the
referential-integrity gate actually fires."""
import json
from pathlib import Path

from aleph.schemas import (
    Analysis, Claim, Computation, DocumentRecord, Edge,
    ExtractedFacts, Fact, ReferenceError_, check_references,
)

records = [DocumentRecord(**r) for r in json.loads(
    Path("data/manifest.json").read_text(encoding="utf-8"))]
print(f"manifest: {len(records)} records validated")
for record in records:
    print(f"  {record.doc_id:<12} {len(record.sections)} sections, "
          f"{len(record.verified_figures)} anchors")

edge = Edge(source="Uber", relation="REPORTED", target="Total revenue",
            period_start="FY2024", period_end="FY2025", value=52017.0,
            unit="USD millions")
print(f"\nedge covers FY2025: {edge.covers('FY2025')}  "
      f"FY2023: {edge.covers('FY2023')}")

facts = ExtractedFacts(facts=[
    Fact(name="Mobility revenue FY2024", value=25087.0,
         unit="USD millions", quote="Mobility $ 19,832 $ 25,087 26 %"),
])
bad = Analysis(
    computations=[Computation(label="growth",
                              expression="{Mobility Revenue FY2024} * 2")],
    claims=[Claim(supporting_facts=["Mobility revenue FY2024"],
                  claim="Mobility grew.")],
)
try:
    check_references(facts, bad)
    print("\nFAILED: reference gate did not fire")
    raise SystemExit(1)
except ReferenceError_ as exc:
    print(f"\nreference gate fired: {exc}")