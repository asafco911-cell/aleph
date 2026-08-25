"""Planning, critique and analysis. Canonical definitions.

These were previously duplicated byte-for-byte across two chapter scripts.
Two classes with the same name in different modules are distinct types to
Python, which is what produced LangGraph's unregistered-type warnings.
"""
from typing import Literal

from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    number: int
    action: str = Field(description="What to do, concretely and verifiably.")
    purpose: str = Field(description="Why this step is needed for the final answer.")
    depends_on: list[int] = Field(
        default_factory=list,
        description="Step numbers that must run first. Empty means it can run in parallel.",
    )


class Plan(BaseModel):
    question: str
    steps: list[PlanStep]


class Critique(BaseModel):
    category: Literal["metric_choice", "methodology", "completeness", "ordering"]
    severity: Literal["low", "medium", "high"]
    problem: str = Field(description="What is wrong, referencing specific step numbers.")
    fix: str = Field(description="Concrete correction.")


class CriticReport(BaseModel):
    critiques: list[Critique]
    verdict: Literal["approve", "revise"]


class Computation(BaseModel):
    """A calculation the Analyst requests. It never computes anything itself."""
    label: str = Field(description="What this computes, e.g. 'Mobility revenue growth pct'.")
    expression: str = Field(
        description="Python expression using ONLY fact names in braces, e.g. "
                    "'({Mobility revenue FY2025} - {Mobility revenue FY2024}) "
                    "/ {Mobility revenue FY2024} * 100'"
    )


class Claim(BaseModel):
    """An analytical claim referencing evidence BY NAME.

    Unlike GroundedClaim, this does not carry its own quote: it points into a
    shared fact register. Pydantic can confirm these are strings but cannot
    confirm they resolve, so referential integrity is checked separately by
    aleph.schemas.validation.check_references.
    """
    supporting_facts: list[str] = Field(description="Names of facts this claim rests on.")
    supporting_computations: list[str] = Field(
        default_factory=list, description="Labels of computations used."
    )
    claim: str = Field(description="The claim, derived ONLY from the facts and computations above.")


class Analysis(BaseModel):
    computations: list[Computation]
    claims: list[Claim]


class InferenceVerdict(BaseModel):
    claim_index: int
    sound: bool
    reason: str


class InferenceReview(BaseModel):
    verdicts: list[InferenceVerdict]