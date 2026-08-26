"""Extract facts from one target and report what passed the gates."""
import json
import sys
from pathlib import Path

from aleph.extraction import extract
from aleph.extraction.extractor import resolve_target
from aleph.extraction.gates import column_periods
from aleph.schemas import DocumentRecord

doc_id, target = sys.argv[1], sys.argv[2]
question = sys.argv[3] if len(sys.argv) > 3 else "Extract every reported line item."

record = next(
    DocumentRecord(**r)
    for r in json.loads(Path("data/manifest.json").read_text(encoding="utf-8"))
    if r["doc_id"] == doc_id
)

source_text, _ = resolve_target(record, target)
print(f"columns detected: {column_periods(source_text)}")

accepted, rejected, cache_hit = extract(record, target, question)
print(f"{doc_id} {target}  cache_hit={cache_hit}")
print(f"accepted={len(accepted)}  rejected={len(rejected)}\n")

for fact in accepted:
    period = fact.period or "?"
    print(f"  {fact.name:<44} {fact.value:>14,.1f} {fact.unit}  [{period}]")
    print(f"     p{fact.source.pages}  {fact.quote[:90]}")

for failure in rejected:
    print(f"\n  REJECTED [{failure.gate}] {failure.fact_name}: {failure.detail}")