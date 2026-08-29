"""Dump note titles for every filing. Note numbering and titling vary by
filer, so title-based resolution has to be checked against reality."""
import json
import sys
from pathlib import Path

from aleph.schemas import DocumentRecord

needle = sys.argv[1].lower() if len(sys.argv) > 1 else None

for record in [DocumentRecord(**r) for r in json.loads(
        Path("data/manifest.json").read_text(encoding="utf-8"))]:
    print(f"\n=== {record.doc_id}")
    for note in record.notes:
        if needle and needle not in note.title.lower():
            continue
        print(f"  {note.number:>2}  p{note.pdf_page:>3}  {note.title[:80]}")