"""Verify that normalised matching finds text that raw matching misses."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pypdf import PdfReader

from textnorm import contains, normalise

TARGET = "Management's Discussion and Analysis"
PATH = Path("data/uber_10k_fy2024.pdf")

text = PdfReader(PATH).pages[2].extract_text() or ""

print(f"raw        : {TARGET in text}")
print(f"normalised : {contains(text, TARGET)}")
print(f"needle     : {normalise(TARGET)!r}")