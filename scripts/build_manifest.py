"""CLI entry point for manifest construction. This layer owns exit codes.

`--allow-replacement` is the decision this layer makes and the library does
not: build_manifest raises when a filing's sha256 changed under an existing
doc_id, and only a human can say whether that is a corrected filing
superseding an original or the wrong document at that path (ISSUES.md #30).
"""
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from aleph.documents import DocumentError, build_manifest
from aleph.documents.manifest import committed_hashes, replaced_documents

DATA_DIR = Path("data")


def main(argv: list[str]) -> int:
    allow_replacement = "--allow-replacement" in argv
    unknown = [a for a in argv if a.startswith("-") and a != "--allow-replacement"]
    if unknown:
        print(f"unknown option(s): {unknown}. Only --allow-replacement is "
              "accepted.", file=sys.stderr)
        return 2

    # ValidationError is caught alongside DocumentError because DocumentRecord's
    # own validators reject a bad document too - a filing whose reported fiscal
    # year contradicts its doc_id raises here, not in inspect(). Found by
    # putting the wrong 10-K at an existing path: the run ended in a pydantic
    # traceback rather than a decision, which is not what principle 5 means by
    # "the CLI decides the exit code".
    try:
        records = build_manifest(DATA_DIR, allow_replacement=allow_replacement)
    except (DocumentError, ValidationError) as exc:
        print(f"\nMANIFEST FAILED\n{exc}", file=sys.stderr)
        return 1

    # Report the replacements that --allow-replacement waved through. Passing
    # the flag is a decision to overwrite, not a reason to stop saying what
    # was overwritten - a silent overwrite is the behaviour #30 named.
    if allow_replacement:
        for doc_id, old, new in replaced_documents(records, committed_hashes(DATA_DIR)):
            print(f"REPLACED  {doc_id}\n    was {old}\n    now {new}")

    for record in records:
        anchors = f"{len(record.verified_figures)} anchors" \
            if record.verified_figures else "no anchors"
        print(f"OK  {record.doc_id:<12} {record.n_pages:>3}p  "
              f"{len(record.sections):>2} sections  "
              f"deltas {record.page_offset_deltas}  {anchors}")

    payload = [r.model_dump() for r in records]
    (DATA_DIR / "manifest.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    print(f"\nWrote {len(records)} records to {DATA_DIR / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
