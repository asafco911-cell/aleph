"""Inspect the raw extracted text around a keyword, on a specific page.

Uses repr() because the failure mode is almost always an invisible character.
"""
import sys
from pathlib import Path

from pypdf import PdfReader

path, page_no, keyword = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
window = int(sys.argv[4]) if len(sys.argv) > 4 else 400

text = PdfReader(path).pages[page_no - 1].extract_text() or ""
index = text.find(keyword)

if index == -1:
    print(f"'{keyword}' not found on page {page_no}")
    sys.exit(1)

start = max(0, index - 50)
print(f"{path.name} p{page_no}, '{keyword}' at char {index}")
print("-" * 60)
print(repr(text[start:start + window]))