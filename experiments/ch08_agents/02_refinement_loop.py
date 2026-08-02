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

REVISER_PROMPT = """You are the planner. A reviewer found problems with your plan.
Produce a REVISED plan that addresses every critique.

RULES:
- Keep what worked. Do not rewrite from scratch.
- Address each critique explicitly by adding, reordering, or replacing steps.
- Renumber steps sequentially and keep depends_on consistent.

QUESTION: {question}

YOUR CURRENT PLAN:
{plan}

REVIEWER CRITIQUES:
{critiques}"""


def revise_plan(plan, report):
    plan_text = "\n".join(
        f"{s.number}. {s.action}  (depends_on: {s.depends_on})" for s in plan.steps
    )
    crit_text = "\n".join(
        f"- [{c.severity}] {c.category}: {c.problem}\n  FIX: {c.fix}" for c in report.critiques
    )
    return client.messages.create(
        model="claude-sonnet-4-5", max_tokens=2500,
        response_model=Plan,
        messages=[{"role": "user", "content": REVISER_PROMPT.format(
            question=plan.question, plan=plan_text, critiques=crit_text)}],
    )

MAX_ROUNDS = 3


def blocking_issues(report):
    """Your stopping rule: only high/medium severity issues block approval."""
    return [c for c in report.critiques if c.severity in ("high", "medium")]


def refine(question, max_rounds=MAX_ROUNDS):
    plan = make_plan(question)
    history = []

    for round_num in range(1, max_rounds + 1):
        report = critique_plan(plan)
        blockers = blocking_issues(report)
        history.append({
            "round": round_num,
            "steps": len(plan.steps),
            "total": len(report.critiques),
            "blockers": len(blockers),
            "by_severity": {s: sum(1 for c in report.critiques if c.severity == s)
                            for s in ("high", "medium", "low")},
        })

        print(f"\n--- Round {round_num} ---")
        print(f"  plan: {len(plan.steps)} steps")
        print(f"  critiques: {history[-1]['by_severity']}  (blocking: {len(blockers)})")

        # Stop condition 1 (quality): nothing substantive left, only cosmetic
        if not blockers:
            print("  -> CONVERGED: only cosmetic issues remain.")
            return plan, report, history, "converged"

        # Otherwise the PLANNER revises (not the critic)
        if round_num < max_rounds:
            print("  -> revising...")
            plan = revise_plan(plan, report)

    # Stop condition 2 (hard ceiling): escalate to a human
    print("  -> CEILING REACHED: unresolved issues, escalating to human review.")
    return plan, report, history, "escalated"


question = "Was Uber's 2025 profitability improvement high quality or one-time in nature?"
final_plan, final_report, history, outcome = refine(question)

print("\n" + "=" * 70)
print(f"OUTCOME: {outcome.upper()}")
print("=" * 70)
for h in history:
    print(f"  round {h['round']}: {h['steps']} steps, "
          f"{h['total']} critiques ({h['blockers']} blocking)")

if outcome == "escalated":
    print("\nHUMAN REVIEW NEEDED - unresolved:")
    for c in blocking_issues(final_report):
        print(f"  [{c.severity}] {c.problem[:150]}")
        