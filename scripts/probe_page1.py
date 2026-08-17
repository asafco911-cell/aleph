"""Probe: dump page-1 text so regex is written against reality, not assumption."""
import sys
from pathlib import Path
from pypdf import PdfReader

path = Path(sys.argv[1])
reader = PdfReader(path)
text = reader.pages[0].extract_text() or ""

print(f"FILE      : {path.name}")
print(f"PAGES     : {len(reader.pages)}")
print(f"CHARS(p1) : {len(text)}")
print("-" * 60)
print(repr(text[:900]))