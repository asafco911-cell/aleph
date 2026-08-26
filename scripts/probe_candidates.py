"""Count normalised occurrences of a phrase across every page."""
import sys
from pathlib import Path

from pypdf import PdfReader

from aleph.infra.textnorm import normalise

sys.path.insert(0, str(Path(__file__).parent))

from pypdf import PdfReader

from textnorm import normalise

path = Path(sys.argv[1])
needle = normalise(sys.argv[2])

for page_number, page in enumerate(PdfReader(path).pages, start=1):
    text = normalise(page.extract_text() or "")
    position = text.find(needle)
    if position != -1:
        print(f"  p{page_number:>3}  char {position:>5}  ...{text[max(0,position-40):position+60]}...")