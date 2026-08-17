"""Locate the PDF page where each 10-K item actually begins.

Cross-references share the item's title but not the "Item N." prefix pattern,
and never appear out of document order. Ordering is the strongest constraint:
each item must start at or after the previous one.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pypdf import PdfReader

from parse_toc import parse_toc
from textnorm import normalise


def find_candidates(pages: list[str], item: str, toc_page: int) -> list[tuple[int, int]]:
    """Return (page_number, char_offset) for every 'Item N.' heading pattern."""
    pattern = re.compile(rf"\bitem\s+{re.escape(item.lower())}\.\s")
    found = []
    for page_number, text in enumerate(pages, start=1):
        if page_number == toc_page:
            continue
        match = pattern.search(text)
        if match:
            found.append((page_number, match.start()))
    return found


def locate(path: Path, toc_page: int) -> list[dict]:
    entries = parse_toc(path, toc_page)
    if not entries:
        raise SystemExit(
            f"FAILED: no TOC entries parsed from {path.name} page {toc_page}. "
            "Wrong TOC page, or the TOC spans multiple pages."
        )
    pages = [normalise(p.extract_text() or "") for p in PdfReader(path).pages]

    located, floor = [], 0
    for entry in entries:
        candidates = find_candidates(pages, entry["item"], toc_page)
        # Ordering constraint: an item cannot start before the previous one.
        viable = [c for c in candidates if c[0] >= floor]
        if not viable:
            raise SystemExit(
                f"FAILED: Item {entry['item']} has no candidate at or after "
                f"page {floor}. candidates={candidates}"
            )
        page_number, offset = viable[0]
        floor = page_number
        located.append({**entry, "pdf_page": page_number, "char_offset": offset})
    return located


def main() -> None:
    path, toc_page = Path(sys.argv[1]), int(sys.argv[2])
    located = locate(path, toc_page)

    for row in located:
        delta = row["pdf_page"] - row["printed_page"]
        print(f"  Item {row['item']:<4} printed {row['printed_page']:>4} "
              f"-> pdf {row['pdf_page']:>4}  (delta {delta:+d})  char {row['char_offset']:>5}")

    deltas = {row["pdf_page"] - row["printed_page"] for row in located}
    print(f"\n{len(located)} items located. distinct deltas: {sorted(deltas)}")
    print(json.dumps(located, indent=2)[:0])  # placeholder, no output


if __name__ == "__main__":
    main()