"""Report what the manifest actually contains. Verifies the stored artifact,
not a recomputation of it."""
import json
from pathlib import Path

from aleph.schemas import DocumentRecord

for record in [DocumentRecord(**r) for r in json.loads(
        Path("data/manifest.json").read_text(encoding="utf-8"))]:
    names = [s.name for s in record.statements]
    print(f"{record.doc_id:<12} v{record.schema_version}  "
          f"{len(record.sections):>2} sections  "
          f"{len(record.statements)} statements  "
          f"{len(record.notes):>2} notes")
    print(f"             {names}")