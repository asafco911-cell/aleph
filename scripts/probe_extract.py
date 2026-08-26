"""Extract facts from one target and report what passed the gates.

Rejections print the offending quote: a gate failure is only actionable if you
can see the text that triggered it. Quotes are recovered from the cache rather
than re-requested, so diagnosis costs nothing.
"""
import json
import sys
from pathlib import Path

import aleph
from aleph.extraction import extract
from aleph.extraction.extractor import DEFAULT_MODEL, PROMPT_VERSION, resolve_target
from aleph.extraction.gates import resolve_axis
from aleph.infra.cache import Cache
from aleph.schemas import DocumentRecord

doc_id, target = sys.argv[1], sys.argv[2]
question = sys.argv[3] if len(sys.argv) > 3 else "Extract every reported line item."

record = next(
    DocumentRecord(**r)
    for r in json.loads(Path("data/manifest.json").read_text(encoding="utf-8"))
    if r["doc_id"] == doc_id
)

source_text, _ = resolve_target(record, target)

accepted, rejected, cache_hit = extract(record, target, question)
print(f"{doc_id} {target}  cache_hit={cache_hit}")
print(f"accepted={len(accepted)}  rejected={len(rejected)}\n")

for fact in accepted:
    period = fact.period or "?"
    print(f"  {fact.name:<44} {fact.value:>14,.1f} {fact.unit}  [{period}]")
    print(f"     p{fact.source.pages}  {fact.quote[:90]}")

if rejected:
    # Recover quotes from the same cache entry the extractor just used.
    payload = Cache().get(Cache.key(
        sha256=record.sha256,
        prompt_version=PROMPT_VERSION,
        model=DEFAULT_MODEL,
        target=target,
        question=question,
    ))
    quotes = {item["name"]: item["quote"] for item in payload["facts"]} if payload else {}

    for failure in rejected:
        print(f"\n  REJECTED [{failure.gate}] {failure.fact_name}")
        print(f"     {failure.detail}")
        quote = quotes.get(failure.fact_name)
        if quote:
            print(f"     quote: {quote[:160]}")