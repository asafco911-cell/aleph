"""Claims bound to their source text. Produced by an LLM, so validated here."""
from pydantic import BaseModel, Field


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


class ExtractedFacts(BaseModel):
    facts: list[Fact]

    def names(self) -> set[str]:
        return {fact.name for fact in self.facts}