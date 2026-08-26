"""Map a 10-K's internal structure and extract sections at character resolution.

TOC layout varies by filer: Uber and DoorDash emit one entry per line, Lyft
runs entries together and glues the page number to the next item. Anchoring on
end-of-line therefore fails, so the page number is identified by what FOLLOWS.

Offsets from location are measured on NORMALISED text, which is a different
string of a different length than the raw extract. Headings are re-located in
raw text before slicing; extraction returns RAW text, because citations must
quote the source verbatim or provenance breaks.
"""
import re
from pathlib import Path

from pypdf import PdfReader

from ..infra.textnorm import normalise
from ..schemas.documents import SectionRange
from .errors import DocumentError

# "Item 7A. Quantitative and Qualitative Disclosures About Market Risk 68"
# The lookahead is load-bearing: a lazy title match would otherwise stop at the
# digits inside "Form 10-K Summary".
RE_TOC_ENTRY = re.compile(
    r"item\s+(\d{1,2}[a-c]?)\.\s+(.+?)\s*(\d{1,3})\s*"
    r"(?=item\s+\d|part\s+[ivx]|signatures|exhibit|$)",
    re.IGNORECASE,
)

MIN_TOC_ENTRIES = 15


def parse_toc(path: Path, toc_page: int) -> list[dict]:
    """Return one record per TOC entry, in document order."""
    text = normalise(
        PdfReader(path).pages[toc_page - 1].extract_text() or "",
        fold_case=False,
    )
    return [
        {
            "item": match.group(1).upper(),
            "title": match.group(2).strip(),
            "printed_page": int(match.group(3)),
        }
        for match in RE_TOC_ENTRY.finditer(text)
    ]


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
    if best_count < MIN_TOC_ENTRIES:
        raise DocumentError(
            f"{path.name}: no TOC page found "
            f"(best was page {best_page} with {best_count} entries)"
        )
    return best_page


def _find_candidates(pages: list[str], item: str, toc_page: int) -> list[tuple[int, int]]:
    """Return (page, offset) for every 'Item N.' heading pattern outside the TOC."""
    pattern = re.compile(rf"\bitem\s+{re.escape(item.lower())}\.\s")
    found = []
    for page_number, text in enumerate(pages, start=1):
        if page_number == toc_page:
            continue
        match = pattern.search(text)
        if match:
            found.append((page_number, match.start()))
    return found


def build_sections(path: Path) -> tuple[int, list[SectionRange]]:
    """Locate every item and close each range against the next one.

    Cross-references share an item's title but never appear out of document
    order, so ordering is the strongest available constraint: each item must
    start at or after the previous one, and later on the same page.
    """
    toc_page = find_toc_page(path)
    entries = parse_toc(path, toc_page)
    if not entries:
        raise DocumentError(f"{path.name}: zero TOC entries on page {toc_page}")

    reader = PdfReader(path)
    n_pages = len(reader.pages)
    pages = [normalise(p.extract_text() or "") for p in reader.pages]

    located: list[dict] = []
    floor_page, floor_offset = 0, -1
    for entry in entries:
        candidates = _find_candidates(pages, entry["item"], toc_page)
        viable = [
            c for c in candidates
            if c[0] > floor_page or (c[0] == floor_page and c[1] > floor_offset)
        ]
        if not viable:
            raise DocumentError(
                f"{path.name}: Item {entry['item']} has no candidate after "
                f"page {floor_page} offset {floor_offset}. candidates={candidates}"
            )
        page_number, offset = viable[0]
        floor_page, floor_offset = page_number, offset
        located.append({**entry, "pdf_page": page_number, "char_offset": offset})

    ranges = []
    for index, row in enumerate(located):
        nxt = located[index + 1] if index + 1 < len(located) else None
        ranges.append(SectionRange(
            **row,
            end_page=nxt["pdf_page"] if nxt else n_pages,
            end_item=nxt["item"] if nxt else None,
        ))
    return toc_page, ranges


def _raw_offset(raw_text: str, item: str) -> int:
    """Locate 'Item N.' in RAW text. Raises rather than silently returning 0."""
    match = re.search(rf"\bitem\s+{re.escape(item)}\.", raw_text, re.IGNORECASE)
    if match is None:
        raise DocumentError(
            f"Heading 'Item {item}.' found in normalised text but not in raw text; "
            "offsets cannot be reconciled."
        )
    return match.start()


def extract_section(path: Path, sections: list[SectionRange], item: str) -> str:
    """Return the raw text of one section, bounded at character resolution."""
    row = next((s for s in sections if s.item == item.upper()), None)
    if row is None:
        raise DocumentError(f"{path.name}: Item {item} not located")

    pages = PdfReader(path).pages
    first = pages[row.pdf_page - 1].extract_text() or ""
    start = _raw_offset(first, row.item)

    if row.pdf_page == row.end_page:
        end = _raw_offset(first, row.end_item) if row.end_item else len(first)
        return first[start:end]

    parts = [first[start:]]
    for page_number in range(row.pdf_page + 1, row.end_page):
        parts.append(pages[page_number - 1].extract_text() or "")

    last = pages[row.end_page - 1].extract_text() or ""
    parts.append(last if row.end_item is None else last[:_raw_offset(last, row.end_item)])
    return "\n".join(parts)