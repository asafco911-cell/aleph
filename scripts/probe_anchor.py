"""Sanity probe: confirm known-verified figures exist in the document body.

This does not parse tables. It only proves the text layer is intact and the
document contains the numbers verified independently in ch05, ch07 and ch08.
"""
import sys
from pathlib import Path

from pypdf import PdfReader

path = Path(sys.argv[1])
targets = sys.argv[2:]

reader = PdfReader(path)
hits = {t: [] for t in targets}

for page_number, page in enumerate(reader.pages, start=1):
    text = page.extract_text() or ""
    for target in targets:
        if target in text:
            hits[target].append(page_number)

print(f"FILE: {path.name}  ({len(reader.pages)} pages)")
for target, pages in hits.items():
    status = "FOUND" if pages else "MISSING"
    print(f"  {target:<10} {status:<8} pages={pages}")

if any(not pages for pages in hits.values()):
    sys.exit(1)