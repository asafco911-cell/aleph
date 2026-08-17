"""Print the exact Unicode codepoint of every character around a keyword.

repr() escapes non-printable characters only. A printable look-alike
(e.g. a full-width comma) renders identically and stays invisible.
"""
import sys
import unicodedata
from pathlib import Path

from pypdf import PdfReader

path, page_no, keyword = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
span = int(sys.argv[4]) if len(sys.argv) > 4 else 12

text = PdfReader(path).pages[page_no - 1].extract_text() or ""
index = text.find(keyword)
if index == -1:
    print(f"'{keyword}' not found on page {page_no}")
    sys.exit(1)

start = max(0, index - span)
for offset, char in enumerate(text[start:index + len(keyword) + span]):
    code = ord(char)
    flag = "  <-- NON-ASCII" if code > 127 else ""
    name = unicodedata.name(char, "UNNAMED")
    print(f"{start + offset:>6}  {char!r:<8} U+{code:04X}  {name}{flag}")