# Aleph · Chapter 8 Reference — Advanced Agents: from ReAct to Planning

> Fixed reference format. One per chapter. English. Read in 5 minutes, use forever.

---

## TL;DR

ReAct is greedy search in action space: at every turn the model sees the whole (increasingly polluted) history and picks the single locally-best next step. It has no plan, no memory of intent, no way back, and — worst — the entity that produces the answer is also the entity that decides it's good enough. Every fix in this chapter comes from one idea: **separate roles instead of cramming them into one entity with one context.** Planning separates from execution, criticism separates from production, and each role gets a clean context and a narrow mandate. The strongest critic turns out to be mostly *code*, not a model.

---

## Core concepts

**What ReAct actually does.** Thought → Action → Observation, looping. Each turn the model receives the full history and chooses one step that looks best *right now*. No lookahead, no plan. This is structurally identical to HNSW's greedy walk (Ch3) — and inherits the same weakness: **it gets stuck in local minima.** It can take five individually reasonable steps into a dead end, because reaching the real answer required a step that looked *unhelpful* at the time. (Analogy: a tourist with no map asking "which way now?" at every corner — every answer locally correct, twenty corners later, wrong neighbourhood.)

*Worked example:* "Was Uber's 2025 profitability improvement high quality?" → ReAct finds Adjusted EBITDA ($8.7B, +$2.2B), sees "improved across all segments," concludes "high quality." But Adjusted EBITDA is non-GAAP and excludes legal/regulatory reserve changes and asset-sale gains. Answering properly required *climbing* — leaving the attractive EBITDA path for the GAAP reconciliation. Greedy never climbs.

**The five failure modes:**
1. **No global plan** — an 8-step question loses direction mid-way.
2. **Context pollution** — history accumulates failed searches, abandoned attempts, errors. The harder the task, the dirtier the context, exactly when clarity matters most.
3. **No recovery** — if step 3 reveals step 1's data was wrong, the loop is one-directional and builds on rotten foundations.
4. **No parallelism** — independent sub-tasks run serially.
5. **No self-criticism** — the producer is also the judge, in the same polluted context. Ch5/Ch6 established that *verifying is easier than generating*; ReAct throws that away.

**Failures 3 and 5 are linked:** missing recovery is the *symptom*, missing criticism is the *cause*. Without a critic nobody knows recovery is needed, so the agent proceeds confidently — producing exactly the confident-and-wrong answer identified in Ch5 as the most dangerous kind.

**Plan-and-execute.** Generate a full plan first, then execute it. Four gains, mapping to failures 1–4: a **global view** (written before context got dirty), a **clean context per step**, **parallelism** (independent steps marked), and — most important for Aleph — **the plan is reviewable before execution**. You can't audit a ReAct loop mid-flight; you can read a plan and say "you forgot share count." That's human-in-the-loop. The cost: a plan written in advance can turn out wrong, so add **re-planning** — after each step, check the plan still holds. That's the recovery mechanism ReAct lacks.

**What to check in a plan (four critic criteria):**

| Criterion | Question | Failure it catches |
|---|---|---|
| **metric_choice** | Right metrics for this question? (Owner Earnings vs net income, FCF vs EBITDA, maintenance vs growth capex) | Correct conclusion on the wrong measure |
| **methodology** | Does the approach fit the framework? | Shallow or irrelevant analysis |
| **completeness** | What's *missing*? | An error with no step to point at |
| **ordering** | Does any step conclude before the step that verifies it? | Post-hoc justification (Ch6 citation-first, at plan level) |

Completeness is the hardest — a 16-step plan can have every step correct and still be wrong for lack of a step (e.g. share dilution: total profit rises while per-share erodes).

**Role separation is the whole mechanism.** The critic is not a smarter model — it's the *same* model with a different role and a clean context. The prompt line **"You did NOT write this plan"** does the work: it receives the plan as external text, with an explicit mandate to find flaws, without seeing the reasoning that produced it. Also: the **planner revises, not the critic**. If the critic edits, it becomes a co-author and can no longer judge its own output objectively — ReAct's flaw re-entering through the back door.

