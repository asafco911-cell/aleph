"""Deterministic document metadata. No LLM produces any field here.

This is the only schema family that crosses a TIME boundary: it is written to
data/manifest.json, committed to git, and read by future runs. Every other
schema is regenerated each run and can change freely. A breaking change here
invalidates every existing manifest and every provenance chain pointing at it,
which is why this family alone carries a version.
"""
from typing import Optional

from pydantic import BaseModel, Field, model_validator

SCHEMA_VERSION = 3


class SectionRange(BaseModel):
    """Boundaries of one 10-K item, at character resolution.

    Page resolution is insufficient: seven items can share a single page, and
    a page-level cut would silently bleed a neighbouring section into the text.
    Contaminated boundaries fabricate exactly the signal that year-over-year
    language forensics is built to detect.
    """
    item: str = Field(description="Item identifier, e.g. '7', '7A', '9B'.")
    title: str
    printed_page: int = Field(description="Page number as printed in the TOC.")
    pdf_page: int = Field(description="1-based index into PdfReader.pages.")
    char_offset: int = Field(description="Heading offset within the NORMALISED page text.")
    end_page: int
    end_item: Optional[str] = Field(
        default=None, description="Item that closes this range. None means end of document."
    )


class VerifiedFigure(BaseModel):
    """A figure independently verified outside this pipeline."""
    value: str = Field(description="Verbatim string as it appears in the filing, e.g. '43,978'.")
    pages: list[int] = Field(description="PDF pages where the string was found.")

class NoteRange(BaseModel):
    """One note to the consolidated financial statements, inside Item 8.

    Item 8 spans dozens of pages, so section scoping alone leaves far too much
    text for an extractor. Notes give a second resolution layer, and they also
    disambiguate: the same metric name appears under different definitions in
    MD&A and in the notes, so a fact is only interpretable once its origin is
    known.
    """
    number: int
    title: str
    pdf_page: int
    char_offset: int = Field(description="Heading offset within NORMALISED page text.")
    end_page: int
    end_number: Optional[int] = Field(
        default=None, description="Note that closes this range. None means end of Item 8."
    )

class StatementRange(BaseModel):
    """One primary financial statement inside Item 8.

    Statements are identified by statutory heading text, which the SEC dictates
    and which appears as a running header on every page of the statement. Notes
    are identified by number. Two different structures, two different maps.
    """
    name: str = Field(description="Canonical key, e.g. 'cash_flows', 'operations'.")
    heading: str = Field(description="Statutory heading as matched.")
    pdf_page: int
    end_page: int

class DocumentRecord(BaseModel):
    """One filing, fully identified and structurally mapped."""
    schema_version: int = Field(default=SCHEMA_VERSION)

    doc_id: str = Field(description="Human-authored stable id, e.g. 'UBER_FY2025'.")
    file_name: str
    ticker: str
    company: str

    sha256: str = Field(description="Content identity. The file name is metadata; this is not.")
    size_bytes: int
    n_pages: int

    form_type: str
    fiscal_year: int
    fiscal_year_end: str
    toc_page: int
    page_offset_deltas: list[int]

    sections: list[SectionRange]
    verified_figures: dict[str, VerifiedFigure] = Field(default_factory=dict)
    verification_source: str
    notes: list[NoteRange] = Field(default_factory=list)
    statements: list[StatementRange] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_identity(self) -> "DocumentRecord":
        if not self.doc_id.endswith(f"FY{self.fiscal_year}"):
            raise ValueError(
                f"{self.doc_id} does not match reported fiscal year {self.fiscal_year}"
            )
        if len(self.sha256) != 64:
            raise ValueError(f"{self.doc_id}: sha256 must be 64 hex characters")
        return self