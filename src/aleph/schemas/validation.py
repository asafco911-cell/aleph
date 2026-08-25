"""Referential integrity across schema families.

A claim that names a fact which does not exist looks perfectly grounded and is
not. Pydantic validates shape, not resolution, so this runs as a separate gate.
"""
import re

from .agents import Analysis
from .evidence import ExtractedFacts

RE_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")


class ReferenceError_(Exception):
    """Raised when a claim or computation names something that does not exist."""


def check_references(facts: ExtractedFacts, analysis: Analysis) -> None:
    """Raise if any claim or computation points at a name that is not defined."""
    fact_names = facts.names()
    computation_labels = {c.label for c in analysis.computations}

    for computation in analysis.computations:
        for placeholder in RE_PLACEHOLDER.findall(computation.expression):
            if placeholder not in fact_names:
                raise ReferenceError_(
                    f"Computation '{computation.label}' references unknown fact "
                    f"'{placeholder}'. Known facts: {sorted(fact_names)}"
                )

    for index, claim in enumerate(analysis.claims):
        for name in claim.supporting_facts:
            if name not in fact_names:
                raise ReferenceError_(
                    f"Claim {index} references unknown fact '{name}'. "
                    f"Known facts: {sorted(fact_names)}"
                )
        for label in claim.supporting_computations:
            if label not in computation_labels:
                raise ReferenceError_(
                    f"Claim {index} references unknown computation '{label}'. "
                    f"Known computations: {sorted(computation_labels)}"
                )