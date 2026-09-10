"""Run every extraction target against every filing. Gate, not report.

The extraction layer was exercised only on Uber for a long stretch. Five
structural assumptions that looked like properties of 10-K filings turned out
to be properties of Uber's filing, and each broke on Lyft or DoorDash: TOC line
structure, note heading convention, equity statement wording, page offset, and
where geographic revenue is disclosed.

REQUIRED targets must yield facts. OPTIONAL ones may legitimately return
nothing: Lyft reports a single segment and files no segment note, and geography
is asked of several candidate notes of which most will not hold it.
"""
import json
import sys

from _filings import exit_on_missing_filing
from aleph.extraction import extract
from aleph.extraction.targets import resolve_targets
from aleph.infra.paths import DATA_DIR
from aleph.schemas import DocumentRecord

MIN_ACCEPTED = 3

records = [
    DocumentRecord(**r)
    for r in json.loads((DATA_DIR / "manifest.json").read_text(encoding="utf-8"))
]
only = sys.argv[1:] or None

failures: list[str] = []

for record in records:
    if only and record.doc_id not in only:
        continue

    print(f"\n=== {record.doc_id}")
    geography_hits = 0

    for key, target, question, required in resolve_targets(record):

        if target.startswith("UNRESOLVED"):
            count = int(target.split(":")[1])
            if count == 0 and not required:
                print(f"  ABSENT {key:<14} no note title matches; "
                      "not disclosed by this filer")
            else:
                failures.append(f"{record.doc_id}/{key}: {count} notes matched")
                print(f"  FAIL   {key:<14} title matched {count} notes")
            continue

        try:
            accepted, rejected, cache_hit = extract(record, target, question)
        except FileNotFoundError as exc:
            # NOT a per-target failure, so it does not go in `failures`.
            # Without the filings the broad handler below turned one missing
            # file into 97 lines of identical FAIL rows, one per target per
            # filing - loud, but it buried the single fact that matters.
            # This is the CLI boundary: one line, exit 1.
            exit_on_missing_filing(exc)
        except Exception as exc:
            failures.append(f"{record.doc_id}/{key}: {type(exc).__name__}: {exc}")
            print(f"  FAIL   {key:<14} {target:<12} "
                  f"{type(exc).__name__}: {str(exc)[:80]}")
            continue

        if key.startswith("geography") and accepted:
            geography_hits += len(accepted)

        units = sorted({fact.unit for fact in accepted}) or ["-"]
        ok = len(accepted) >= MIN_ACCEPTED
        if required and not ok:
            failures.append(
                f"{record.doc_id}/{key}: {len(accepted)} accepted "
                f"(min {MIN_ACCEPTED}), {len(rejected)} rejected"
            )

        status = "ok    " if ok else ("FAIL  " if required else "empty ")
        print(f"  {status} {key:<14} {target:<12} "
              f"acc={len(accepted):>2} rej={len(rejected):>2} "
              f"cache={str(cache_hit):<5} units={units}")

        for failure in rejected[:2]:
            print(f"           [{failure.gate}] {failure.detail[:95]}")

    # Geography feeds the country risk premium judgement, so its total absence
    # across every candidate note is worth flagging even though no single note
    # is required to hold it.
    if geography_hits == 0:
        print("  NOTE   geography not found in any candidate note")

print(f"\n{len(failures)} failures")
for line in failures:
    print(f"  {line}")

sys.exit(1 if failures else 0)