**Stopping conditions (two, not one).**
1. **Quality** — keep iterating while `high`/`medium` issues remain; stop when only `low` (cosmetic) ones are left.
2. **Hard ceiling** — max N rounds regardless. Insurance against an unresolvable demand looping forever.
Hitting the ceiling with open issues is the *correct* trigger for human escalation: the system reports that it could not converge, instead of proceeding confidently. **A good autonomous system isn't one that always succeeds — it's one that knows when it's failing and says so.**

**`critic drift`** — a critic given a better and better plan doesn't stop; it raises the bar. A 24-step plan can always become 30. "Is this thorough enough?" has **no upper bound**. Mitigation: constrain the mandate (review only against available data), or accept when the issue count stops falling between rounds.

**Why drift shrinks on final answers — and the hybrid critic.** "Does the quote exist?" has a *floor*: yes or no. Factual checks terminate; quality checks don't. But not every claim is quotable — "grew 18.3%" appears nowhere; it's *derived*. So split verification by claim type:

| Claim type | Example | How verified | By |
|---|---|---|---|
| **Fact** | "Revenue was 29,670" | Is the quote in the source? | **Python** (`in`) |
| **Computation** | "grew 18.3%" | Re-run the arithmetic | **Python** |
| **Inference** | "the growth is high quality" | Does it follow from the facts? | **LLM** |

The first two need no LLM at all — deterministic, instant, zero drift. Only inference goes to the model, with an explicit "facts and arithmetic have ALREADY been verified by code — do not re-check them." **The best critic is mostly code.** This is the chapter's version of "LLM interprets, Python computes" (Ch7), and it is exactly what the syllabus means by *deterministic tools > free search*.

**The analyst must not compute.** It returns an *expression* (`({Mobility revenue 2025} - {Mobility revenue 2024})`), never a number. Python substitutes and evaluates. The "grew 30% instead of 19.6%" failure becomes architecturally impossible.

**LangGraph — why, after hand-rolling the loop.** The manual `refine()` worked but had three problems: (1) flow logic embedded in `if`/`for`, tangled with agent logic; (2) data passed as arguments — unmanageable at 5 agents × 10 fields; (3) "escalate to human" was a `print()` — the system didn't actually *pause*. LangGraph fixes all three: flow becomes an **explicit graph** (nodes and edges — the Ch7 structure again), data lives in a **shared state**, and **checkpointing** makes real pause/resume possible via `thread_id`.

---

## Code patterns learned

Analyst returns expressions, Python evaluates:
```python
class Computation(BaseModel):
    label: str
    expression: str      # "({Mobility revenue 2025} - {Mobility revenue 2024}) / {...} * 100"

for name, value in lookup.items():
    expr = expr.replace("{" + name + "}", str(value))
if "{" in expr:                                    # unresolved -> the model invented a fact name
    ...                                            # hallucination caught in code
value = eval(expr, {"__builtins__": {}}, {})       # arithmetic only, no builtins
```

Deterministic critic checks:
```python
if " ".join(fact.quote.split()) not in " ".join(source_text.split()):   # verbatim check
    issues.append(...)
if fact_name not in {f.name for f in facts.facts}:                       # dangling reference
    issues.append(...)
```

LangGraph wiring:
```python
class TeamState(TypedDict):          # shared state; nodes return only what they change
    question: str; facts: Optional[object]; revision_count: int; ...

workflow.add_conditional_edges("critic", route_after_critic,
    {"write": "write", "revise": "revise", "escalate": "escalate"})
workflow.add_edge("revise", "compute")     # revised analysis must be recomputed
app = workflow.compile(checkpointer=MemorySaver())
app.invoke(state, config={"configurable": {"thread_id": "uber-analysis-1"}})
```

Order the critic's checks cheapest-and-surest first: if code checks fail, don't pay for LLM inference review at all.

---

## Evidence from the experiments

