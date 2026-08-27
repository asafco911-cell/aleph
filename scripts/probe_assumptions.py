"""Derive assumption ranges from extracted facts and report their status."""
import json
import sys
from pathlib import Path

from aleph.extraction import extract
from aleph.schemas import DocumentRecord
from aleph.schemas.valuation import Override
from aleph.valuation import derive_all

TARGETS = [
    ("note:13", "Extract revenue by reportable segment for each year."),
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

doc_id = sys.argv[1]
record = next(
    DocumentRecord(**r)
    for r in json.loads(Path("data/manifest.json").read_text(encoding="utf-8"))
    if r["doc_id"] == doc_id
)

facts = []
for target, question in TARGETS:
    accepted, rejected, cache_hit = extract(record, target, question)
    print(f"  {target:<22} accepted={len(accepted):>2} rejected={len(rejected):>2} "
          f"cache_hit={cache_hit}")
    facts.extend(accepted)

raw = json.loads(Path("data/overrides.json").read_text(encoding="utf-8"))
overrides = {
    name: Override(**payload)
    for name, payload in raw.get(doc_id, {}).items()
}

print(f"\n{len(facts)} facts pooled, {len(overrides)} overrides loaded\n")

for assumption in derive_all(facts, overrides):
    print(f"=== {assumption.name}  [{assumption.status}]")
    if assumption.base is not None:
        print(f"    low={assumption.low:,.1f}  base={assumption.base:,.1f}  "
              f"high={assumption.high:,.1f} {assumption.unit}")
    print(f"    observations: "
          f"{[f'{o.period}={o.value:,.1f}' for o in assumption.observations]}")
    if assumption.excluded:
        print(f"    excluded:     "
              f"{[f'{o.period}={o.value:,.1f}' for o in assumption.excluded]}")
    print(f"    {assumption.rationale}\n")

blocked = [a.name for a in derive_all(facts, overrides) if a.status == "blocked"]
if blocked:
    print(f"BLOCKED: {blocked}")
    sys.exit(1)
