"""Map the primary financial statements inside Item 8.

Statement headings are statutory wording, repeated as a running header on every
page of the statement. Detection is therefore a page-classification problem,
not a boundary-search problem: a page belongs to a statement if it carries that
statement's header.

Equity statement wording varies by filer (redeemable non-controlling interests
vs stockholders' equity), so several alternatives map to one canonical name.
"""
import re
from pathlib import Path

from pypdf import PdfReader

from ..infra.textnorm import normalise
from ..schemas.documents import SectionRange, StatementRange
from .errors import DocumentError

STATEMENT_PATTERNS: dict[str, list[str]] = {
    "auditor_report": [r"report of independent registered public accounting firm"],
    "balance_sheet": [r"consolidated balance sheets?"],
    "operations": [r"consolidated statements? of operations"],
    "comprehensive_income": [r"consolidated statements? of comprehensive (?:income|loss)"],
    # Equity heading wording varies widely between filers: "stockholders'
    # equity", "changes in equity", "redeemable non-controlling interests and
    # stockholders' equity". An enumerated list of variants failed on the third
    # filer tested, so the middle is matched loosely instead.
    "equity": [r"consolidated statements? of [a-z',\- ]{0,70}equity"],
    "cash_flows": [r"consolidated statements? of cash flows"],
}

# Every 10-K files all of these. A missing one is a detection failure, not an
# absent statement: the range-closing logic would silently fold its pages into
# the preceding statement.
REQUIRED = ("balance_sheet", "operations", "comprehensive_income",
            "equity", "cash_flows")


def find_statements(
    path: Path, sections: list[SectionRange], notes_start: int | None = None
) -> list[StatementRange]:
    """Classify every page of Item 8 that precedes the notes.

    The first page of Item 8 is an index listing every statement title, so it
    is excluded exactly as the TOC page is excluded when locating items.
    Statements are contiguous, so each one is closed against the start of the
    next: continuation pages do not repeat the running header, and classifying
    by header alone would silently truncate them.
    """
    item8 = next((s for s in sections if s.item == "8"), None)
    if item8 is None:
        raise DocumentError("Item 8 not present in section map")

    index_page = item8.pdf_page
    last_page = (notes_start - 1) if notes_start else item8.end_page
    reader = PdfReader(path)

    starts: dict[str, tuple[int, str]] = {}
    for page_number in range(index_page + 1, last_page + 1):
        text = normalise(reader.pages[page_number - 1].extract_text() or "")
        head = text[:200]  # running header only, never body text
        for name, patterns in STATEMENT_PATTERNS.items():
            if name in starts:
                continue
            for pattern in patterns:
                match = re.search(pattern, head)
                if match:
                    starts[name] = (page_number, match.group(0))
                    break

    missing = [name for name in REQUIRED if name not in starts]
    if missing:
        raise DocumentError(
            f"{path.name}: required statements not found in Item 8 "
            f"(pages {index_page + 1}-{last_page}): {missing}"
        )

    ordered = sorted(starts.items(), key=lambda kv: kv[1][0])
    ranges = []
    for index, (name, (page_number, heading)) in enumerate(ordered):
        end = ordered[index + 1][1][0] - 1 if index + 1 < len(ordered) else last_page
        ranges.append(StatementRange(
            name=name, heading=heading, pdf_page=page_number, end_page=end
        ))
    return ranges

    return [
        StatementRange(
            name=name, heading=heading, pdf_page=min(pages), end_page=max(pages)
        )
        for name, (pages, heading) in sorted(hits.items(), key=lambda kv: min(kv[1][0]))
    ]


def extract_statement(path: Path, statements: list[StatementRange], name: str) -> str:
    """Return the raw text of one statement."""
    row = next((s for s in statements if s.name == name), None)
    if row is None:
        raise DocumentError(f"{path.name}: statement '{name}' not located")
    pages = PdfReader(path).pages
    return "\n".join(
        pages[n - 1].extract_text() or ""
        for n in range(row.pdf_page, row.end_page + 1)
    )