**Plan + critique (16-step plan):** the planner did include non-GAAP reconciliation and one-time-item steps on its own. The critic returned `REVISE` with 5 issues, including **[HIGH] completeness: the plan completely omits share dilution and share count** — a flaw with no wrong step to point at. It also flagged metric_choice (FCF and maintenance-vs-growth capex missing) and methodology (external macro tailwinds vs internal efficiency have different sustainability profiles).

**Refinement loop:** `high` went 1 → 0 after one round and stayed there — the mechanism worked where it mattered most. But `medium` stuck at 3 across rounds 2 and 3 while the plan grew 19 → 24 steps: **critic drift**, demanding depth the source couldn't supply. The hard ceiling fired, and the system escalated with three focused open questions instead of looping forever.

**Agent team:** extractor → analyst → compute → critic → write. The analyst emitted expressions only. Python produced Mobility +4,583 / Delivery +3,498 / Freight −42 — **identical to the Ch7 knowledge-graph result and to the manually verified golden-dataset figure.** Three independent paths agreeing. Code checks passed (every quote verbatim in page 58); the LLM reviewed only inference and correctly decomposed a two-part claim. Notably the extractor also captured rounded prose figures ("increase ~$5 billion") and the analyst **ignored them**, computing from precise source values instead.

**LangGraph run:** clean pass, `revisions: 0`, routed critic → write, `next node: (finished)`. Final answer carried each claim with its computation attached — a full chain from page to conclusion.

---

## Gotchas / failure patterns

- **Module-level code re-runs on import.** Importing `03_agent_team` executed its demo block again (duplicate output, wasted API calls). Wrap run code in `if __name__ == "__main__":`.
- **`Deserializing unregistered type ... from checkpoint`** — LangGraph warning when checkpointing Pydantic models defined in a script. Harmless with `MemorySaver`, but a real issue with a persistent checkpointer. Fix: move schemas into a shared `schemas.py`. *(Open issue.)*
- **Module names starting with a digit** can't be imported normally — needs `import_module`. Prefer non-numeric module names for anything reusable.
- **`eval` on model output** must be restricted (`{"__builtins__": {}}`). Fine for learning; a real system uses a dedicated expression parser.
- **Don't let the critic edit.** The moment it does, it can't judge objectively next round.

---

## What this means for Aleph

Aleph now has an agent team with genuine role separation and a hybrid critic whose factual and arithmetic checks are pure code, plus a state machine that can pause, route conditionally, and escalate to a human when it fails to converge. Next steps: swap `MemorySaver` for a persistent checkpointer (real cross-session resume), give the extractor the Ch4 hybrid retrieval and Ch7 graph as tools instead of a single page, and constrain the critic's mandate to available data to reduce drift. The standing rule holds throughout: any number surfaced ran through Python, from a verbatim quote.

---

## 60-second self-test

1. Why is ReAct "greedy search in action space," and what's the failure that follows?
2. Which two ReAct failure modes are cause and symptom of each other?
3. What does plan-and-execute buy that matters most for Aleph, and why is that impossible in ReAct?
4. What is `critic drift`, and why does it shrink when reviewing answers instead of plans?
5. Split claim verification by type — which parts need no LLM, and why does that matter?

<details>
<summary>Answers</summary>

1. It picks the locally-best next step with no lookahead or plan, so it gets stuck in local minima — a chain of reasonable steps ending somewhere wrong, because the right path required a step that looked unhelpful at the time.
2. Missing self-criticism (cause) and missing recovery (symptom) — without a critic, nothing detects that recovery is needed.
3. The plan is reviewable *before* execution, so a human can catch a missing step. A ReAct loop can't be audited mid-flight — there's no artifact to review.
4. A critic given a better plan raises the bar rather than approving — "thorough enough?" has no upper bound. On answers, checks like "does this quote exist?" have a definite yes/no floor, so they terminate.
5. Facts (substring check) and computations (re-run the arithmetic) are pure Python — deterministic, instant, no drift. Only inference needs LLM judgment. It matters because it shrinks the model's mandate to the one place judgment is genuinely required.
</details>
