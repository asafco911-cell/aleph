"""Assumption ranges and the analyst decisions that unblock them.

Python derives ranges from extracted facts; it never picks one. When dispersion
makes a range meaningless, derivation is BLOCKED rather than smoothed over: a
silently averaged assumption produces a valuation that looks reasonable and is
not.

An analyst override is DATA, not a gesture. It is persisted, versioned, and
requires a written rationale, because an exclusion without a recorded reason is
indistinguishable from fitting the inputs to a desired answer - and because an
interactive choice that is not stored destroys reproducibility.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

MIN_RATIONALE_CHARS = 20


class Observation(BaseModel):
    """One period's value for a derived quantity, traced to its fact."""
    period: str
    value: float
    fact_name: str


class Override(BaseModel):
    """An analyst decision to exclude periods or fix a value outright."""
    excluded_periods: list[str] = Field(default_factory=list)
    fixed_value: Optional[float] = None
    rationale: str
    decided_by: str
    decided_at: str = Field(description="ISO date, e.g. '2026-08-27'.")

    @field_validator("rationale")
    @classmethod
    def rationale_must_be_substantive(cls, value: str) -> str:
        if len(value.strip()) < MIN_RATIONALE_CHARS:
            raise ValueError(
                f"rationale must be at least {MIN_RATIONALE_CHARS} characters; "
                "an exclusion without a stated reason is not a judgement"
            )
        return value


class AssumptionRange(BaseModel):
    """A derived input to valuation, with its evidence and its status."""
    name: str
    unit: str
    status: Literal["derived", "overridden", "blocked"]

    low: Optional[float] = None
    base: Optional[float] = None
    high: Optional[float] = None

    observations: list[Observation]
    excluded: list[Observation] = Field(default_factory=list)
    method: str = Field(description="How low/base/high were computed.")
    rationale: str = Field(description="Why this range is defensible, or why it is blocked.")
    doc_ids: list[str] = Field(default_factory=list)