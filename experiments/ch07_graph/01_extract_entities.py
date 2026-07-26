import os
import json
from typing import List, Optional
from dotenv import load_dotenv
from pydantic import BaseModel, Field
import instructor
from anthropic import Anthropic
from pypdf import PdfReader

load_dotenv()
client = instructor.from_anthropic(Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY")))


class Node(BaseModel):
    """An entity in the knowledge graph."""
    id: str = Field(description="Canonical name, e.g. 'Uber', 'Freight', 'Adjusted EBITDA'.")
    type: str = Field(description="One of: Company, Segment, Metric, Risk, Event, Period.")


class Edge(BaseModel):
    """A typed relationship between two nodes. Numbers live here as properties."""
    source: str = Field(description="id of the source node")
    relation: str = Field(description="Uppercase relation type, e.g. HAS_SEGMENT, REPORTED, FACES_RISK.")
    target: str = Field(description="id of the target node")
    period: Optional[str] = Field(default=None, description="e.g. 'FY2025'")
    value: Optional[float] = Field(default=None, description="Numeric value of the measurement")
    unit: Optional[str] = Field(default=None, description="e.g. 'USD millions', 'percent'")


class GraphExtraction(BaseModel):
    nodes: List[Node]
    edges: List[Edge]

EXTRACTION_PROMPT = """Extract a knowledge graph from the financial text below.

RULES:
- Nodes are things other entities connect to: companies, segments, metrics, risks, events, periods.
- NEVER create a node for a number or an amount. Numbers belong on the edge as `value`.
- Metrics (Revenue, Adjusted EBITDA) are shared nodes reused across segments and companies.
- Encode the reporting level by the edge source: (Uber)->(Revenue) is company level,
  (Mobility)->(Revenue) is segment level. Do not rename the metric per level.
- Use relation types: HAS_SEGMENT, REPORTED, FACES_RISK, REALIZED_BY, OCCURRED_IN.

TEXT:
{text}"""


def extract_graph(text):
    """Extract nodes and edges from a chunk of filing text."""
    return client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=2000,
        response_model=GraphExtraction,
        messages=[{"role": "user", "content": EXTRACTION_PROMPT.format(text=text)}],
    )


# Test on the verified segment revenue table (page 58)
reader = PdfReader("data/uber_10k.pdf")
page_text = reader.pages[58].extract_text()

print("Extracting graph from page 58...\n")
result = extract_graph(page_text[:3000])

print(f"NODES ({len(result.nodes)}):")
for n in result.nodes:
    print(f"  [{n.type:<8}] {n.id}")

print(f"\nEDGES ({len(result.edges)}):")
for e in result.edges:
    props = []
    if e.period:
        props.append(e.period)
    if e.value is not None:
        props.append(f"{e.value} {e.unit or ''}".strip())
    prop_str = f"  {{{', '.join(props)}}}" if props else ""
    print(f"  ({e.source}) -[{e.relation}]-> ({e.target}){prop_str}")

# Save for the next step
with open("experiments/ch07_graph/extracted_page58.json", "w", encoding="utf-8") as f:
    json.dump(result.model_dump(), f, indent=2)
print("\nSaved to extracted_page58.json")