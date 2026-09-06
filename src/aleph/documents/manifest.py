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
from .notes import find_notes
from .statements import find_statements

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
    notes = find_notes(path, sections)
    statements = find_statements(path, sections, notes_start=notes[0].pdf_page)

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
        notes=notes,
        statements=statements,
        verified_figures=_check_anchors(path, entry["verified_figures"]),
        verification_source=entry["verification_source"],
    )


def committed_hashes(data_dir: Path) -> dict[str, str]:
    """doc_id -> sha256, from the manifest already on disk.

    Missing or unreadable is not an error: the first build has no previous
    manifest to compare against, and a corrupt one is not evidence that a
    document was replaced.
    """
    path = data_dir / "manifest.json"
    if not path.exists():
        return {}
    try:
        committed = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return {
        row["doc_id"]: row["sha256"]
        for row in committed
        if isinstance(row, dict) and "doc_id" in row and "sha256" in row
    }


def replaced_documents(
    records: list[DocumentRecord], previous: dict[str, str]
) -> list[tuple[str, str, str]]:
    """Return (doc_id, committed_sha256, new_sha256) for each replacement.

    schemas/documents.py states the principle: doc_id is the stable id and
    sha256 is "Content identity. The file name is metadata; this is not."
    Same doc_id with a different hash therefore means the document was
    replaced - and until this function existed, nothing checked it
    (ISSUES.md #30). None of inspect()'s own checks can catch it: the form
    type, the fiscal year and the anchor strings can all still match while
    the bytes change underneath.
    """
    return [
        (record.doc_id, previous[record.doc_id], record.sha256)
        for record in records
        if record.doc_id in previous and previous[record.doc_id] != record.sha256
    ]


def build_manifest(
    data_dir: Path, allow_replacement: bool = False
) -> list[DocumentRecord]:
    """Build every record, raising if a document was replaced under its doc_id.

    A library raises; the CLI decides the exit code (principle 5). This
    raises DocumentError on a replacement so the decision is forced; the
    caller passes allow_replacement=True once the replacement is deliberate
    - a corrected 10-K/A superseding an original, or a re-rendered PDF.
    """
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

    replaced = replaced_documents(records, committed_hashes(data_dir))
    if replaced and not allow_replacement:
        listing = "\n".join(
            f"  {doc_id}\n    committed {old}\n    on disk   {new}"
            for doc_id, old, new in replaced
        )
        raise DocumentError(
            f"{len(replaced)} document(s) changed content under an existing "
            f"doc_id:\n{listing}\n"
            "sha256 is content identity, so this means the file at that path is "
            "not the document the committed results were produced from. Every "
            "other check here can still pass while this is true.\n"
            "If the replacement is deliberate, re-run with --allow-replacement "
            "and record why in data/README.md."
        )
    return records