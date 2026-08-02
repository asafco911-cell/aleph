import os
import json
from typing import List, Literal, Optional
from dotenv import load_dotenv
from pydantic import BaseModel, Field
import instructor
from anthropic import Anthropic

load_dotenv()
client = instructor.from_anthropic(Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY")))


class Fact(BaseModel):
    """A single extracted data point. Must be quotable."""
    name: str = Field(description="Short label, e.g. 'Mobility revenue FY2025'.")
    value: float
    unit: str = Field(description="e.g. 'USD millions'")
    quote: str = Field(description="Exact sentence or table row copied VERBATIM from the source.")


class ExtractedFacts(BaseModel):
    facts: List[Fact]


class Computation(BaseModel):
    """A calculation the Analyst wants performed. It does NOT compute it itself."""
    label: str = Field(description="What this computes, e.g. 'Mobility revenue growth pct'.")
    expression: str = Field(
        description="Python expression using ONLY fact names in braces, e.g. "
                    "'({Mobility revenue FY2025} - {Mobility revenue FY2024}) "
                    "/ {Mobility revenue FY2024} * 100'"
    )


class Claim(BaseModel):
    """An analytical claim. Evidence comes first (Ch6 citation-first)."""
    supporting_facts: List[str] = Field(description="Names of facts this claim rests on.")
    supporting_computations: List[str] = Field(default=[], description="Labels of computations used.")
    claim: str = Field(description="The claim, derived ONLY from the facts and computations above.")


class Analysis(BaseModel):
    computations: List[Computation]
    claims: List[Claim]

def extract_facts(question, source_text):
    """Agent 1: pull quotable data points from the filing."""
    prompt = f"""Extract the data points needed to answer the question.

RULES:
- Every fact must include a VERBATIM quote from the source. Never paraphrase.
- Only extract what is actually present. Do not infer or compute anything.
- Use precise names that include the period, e.g. 'Freight revenue FY2024'.

QUESTION: {question}

SOURCE:
{source_text}"""
    return client.messages.create(
        model="claude-sonnet-4-5", max_tokens=2000,
        response_model=ExtractedFacts,
        messages=[{"role": "user", "content": prompt}],
    )


def analyze(question, facts):
    """Agent 2: decide what to compute and what to claim. Computes NOTHING itself."""
    facts_text = "\n".join(f"- {f.name} = {f.value} {f.unit}" for f in facts.facts)
    prompt = f"""Analyze the question using ONLY the facts below.

RULES:
- Do NOT compute any number yourself. Express every calculation as a Python
  expression referencing fact names in braces. It will be executed for you.
- Every claim must list the facts and computations it rests on.
- Do not claim anything the facts cannot support.

QUESTION: {question}

AVAILABLE FACTS:
{facts_text}"""
    return client.messages.create(
        model="claude-sonnet-4-5", max_tokens=2000,
        response_model=Analysis,
        messages=[{"role": "user", "content": prompt}],
    )

def run_computations(analysis, facts):
    """Deterministic: substitute fact values into expressions and evaluate."""
    lookup = {f.name: f.value for f in facts.facts}
    results = {}
    for comp in analysis.computations:
        expr = comp.expression
        missing = []
        # Substitute {fact name} with its numeric value
        for name, value in lookup.items():
            expr = expr.replace("{" + name + "}", str(value))
        if "{" in expr:                      # an unresolved reference remains
            missing = [p.split("}")[0] for p in expr.split("{")[1:]]
            results[comp.label] = {"error": f"unknown facts: {missing}"}
            continue
        try:
            # Restricted eval: arithmetic only, no builtins available
            results[comp.label] = {"value": eval(expr, {"__builtins__": {}}, {}),
                                   "expression": comp.expression}
        except Exception as e:
            results[comp.label] = {"error": str(e)}
    return results

class InferenceVerdict(BaseModel):
    claim_index: int
    sound: bool
    reason: str


class InferenceReview(BaseModel):
    verdicts: List[InferenceVerdict]


def critic_code_checks(facts, analysis, comp_results, source_text):
    """Deterministic checks - no LLM involved."""
    issues = []

    # Check 1: every quote must literally exist in the source
    normalized_source = " ".join(source_text.split())
    for f in facts.facts:
        normalized_quote = " ".join(f.quote.split())
        if normalized_quote not in normalized_source:
            issues.append(f"[QUOTE] Fact '{f.name}' quote not found verbatim in source.")

    # Check 2: every computation must have executed successfully
    for label, res in comp_results.items():
        if "error" in res:
            issues.append(f"[COMPUTE] '{label}' failed: {res['error']}")

    # Check 3: every claim must reference facts and computations that exist
    fact_names = {f.name for f in facts.facts}
    comp_labels = set(comp_results.keys())
    for i, c in enumerate(analysis.claims):
        for fname in c.supporting_facts:
            if fname not in fact_names:
                issues.append(f"[REF] Claim {i} cites unknown fact '{fname}'.")
        for clabel in c.supporting_computations:
            if clabel not in comp_labels:
                issues.append(f"[REF] Claim {i} cites unknown computation '{clabel}'.")
    return issues


def critic_inference_review(analysis, comp_results):
    """LLM judgment - ONLY for whether the reasoning holds."""
    claims_text = ""
    for i, c in enumerate(analysis.claims):
        comps = "; ".join(
            f"{lbl}={comp_results.get(lbl, {}).get('value', 'n/a')}"
            for lbl in c.supporting_computations
        )
        claims_text += f"\nClaim {i}: {c.claim}\n  facts: {c.supporting_facts}\n  computed: {comps}\n"

    prompt = f"""You are reviewing analytical claims. You did NOT write them.
Facts and arithmetic have ALREADY been verified by code - do not re-check them.

Judge ONLY this: does each claim follow logically from its stated facts and
computed values? Flag overstatement, unsupported causal language, and leaps.

CLAIMS:
{claims_text}"""
    return client.messages.create(
        model="claude-sonnet-4-5", max_tokens=1500,
        response_model=InferenceReview,
        messages=[{"role": "user", "content": prompt}],
    )

from pypdf import PdfReader

reader = PdfReader("data/uber_10k.pdf")
source_text = reader.pages[58].extract_text()
question = "Which Uber segment contributed most to revenue growth in 2025?"

print("=" * 70, "\n[1] EXTRACTOR\n", "=" * 70, sep="")
facts = extract_facts(question, source_text)
for f in facts.facts:
    print(f"  {f.name} = {f.value:,.0f} {f.unit}")

print("\n" + "=" * 70, "\n[2] ANALYST\n", "=" * 70, sep="")
analysis = analyze(question, facts)
for c in analysis.computations:
    print(f"  {c.label}: {c.expression}")

print("\n" + "=" * 70, "\n[3] COMPUTE (python)\n", "=" * 70, sep="")
comp_results = run_computations(analysis, facts)
for label, res in comp_results.items():
    print(f"  {label} = {res.get('value', res.get('error'))}")

print("\n" + "=" * 70, "\n[4] CRITIC - code checks\n", "=" * 70, sep="")
code_issues = critic_code_checks(facts, analysis, comp_results, source_text)
print("  PASS - all quotes and references verified" if not code_issues
      else "\n".join(f"  {i}" for i in code_issues))

print("\n" + "=" * 70, "\n[5] CRITIC - inference review (LLM)\n", "=" * 70, sep="")
review = critic_inference_review(analysis, comp_results)
for v in review.verdicts:
    mark = "OK  " if v.sound else "FLAG"
    print(f"  [{mark}] Claim {v.claim_index}: {v.reason[:120]}")

print("\n" + "=" * 70, "\n[6] CLAIMS\n", "=" * 70, sep="")
for i, c in enumerate(analysis.claims):
    print(f"  {i}. {c.claim}")