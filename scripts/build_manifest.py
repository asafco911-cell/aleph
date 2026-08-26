"""CLI entry point for manifest construction. This layer owns exit codes."""
import json
import sys
from pathlib import Path

from aleph.documents import DocumentError, build_manifest

DATA_DIR = Path("data")


def main() -> int:
    try:
        records = build_manifest(DATA_DIR)
    except DocumentError as exc:
        print(f"\nMANIFEST FAILED\n{exc}", file=sys.stderr)
        return 1

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
    sys.exit(main())