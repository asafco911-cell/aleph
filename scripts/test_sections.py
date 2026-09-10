"""Validate section extraction boundaries against contamination and truncation."""
import json
import sys

from _filings import exit_on_missing_filing
from aleph.documents import extract_section
from aleph.infra.paths import DATA_DIR
from aleph.schemas import DocumentRecord

MANIFEST = [DocumentRecord(**r) for r in json.loads(
    (DATA_DIR / "manifest.json").read_text(encoding="utf-8"))]


def check(doc_id: str, item: str) -> None:
    record = next(r for r in MANIFEST if r.doc_id == doc_id)
    path = DATA_DIR / record.file_name
    text = extract_section(path, record.sections, item)

    head = text[:70].replace("\n", " ")
    print(f"{doc_id} Item {item}: {len(text):>7,} chars")
    print(f"   head: {head}")

    row = next(r for r in record.sections if r.item == item)
    if f"item {item.lower()}." not in text[:100].lower():
        print("   FAILED: section does not begin with its own heading")
        sys.exit(1)
    if row.end_item and f"item {row.end_item.lower()}." in text[-200:].lower():
        print(f"   FAILED: bleeds into Item {row.end_item}")
        sys.exit(1)
    print("   ok")


# The filings are not distributed; without them this printed a 26-line pypdf
# traceback. Caught here, at the CLI boundary, never inside src/aleph/.
try:
    for doc in ("UBER_FY2024", "UBER_FY2025"):
        check(doc, "7")
        check(doc, "9A")
except FileNotFoundError as exc:
    exit_on_missing_filing(exc)
