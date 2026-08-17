"""Parse the 10-K table of contents. Deterministic: regex only, no LLM.

The TOC is a regular structure, so an LLM would add non-determinism and cost
without adding capability.

Layout varies by filer. Uber and DoorDash emit one entry per line. Lyft runs
entries together, gluing the page number to the next item ("Business 5Item
1A."). Anchoring on end-of-line therefore fails on Lyft, so the page number is
identified by what FOLLOWS it instead.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pypdf import PdfReader

from textnorm import normalise

# "Item 7A. Quantitative and Qualitative Disclosures About Market Risk 68"
# The lookahead is what makes this safe: a lazy title match would otherwise
# stop at the digits inside "Form 10-K Summary".
RE_TOC_ENTRY = re.compile(
    r"item\s+(\d{1,2}[a-c]?)\.\s+(.+?)\s*(\d{1,3})\s*"
    r"(?=item\s+\d|part\s+[ivx]|signatures|exhibit|$)",
    re.IGNORECASE,
)


def parse_toc(path: Path, toc_page: int) -> list[dict]:
    """Return one record per TOC entry, in document order."""
    text = normalise(
        PdfReader(path).pages[toc_page - 1].extract_text() or "",
        fold_case=False,
    )
    entries = []
    for match in RE_TOC_ENTRY.finditer(text):
        entries.append({
            "item": match.group(1).upper(),
            "title": match.group(2).strip(),
            "printed_page": int(match.group(3)),
        })
    return entries


def main() -> None:
    path = Path(sys.argv[1])
    toc_page = int(sys.argv[2])
    entries = parse_toc(path, toc_page)

    for entry in entries:
        print(f"  Item {entry['item']:<4} p{entry['printed_page']:>4}  {entry['title'][:60]}")
    print(f"\n{len(entries)} entries parsed")

    if not entries:
        print("FAILED: zero entries parsed", file=sys.stderr)
        sys.exit(1)

    # Printed page numbers must never go backwards. Item 6 "[Reserved]" can
    # share a page with Item 7, so equality is allowed.
    pages = [e["printed_page"] for e in entries]
    if pages != sorted(pages):
        print("\nFAILED: printed page numbers are not monotonic", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()