"""Claims bound to their source text. Produced by an LLM, so validated here."""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class FactSource(BaseModel):
    """Where a fact came from, precisely enough to re-open the page.

    The same metric name carries different definitions in different parts of a
    filing: an effective tax rate in MD&A is not necessarily the one in the tax
    note, and geographic revenue under ASC 280 need not match the operational
    split. A number without its origin is not interpretable.

    target_key records WHICH extraction target produced the fact. Region names
    are filer-specific - Uber reports United States, United Kingdom and all
    other countries; DoorDash reports United States and international - so
    downstream selection matches on the target rather than on region wording.
    """
    doc_id: str
    kind: Literal["statement", "note", "section"]
    ref: str = Field(description="Statement name, note number, or item id.")
    target_key: str = Field(
        default="",
        description="Extraction target that produced this fact, e.g. 'geography_n3'.",
    )
    pages: list[int]


class GroundedClaim(BaseModel):
    """A claim that carries its own evidence.

    Field order is load-bearing: the model generates the quote before the
    claim, so the evidence shapes the claim rather than the reverse.
    """
    evidence_quote: str = Field(
        description="The exact sentence copied verbatim from the source context."
    )
    source_chunk_id: str = Field(description="Id of the chunk the evidence came from, e.g. 'c29'.")
    claim: str = Field(description="The analytical claim, derived ONLY from the quote above.")


class GroundedAnswer(BaseModel):
    claims: list[GroundedClaim]
    summary: str = Field(description="Short answer, based only on the claims above.")


class Fact(BaseModel):
    """A single extracted data point. Must be quotable."""
    name: str = Field(description="Short label, e.g. 'Mobility revenue FY2025'.")
    value: float
    unit: str = Field(description="e.g. 'USD millions'")
    quote: str = Field(description="Exact sentence or table row copied VERBATIM from the source.")
    period: Optional[str] = Field(
        default=None,
        description="Fiscal year this value belongs to, e.g. 'FY2024'.",
    )
    source: Optional[FactSource] = Field(
        default=None,
        description="Provenance. Required for anything the extraction pipeline produces.",
    )


class ExtractedFacts(BaseModel):
    facts: list[Fact]

    def names(self) -> set[str]:
        return {fact.name for fact in self.facts}