"""Map the notes to the consolidated financial statements inside Item 8.

Two heading conventions exist in practice:

  Form A (Uber):        "Note 13 - Segment Information"
  Form B (Lyft, DASH):  "13. Segment Information"

Under Form B the "Note N -" wording is reserved for CROSS-REFERENCES, the exact
inverse of Form A, so lexical rules alone cannot separate heading from
reference. Structure can: a heading opens a line, a cross-reference sits inside
a sentence. Detection is therefore line-anchored, and the form in use is
measured per document rather than assumed.
"""
import re
from pathlib import Path

from pypdf import PdfReader

from ..infra.textnorm import normalise_lines
from ..schemas.documents import NoteRange, SectionRange
from .errors import DocumentError

# "Note 13 - Segment Information and Geographic Information"
RE_NOTE_PREFIXED = re.compile(
    r"^note\s+(\d{1,2})\s*[-:]\s*(.{3,80})$",
    re.MULTILINE | re.IGNORECASE,
)

# "13. Segment Information and Geographic Information"
# The capital letter is required: it separates a heading from a numeric table
# row that happens to begin a line.
RE_NOTE_BARE = re.compile(
    r"^(\d{1,2})\.\s+([A-Z].{3,80})$",
    re.MULTILINE,
)

MIN_NOTES = 5


def _item8_range(sections: list[SectionRange]) -> tuple[int, int]:
    row = next((s for s in sections if s.item == "8"), None)
    if row is None:
        raise DocumentError("Item 8 not present in section map")
    return row.pdf_page, row.end_page


def _collect(pages: dict[int, str], pattern: re.Pattern) -> dict[int, list[tuple[int, int, str]]]:
    candidates: dict[int, list[tuple[int, int, str]]] = {}
    for page_number, text in pages.items():
        for match in pattern.finditer(text):
            number = int(match.group(1))
            candidates.setdefault(number, []).append(
                (page_number, match.start(), match.group(2).strip())
            )
    return candidates


def find_notes(path: Path, sections: list[SectionRange]) -> list[NoteRange]:
    """Locate every note heading within Item 8, in numeric order."""
    start_page, end_page = _item8_range(sections)
    reader = PdfReader(path)
    pages = {
        n: normalise_lines(reader.pages[n - 1].extract_text() or "")
        for n in range(start_page, end_page + 1)
    }

    # Measure the convention instead of assuming it.
    prefixed = _collect(pages, RE_NOTE_PREFIXED)
    bare = _collect(pages, RE_NOTE_BARE)
    candidates = prefixed if len(prefixed) >= len(bare) else bare

    if len(candidates) < MIN_NOTES:
        raise DocumentError(
            f"{path.name}: no note heading convention matched in Item 8 "
            f"(pages {start_page}-{end_page}). "
            f"prefixed={len(prefixed)} bare={len(bare)}"
        )

    located: list[dict] = []
    skipped: list[int] = []
    floor_page, floor_offset = start_page - 1, -1

    for number in sorted(candidates):
        viable = [
            c for c in candidates[number]
            if c[0] > floor_page or (c[0] == floor_page and c[1] > floor_offset)
        ]
        if not viable:
            skipped.append(number)
            continue
        page_number, offset, title = viable[0]
        floor_page, floor_offset = page_number, offset
        located.append({
            "number": number,
            "title": title,
            "pdf_page": page_number,
            "char_offset": offset,
        })

    # A gap in an otherwise increasing sequence means headings were missed, not
    # that the filer skipped a number. Silence would leave the extractor blind
    # to entire notes.
    numbers = [row["number"] for row in located]
    gaps = [n for n in range(min(numbers), max(numbers) + 1) if n not in numbers]
    if gaps or skipped:
        raise DocumentError(
            f"{path.name}: note map incomplete. missing={gaps} "
            f"out_of_order={skipped}. Located {len(located)} notes "
            f"in pages {start_page}-{end_page}."
        )

    ranges = []
    for index, row in enumerate(located):
        nxt = located[index + 1] if index + 1 < len(located) else None
        ranges.append(NoteRange(
            **row,
            end_page=nxt["pdf_page"] if nxt else end_page,
            end_number=nxt["number"] if nxt else None,
        ))
    return ranges


def _raw_offset(text: str, number: int) -> int:
    """Locate a note heading in RAW text, trying both conventions."""
    for pattern in (
        rf"^\s*note\s+{number}\s*[-:\u2013\u2014]",
        rf"^\s*{number}\.\s+[A-Z]",
    ):
        match = re.search(pattern, text, re.MULTILINE | re.IGNORECASE)
        if match:
            return match.start()
    raise DocumentError(
        f"Note {number} heading found in normalised text but not raw; "
        "offsets cannot be reconciled."
    )


def extract_note(path: Path, notes: list[NoteRange], number: int) -> str:
    """Return the raw text of one note, bounded at character resolution."""
    row = next((n for n in notes if n.number == number), None)
    if row is None:
        raise DocumentError(f"{path.name}: Note {number} not located")

    pages = PdfReader(path).pages
    first = pages[row.pdf_page - 1].extract_text() or ""
    start = _raw_offset(first, row.number)

    if row.pdf_page == row.end_page:
        end = _raw_offset(first, row.end_number) if row.end_number else len(first)
        return first[start:end]

    parts = [first[start:]]
    for page_number in range(row.pdf_page + 1, row.end_page):
        parts.append(pages[page_number - 1].extract_text() or "")

    last = pages[row.end_page - 1].extract_text() or ""
    parts.append(last if row.end_number is None
                 else last[:_raw_offset(last, row.end_number)])
    return "\n".join(parts)