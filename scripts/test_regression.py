"""Regression gate over every extraction target that has ever passed.

Runs entirely from cache: zero tokens, so there is no excuse for checking one
target instead of all of them. Gate, not report - exit(1) on any shortfall.
"""
import json
import sys
from pathlib import Path

from aleph.extraction import extract
from aleph.schemas import DocumentRecord

# doc_id, target, question, minimum accepted facts
EXPECTED = [
    ("UBER_FY2024", "note:13", "Extract revenue by geography.", 12),
    ("UBER_FY2024", "note:13",
     "Extract revenue by reportable segment for each year.", 12),
    ("UBER_FY2024", "note:11",
     "Extract the effective tax rate and the provision for income taxes.", 6),
    ("UBER_FY2024", "statement:cash_flows",
     "Extract net cash provided by operating activities and purchases of "
     "property and equipment.", 6),
    ("UBER_FY2024", "statement:operations",
     "Extract diluted weighted-average shares outstanding and net income "
     "attributable to Uber Technologies, Inc.", 6),
]

records = {
    r["doc_id"]: DocumentRecord(**r)
    for r in json.loads(Path("data/manifest.json").read_text(encoding="utf-8"))
}

failures = 0
for doc_id, target, question, minimum in EXPECTED:
    accepted, rejected, cache_hit = extract(records[doc_id], target, question)
    ok = len(accepted) >= minimum
    failures += not ok
    print(f"  {'ok  ' if ok else 'FAIL'} {doc_id} {target:<22} "
          f"accepted={len(accepted):>2} (min {minimum})  "
          f"rejected={len(rejected):>2}  cache_hit={cache_hit}")
    if not ok:
        for failure in rejected[:3]:
            print(f"         [{failure.gate}] {failure.detail[:110]}")

sys.exit(1 if failures else 0)