import os
from typing import List, Literal
from dotenv import load_dotenv
from pydantic import BaseModel, Field
import instructor
from anthropic import Anthropic

load_dotenv()
client = instructor.from_anthropic(Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY")))


class PlanStep(BaseModel):
    """One step in an analysis plan."""
    number: int
    action: str = Field(description="What to do, concretely and verifiably.")
    purpose: str = Field(description="Why this step is needed for the final answer.")
    depends_on: List[int] = Field(default=[], description="Step numbers that must run first. Empty = can run in parallel.")


class Plan(BaseModel):
    question: str
    steps: List[PlanStep]

PLANNER_PROMPT = """You are a financial analysis planner.
Break the question into concrete, verifiable steps.

RULES:
- Every step must be a single verifiable action (retrieve X, compute Y), not a vague goal.
- Verification steps must come BEFORE the steps that draw conclusions from them.
- Mark independent steps with an empty depends_on so they can run in parallel.
- Do not skip data-quality checks (non-GAAP reconciliation, share count, one-time items)
  when the question depends on them.

QUESTION: {question}"""


def make_plan(question):
    return client.messages.create(
        model="claude-sonnet-4-5", max_tokens=1500,
        response_model=Plan,
        messages=[{"role": "user", "content": PLANNER_PROMPT.format(question=question)}],
    )

class Critique(BaseModel):
    """A single problem found in the plan."""
    category: Literal["metric_choice", "methodology", "completeness", "ordering"]
    severity: Literal["low", "medium", "high"]
    problem: str = Field(description="What is wrong, referencing specific step numbers.")
    fix: str = Field(description="Concrete correction.")


class CriticReport(BaseModel):
    critiques: List[Critique]
    verdict: Literal["approve", "revise"]


CRITIC_PROMPT = """You are a critical reviewer of financial analysis plans.
You did NOT write this plan. Your job is to find its flaws.

Check four things:
1. metric_choice  - are the chosen metrics right for this question?
                    (Owner Earnings vs net income, FCF vs EBITDA, maintenance vs growth capex)
2. methodology    - does the reasoning approach fit the question?
3. completeness   - what is MISSING? A plan can have every step correct and still be
                    wrong because of an absent step (e.g. share count and dilution).
4. ordering       - does any step draw a conclusion BEFORE the step that verifies it?

Be specific and reference step numbers. If the plan is sound, return an empty
critiques list and verdict "approve".

QUESTION: {question}

PLAN:
{plan}"""


def critique_plan(plan):
    plan_text = "\n".join(
        f"{s.number}. {s.action}  (purpose: {s.purpose}; depends_on: {s.depends_on})"
        for s in plan.steps
    )
    return client.messages.create(
        model="claude-sonnet-4-5", max_tokens=1500,
        response_model=CriticReport,
        messages=[{"role": "user", "content": CRITIC_PROMPT.format(
            question=plan.question, plan=plan_text)}],
    )

question = "Was Uber's 2025 profitability improvement high quality or one-time in nature?"

print("=" * 70)
print("PLANNING")
print("=" * 70)
plan = make_plan(question)
for s in plan.steps:
    dep = f" [after {s.depends_on}]" if s.depends_on else " [parallel]"
    print(f"{s.number}. {s.action}{dep}")
    print(f"   -> {s.purpose}")

print("\n" + "=" * 70)
print("CRITIQUE")
print("=" * 70)
report = critique_plan(plan)
print(f"VERDICT: {report.verdict.upper()}\n")
for c in report.critiques:
    print(f"[{c.severity.upper():<6}] {c.category}")
    print(f"  problem: {c.problem}")
    print(f"  fix:     {c.fix}\n")