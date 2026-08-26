"""Build validated DocumentRecords from anchors.json. No LLM involved.

Verified figures are read from a committed file, never from argv. Measured:
PowerShell silently converts the argument 25,087 into the string "25,87".
"""
import hashlib
import json
import re
from pathlib import Path

from pypdf import PdfReader

from ..infra.textnorm import contains
from ..schemas.documents import DocumentRecord, VerifiedFigure
from .errors import DocumentError
from .structure import build_sections

MONTHS = ("January|February|March|April|May|June|July|"
          "August|September|October|November|December")

RE_FISCAL_YEAR = re.compile(
    rf"For the fiscal year ended\s+({MONTHS})\s+(\d{{1,2}}),\s*(\d{{4}})"
)
RE_FORM_TYPE = re.compile(r"FORM\s+(10-K(?:/A)?)")
_CONTROL_WS = re.compile(r"[\s\x00-\x1f]+")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _exactly_one(pattern: re.Pattern, text: str, label: str, path: Path) -> re.Match:
    """Zero and two are both failures: two means the document is not a plain 10-K."""
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise DocumentError(
            f"{path.name}: expected exactly 1 match for {label}, found {len(matches)}.\n"
            f"Page 1 excerpt:\n{text[:300]}"
        )
    return matches[0]


def _check_anchors(path: Path, figures: dict[str, str]) -> dict[str, VerifiedFigure]:
    if not figures:
        return {}
    pages = [p.extract_text() or "" for p in PdfReader(path).pages]
    found = {}
    for label, value in figures.items():
        hits = [n for n, text in enumerate(pages, start=1) if contains(text, value)]
        if not hits:
            raise DocumentError(
                f"{path.name}: verified figure {label}={value} is absent. "
                "This is not the document the anchor was verified against."
            )
        found[label] = VerifiedFigure(value=value, pages=hits)
    return found


def inspect(doc_id: str, entry: dict, data_dir: Path) -> DocumentRecord:
    path = data_dir / entry["file_name"]
    if not path.exists():
        raise DocumentError(f"{doc_id}: file not found at {path}")

    reader = PdfReader(path)
    page_one = _CONTROL_WS.sub(" ", reader.pages[0].extract_text() or "")

    form_type = _exactly_one(RE_FORM_TYPE, page_one, "form type", path).group(1)
    if form_type != "10-K":
        raise DocumentError(
            f"{path.name}: form type is {form_type}, not 10-K. Amendments are "
            "partial documents and would fabricate omissions in language forensics."
        )

    fiscal = _exactly_one(RE_FISCAL_YEAR, page_one, "fiscal year end", path)
    month, day, year = fiscal.group(1), int(fiscal.group(2)), int(fiscal.group(3))

    toc_page, sections = build_sections(path)

    return DocumentRecord(
        doc_id=doc_id,
        file_name=path.name,
        ticker=entry["ticker"],
        company=entry["company"],
        sha256=_sha256(path),
        size_bytes=path.stat().st_size,
        n_pages=len(reader.pages),
        form_type=form_type,
        fiscal_year=year,
        fiscal_year_end=f"{year}-{month}-{day:02d}",
        toc_page=toc_page,
        page_offset_deltas=sorted({s.pdf_page - s.printed_page for s in sections}),
        sections=sections,
        verified_figures=_check_anchors(path, entry["verified_figures"]),
        verification_source=entry["verification_source"],
    )


def build_manifest(data_dir: Path) -> list[DocumentRecord]:
    anchors = json.loads((data_dir / "anchors.json").read_text(encoding="utf-8"))

    records, seen = [], {}
    for doc_id, entry in anchors.items():
        record = inspect(doc_id, entry, data_dir)
        if record.sha256 in seen:
            raise DocumentError(
                f"Duplicate content: {doc_id} and {seen[record.sha256]} share a SHA-256."
            )
        seen[record.sha256] = doc_id
        records.append(record)
    return records