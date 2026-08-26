"""Report the Item 8 structure map for one document. Diagnostic only."""
import json
import sys
from pathlib import Path

from aleph.documents import find_notes, find_statements
from aleph.schemas import DocumentRecord

records = [
    DocumentRecord(**r)
    for r in json.loads(Path("data/manifest.json").read_text(encoding="utf-8"))
]
targets = sys.argv[1:] or [r.doc_id for r in records]

for record in records:
    if record.doc_id not in targets:
        continue
    path = Path("data") / record.file_name
    item8 = next(s for s in record.sections if s.item == "8")
    print(f"\n=== {record.doc_id}: Item 8 = pages {item8.pdf_page}-{item8.end_page}")
    try:
        notes = find_notes(path, record.sections)
        statements = find_statements(path, record.sections, notes_start=notes[0].pdf_page)
    except Exception as exc:
        print(f"  FAILED: {exc}")
        continue

    for row in statements:
        print(f"  {row.name:<21} p{row.pdf_page:>3}-{row.end_page:<3}  {row.heading[:45]}")
    print(f"  notes: {notes[0].number}-{notes[-1].number} "
          f"({len(notes)}) p{notes[0].pdf_page}-{notes[-1].end_page}")