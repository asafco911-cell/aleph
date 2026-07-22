import os
from typing import List
from dotenv import load_dotenv
from pydantic import BaseModel, Field
import instructor
from anthropic import Anthropic

load_dotenv()
# Wrap the Anthropic client so it enforces Pydantic schemas
client = instructor.from_anthropic(Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY")))


class GroundedClaim(BaseModel):
    """A single claim that MUST cite its evidence before stating the claim."""
    # Field order matters: evidence is generated BEFORE the claim
    evidence_quote: str = Field(
        description="The exact sentence copied verbatim from the source context that supports the claim."
    )
    source_chunk_id: str = Field(
        description="The id of the chunk the evidence was copied from, e.g. 'c29'."
    )
    claim: str = Field(
        description="The analytical claim, derived ONLY from the evidence quote above."
    )


class GroundedAnswer(BaseModel):
    """The full answer: a list of grounded claims, then a summary."""
    claims: List[GroundedClaim]
    summary: str = Field(description="A short answer to the question, based only on the claims above.")

# Simulated retrieved chunks (in Aleph these come from the Ch4 pipeline)
chunks = {
    "c29": "Freight Segment. For the year ended December 31, 2025 compared to the same period in 2024, "
           "Freight revenue decreased $42 million, or 1%, and Freight Adjusted EBITDA improved $41 million, or 55%.",
    "c21": "(In millions) Q1 2024 Q2 2024 Q3 2024 Q4 2024 Q1 2025 Q2 2025 Q3 2025 Q4 2025 "
           "Mobility $ 18,670 $ 20,554 $ 21,002 $ 22,798 $ 21,182 $ 23,762 $ 25,111 $ 27,442",
}

question = "What happened to Uber Freight revenue and profitability?"

context_text = "\n\n".join([f"[{cid}]: {text}" for cid, text in chunks.items()])

result = client.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=1000,
    response_model=GroundedAnswer,          # <-- this enforces the schema
    messages=[{
        "role": "user",
        "content": f"""Answer the question using ONLY the context below.
For each claim, first copy the exact supporting sentence, then state the claim.

CONTEXT:
{context_text}

QUESTION: {question}"""
    }],
)

print(f"QUESTION: {question}\n")
for i, c in enumerate(result.claims, 1):
    print(f"--- Claim {i} ---")
    print(f"  Evidence [{c.source_chunk_id}]: {c.evidence_quote}")
    print(f"  Claim: {c.claim}\n")
print(f"SUMMARY: {result.summary}")