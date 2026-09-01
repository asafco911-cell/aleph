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

from pydantic import BaseModel, Field, field_validator, model_validator

MIN_RATIONALE_CHARS = 20


class Observation(BaseModel):
    """One period's value for a derived quantity, traced to its fact."""
    period: str
    value: float
    fact_name: str
    unit: Optional[str] = Field(
        default=None,
        description="Unit the source fact declared, e.g. 'USD thousands'. "
                    "None for a value Python computed itself, such as a "
                    "growth rate or tax rate ratio, which has no scale of "
                    "its own to report.",
    )


class Override(BaseModel):
    """An analyst decision to exclude periods or fix a value outright.

    fixed_value carries the unit the FILING states, never one pre-converted
    by hand: a human converting thousands to millions in their head is
    exactly where a factor-of-1000 error enters. The engine converts it,
    using the same declared-unit machinery it uses for extracted facts.
    """
    excluded_periods: list[str] = Field(default_factory=list)
    fixed_value: Optional[float] = None
    unit: Optional[str] = Field(
        default=None,
        description="Unit fixed_value is stated in, as the filing states "
                    "it, e.g. 'USD thousands', 'percent'. Required whenever "
                    "fixed_value is set.",
    )
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

    @model_validator(mode="after")
    def unit_required_with_fixed_value(self) -> "Override":
        if self.fixed_value is not None and not self.unit:
            raise ValueError(
                "unit is required whenever fixed_value is set; state the "
                "unit the filing uses, not one converted by hand"
            )
        return self


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

class MarketAssumption(BaseModel):
    """An input that does not exist in the filing: rates, betas, prices.

    Market data cannot be cached against a document hash, because the hash is
    fixed while the value moves daily. Reproducibility therefore requires an
    explicit as_of date recorded alongside the value: a run from last month is
    only reconstructible if the observation date travels with the number.
    """
    name: str
    value: float
    unit: str
    as_of: str = Field(description="ISO date the value was observed.")
    source: str = Field(description="Where it came from, e.g. 'US Treasury 10Y'.")
    rationale: str