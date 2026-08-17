"""Probe: dump page-1 text so regex is written against reality, not assumption."""
import sys
from pathlib import Path
from pypdf import PdfReader

path = Path(sys.argv[1])
page_no = int(sys.argv[2]) if len(sys.argv) > 2 else 1
chars = int(sys.argv[3]) if len(sys.argv) > 3 else 900
reader = PdfReader(path)
text = reader.pages[page_no - 1].extract_text() or ""

print(f"FILE      : {path.name}")
print(f"PAGES     : {len(reader.pages)}")
print(f"CHARS(p{page_no}) : {len(text)}")
print("-" * 60)
print(repr(text[:chars]))