"""Knowledge graph primitives. An LLM interprets; Python computes."""
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class Node(BaseModel):
    """An entity. Sharing a node means IDENTITY, not similarity."""
    id: str = Field(description="Canonical name, e.g. 'Uber', 'Freight', 'Adjusted EBITDA'.")
    type: str = Field(
        description="One of: Company, Segment, Metric, Risk, Event, Period. "
                    "Documentation, not enforcement - a plain str, no validator "
                    "restricts it. Consumed only by experiments/ch07 and ch08, "
                    "never by the live valuation pipeline."
    )


class Edge(BaseModel):
    """A typed relationship. Numbers live here as properties, never as nodes.

    Period is stored as an explicit interval. A single free-text field mixed
    points ("2024") with ranges ("2024 to 2025"), so a query filtering on
    period == "2025" silently missed range edges. An interval makes containment
    a comparison instead of a string match: start <= target <= end.
    A point in time has start == end.
    """
    source: str
    relation: str = Field(
        description="Uppercase relation type, e.g. HAS_SEGMENT, REPORTED. "
                    "Documentation, not enforcement - nothing checks case. "
                    "Consumed only by experiments/ch07 and ch08, never by the "
                    "live valuation pipeline."
    )
    target: str

    period_start: Optional[str] = Field(default=None, description="e.g. 'FY2024'")
    period_end: Optional[str] = Field(default=None, description="e.g. 'FY2025'")

    value: Optional[float] = None
    unit: Optional[str] = Field(default=None, description="e.g. 'USD millions', 'percent'")

    @model_validator(mode="after")
    def check_period(self) -> "Edge":
        if (self.period_start is None) != (self.period_end is None):
            raise ValueError(
                f"{self.source}-{self.relation}->{self.target}: period_start and "
                "period_end must both be set or both be None"
            )
        if self.period_start and self.period_end and self.period_start > self.period_end:
            raise ValueError(f"period_start {self.period_start} is after {self.period_end}")
        return self

    def covers(self, period: str) -> bool:
        if self.period_start is None:
            return False
        return self.period_start <= period <= self.period_end


class GraphExtraction(BaseModel):
    nodes: list[Node]
    edges: list[Edge]