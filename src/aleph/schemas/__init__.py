"""Canonical schema definitions. Import everything from here, never from a
chapter script, so that LangGraph and Python see exactly one type per name.
"""
from .agents import (
    Analysis,
    Claim,
    Computation,
    Critique,
    CriticReport,
    InferenceReview,
    InferenceVerdict,
    Plan,
    PlanStep,
)
from .documents import (
    SCHEMA_VERSION,
    DocumentRecord,
    NoteRange,
    SectionRange,
    StatementRange,
    VerifiedFigure,
)
from .evidence import ExtractedFacts, Fact, FactSource, GroundedAnswer, GroundedClaim
from .graph import Edge, GraphExtraction, Node
from .validation import ReferenceError_, check_references

__all__ = [
    "SCHEMA_VERSION",
    "DocumentRecord", "SectionRange", "NoteRange", "StatementRange", "VerifiedFigure",
    "GroundedClaim", "GroundedAnswer", "Fact", "FactSource", "ExtractedFacts",
    "Node", "Edge", "GraphExtraction",
    "PlanStep", "Plan", "Critique", "CriticReport",
    "Computation", "Claim", "Analysis", "InferenceVerdict", "InferenceReview",
    "check_references", "ReferenceError_",
]