"""Section boundary resolution and raw-text extraction.

Offsets from locate_sections are measured on NORMALISED text, which is a
different string of a different length than the raw extract. Slicing raw text
with a normalised offset cuts mid-word. Headings are therefore re-located in
the raw text before slicing. Extraction returns RAW text: citations must quote
the source verbatim or provenance breaks.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pypdf import PdfReader

from locate_sections import locate
from parse_toc import parse_toc


def find_toc_page(path: Path, search_depth: int = 12) -> int:
    """Return the page holding the most TOC entries. Deterministic, no guessing."""
    best_page, best_count = 0, 0
    for page_number in range(1, search_depth + 1):
        try:
            count = len(parse_toc(path, page_number))
        except IndexError:
            break
        if count > best_count:
            best_page, best_count = page_number, count
    if best_count < 15:
        raise SystemExit(
            f"FAILED: no TOC page found in {path.name} "
            f"(best was page {best_page} with {best_count} entries)"
        )
    return best_page


def add_ranges(located: list[dict], n_pages: int) -> list[dict]:
    """Close each section against the start of the next one."""
    for index, row in enumerate(located):
        if index + 1 < len(located):
            nxt = located[index + 1]
            row["end_page"], row["end_item"] = nxt["pdf_page"], nxt["item"]
        else:
            row["end_page"], row["end_item"] = n_pages, None
    return located


def raw_heading_offset(raw_text: str, item: str) -> int:
    """Locate 'Item N.' in RAW text. Raises rather than silently returning 0."""
    match = re.search(rf"\bitem\s+{re.escape(item)}\.", raw_text, re.IGNORECASE)
    if match is None:
        raise SystemExit(
            f"FAILED: heading 'Item {item}.' present in normalised text "
            "but not findable in raw text. Offsets cannot be reconciled."
        )
    return match.start()


def extract_section(path: Path, located: list[dict], item: str) -> str:
    """Return the raw text of one section, bounded at character resolution."""
    row = next((r for r in located if r["item"] == item.upper()), None)
    if row is None:
        raise SystemExit(f"FAILED: Item {item} not located in {path.name}")

    pages = PdfReader(path).pages
    start_page, end_page = row["pdf_page"], row["end_page"]

    first = pages[start_page - 1].extract_text() or ""
    start_offset = raw_heading_offset(first, row["item"])

    if start_page == end_page:
        end_offset = raw_heading_offset(first, row["end_item"])
        return first[start_offset:end_offset]

    parts = [first[start_offset:]]
    for page_number in range(start_page + 1, end_page):
        parts.append(pages[page_number - 1].extract_text() or "")

    last = pages[end_page - 1].extract_text() or ""
    if row["end_item"] is None:
        parts.append(last)
    else:
        parts.append(last[:raw_heading_offset(last, row["end_item"])])

    return "\n".join(parts)


def build_sections(path: Path) -> tuple[int, list[dict]]:
    toc_page = find_toc_page(path)
    n_pages = len(PdfReader(path).pages)
    return toc_page, add_ranges(locate(path, toc_page), n_pages)