"""Print the opening line of every page in a range. Used to find structural
boundaries inside a section without reading the whole thing."""
import sys
from pathlib import Path

from pypdf import PdfReader

from aleph.infra.textnorm import normalise

path = Path(sys.argv[1])
first, last = int(sys.argv[2]), int(sys.argv[3])
width = int(sys.argv[4]) if len(sys.argv) > 4 else 110

pages = PdfReader(path).pages
for page_number in range(first, last + 1):
    text = normalise(pages[page_number - 1].extract_text() or "")
    print(f"p{page_number:>3}  {text[:width]}")