"""Deterministic document verifier and manifest builder. No LLM involved.

Fails loudly on any anomaly: a silent None is worse than a crash.

Verified figures are read from data/anchors.json, never from argv. Measured:
PowerShell silently converts the argument 25,087 into the string "25,87".
"""
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pypdf import PdfReader

from sections import build_sections
from textnorm import contains

DATA_DIR = Path("data")
ANCHORS_PATH = DATA_DIR / "anchors.json"
MANIFEST_PATH = DATA_DIR / "manifest.json"

MONTHS = ("January|February|March|April|May|June|July|"
          "August|September|October|November|December")

RE_FISCAL_YEAR = re.compile(
    rf"For the fiscal year ended\s+({MONTHS})\s+(\d{{1,2}}),\s*(\d{{4}})"
)
RE_FORM_TYPE = re.compile(r"FORM\s+(10-K(?:/A)?)")

_CONTROL_WS = re.compile(r"[\s\x00-\x1f]+")


class ManifestError(Exception):
    """Raised when a document is not what it claims to be."""


def flatten(text: str) -> str:
    return _CONTROL_WS.sub(" ", text)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_one(pattern: re.Pattern, text: str, label: str, path: Path) -> re.Match:
    """Return the single match, or raise. Zero and two are both failures."""
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ManifestError(
            f"{path.name}: expected exactly 1 match for {label}, "
            f"found {len(matches)}.\nPage 1 excerpt:\n{text[:300]}"
        )
    return matches[0]


def check_anchors(path: Path, figures: dict) -> dict:
    """Confirm every verified figure still appears in the document body."""
    if not figures:
        return {}
    pages = [p.extract_text() or "" for p in PdfReader(path).pages]
    found = {}
    for label, value in figures.items():
        hits = [n for n, text in enumerate(pages, start=1) if contains(text, value)]
        if not hits:
            raise ManifestError(
                f"{path.name}: verified figure {label}={value} is absent. "
                "The document is not the one this anchor was verified against."
            )
        found[label] = {"value": value, "pages": hits}
    return found


def inspect(doc_id: str, entry: dict) -> dict:
    path = DATA_DIR / entry["file_name"]
    if not path.exists():
        raise ManifestError(f"{doc_id}: file not found at {path}")

    reader = PdfReader(path)
    page_one = flatten(reader.pages[0].extract_text() or "")

    form_type = extract_one(RE_FORM_TYPE, page_one, "form type", path).group(1)
    if form_type != "10-K":
        raise ManifestError(
            f"{path.name}: form type is {form_type}, not 10-K. "
            "Amendments are partial documents and break language forensics."
        )

    fiscal = extract_one(RE_FISCAL_YEAR, page_one, "fiscal year end", path)
    month, day, year = fiscal.group(1), int(fiscal.group(2)), int(fiscal.group(3))

    # doc_id encodes the fiscal year, so a mismatch means the mapping is wrong.
    if not doc_id.endswith(f"FY{year}"):
        raise ManifestError(
            f"{doc_id}: document reports fiscal year {year}. "
            "doc_id and document disagree."
        )

    toc_page, located = build_sections(path)
    deltas = sorted({row["pdf_page"] - row["printed_page"] for row in located})

    return {
        "doc_id": doc_id,
        "file_name": path.name,
        "ticker": entry["ticker"],
        "company": entry["company"],
        "sha256": sha256_of(path),
        "size_bytes": path.stat().st_size,
        "n_pages": len(reader.pages),
        "form_type": form_type,
        "fiscal_year_end": f"{year}-{month}-{day:02d}",
        "fiscal_year": year,
        "toc_page": toc_page,
        "page_offset_deltas": deltas,
        "sections": located,
        "verified_figures": check_anchors(path, entry["verified_figures"]),
        "verification_source": entry["verification_source"],
    }


def main() -> None:
    anchors = json.loads(ANCHORS_PATH.read_text(encoding="utf-8"))

    records, seen_hashes = [], {}
    for doc_id, entry in anchors.items():
        record = inspect(doc_id, entry)

        digest = record["sha256"]
        if digest in seen_hashes:
            raise ManifestError(
                f"Duplicate content: {doc_id} and {seen_hashes[digest]} "
                "share the same SHA-256."
            )
        seen_hashes[digest] = doc_id

        records.append(record)
        anchor_note = f"{len(record['verified_figures'])} anchors" \
            if record["verified_figures"] else "no anchors"
        print(f"OK  {doc_id:<12} {record['n_pages']:>3}p  "
              f"{len(record['sections']):>2} sections  "
              f"deltas {record['page_offset_deltas']}  {anchor_note}")

    MANIFEST_PATH.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"\nWrote {len(records)} records to {MANIFEST_PATH}")


if __name__ == "__main__":
    try:
        main()
    except ManifestError as exc:
        print(f"\nMANIFEST FAILED\n{exc}", file=sys.stderr)
        sys.exit(1)