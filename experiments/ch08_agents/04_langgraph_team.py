import os
from typing import List, Optional, TypedDict
from dotenv import load_dotenv
from pypdf import PdfReader
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

# Reuse the agents built in 03_agent_team.py
from importlib import import_module
import sys
sys.path.append("experiments/ch08_agents")

load_dotenv()


class TeamState(TypedDict):
    """Shared state passed between all nodes. Every agent reads and writes here."""
    question: str
    source_text: str
    facts: Optional[object]           # ExtractedFacts
    analysis: Optional[object]        # Analysis
    comp_results: Optional[dict]
    code_issues: List[str]
    inference_flags: List[str]
    revision_count: int
    final_answer: Optional[str]

# Import the agent functions from the previous script
team = import_module("03_agent_team")


def node_extract(state: TeamState) -> dict:
    """Node 1: extract quotable facts."""
    print("  [extract] pulling facts...")
    facts = team.extract_facts(state["question"], state["source_text"])
    return {"facts": facts}


def node_analyze(state: TeamState) -> dict:
    """Node 2: decide computations and claims."""
    print("  [analyze] building claims...")
    analysis = team.analyze(state["question"], state["facts"])
    return {"analysis": analysis}


def node_compute(state: TeamState) -> dict:
    """Node 3: deterministic Python arithmetic. No LLM."""
    print("  [compute] running python...")
    results = team.run_computations(state["analysis"], state["facts"])
    return {"comp_results": results}


def node_critic(state: TeamState) -> dict:
    """Node 4: hybrid critic - code checks first, LLM only for inference."""
    print("  [critic] verifying...")
    code_issues = team.critic_code_checks(
        state["facts"], state["analysis"], state["comp_results"], state["source_text"]
    )
    flags = []
    if not code_issues:                       # only judge inference if facts are sound
        review = team.critic_inference_review(state["analysis"], state["comp_results"])
        flags = [f"Claim {v.claim_index}: {v.reason}" for v in review.verdicts if not v.sound]
    return {"code_issues": code_issues, "inference_flags": flags}


def node_revise(state: TeamState) -> dict:
    """Node 5: re-analyze with the critic's feedback."""
    print(f"  [revise] attempt {state['revision_count'] + 1}...")
    problems = state["code_issues"] + state["inference_flags"]
    question = (state["question"] +
                "\n\nPREVIOUS ATTEMPT HAD THESE PROBLEMS - fix them:\n" +
                "\n".join(f"- {p}" for p in problems))
    analysis = team.analyze(question, state["facts"])
    return {"analysis": analysis, "revision_count": state["revision_count"] + 1}


def node_write(state: TeamState) -> dict:
    """Node 6: compose the final grounded answer."""
    print("  [write] composing answer...")
    lines = []
    for c in state["analysis"].claims:
        comps = ", ".join(
            f"{lbl}={state['comp_results'].get(lbl, {}).get('value')}"
            for lbl in c.supporting_computations
        )
        suffix = f"  [computed: {comps}]" if comps else ""
        lines.append(f"- {c.claim}{suffix}")
    return {"final_answer": "\n".join(lines)}

MAX_REVISIONS = 2


def route_after_critic(state: TeamState) -> str:
    """Conditional edge: decide where to go based on critic results."""
    problems = state["code_issues"] + state["inference_flags"]
    if not problems:
        return "write"                                  # clean -> compose answer
    if state["revision_count"] >= MAX_REVISIONS:
        return "escalate"                               # ceiling -> human
    return "revise"                                     # try again


def node_escalate(state: TeamState) -> dict:
    """Terminal node: the system admits it could not converge."""
    problems = state["code_issues"] + state["inference_flags"]
    answer = ("HUMAN REVIEW REQUIRED - unresolved after "
              f"{state['revision_count']} revisions:\n" +
              "\n".join(f"  - {p}" for p in problems))
    return {"final_answer": answer}

workflow = StateGraph(TeamState)

workflow.add_node("extract", node_extract)
workflow.add_node("analyze", node_analyze)
workflow.add_node("compute", node_compute)
workflow.add_node("critic", node_critic)
workflow.add_node("revise", node_revise)
workflow.add_node("write", node_write)
workflow.add_node("escalate", node_escalate)

workflow.set_entry_point("extract")
workflow.add_edge("extract", "analyze")
workflow.add_edge("analyze", "compute")
workflow.add_edge("compute", "critic")

# Conditional routing after the critic
workflow.add_conditional_edges("critic", route_after_critic, {
    "write": "write",
    "revise": "revise",
    "escalate": "escalate",
})

workflow.add_edge("revise", "compute")      # revised analysis must be recomputed
workflow.add_edge("write", END)
workflow.add_edge("escalate", END)

# Checkpointing: enables pausing, resuming, and inspecting state
app = workflow.compile(checkpointer=MemorySaver())

reader = PdfReader("data/uber_10k.pdf")
initial_state = {
    "question": "Which Uber segment contributed most to revenue growth in 2025?",
    "source_text": reader.pages[58].extract_text(),
    "facts": None, "analysis": None, "comp_results": None,
    "code_issues": [], "inference_flags": [], "revision_count": 0,
    "final_answer": None,
}

config = {"configurable": {"thread_id": "uber-analysis-1"}}

print("=" * 70)
print("RUNNING AGENT TEAM VIA LANGGRAPH")
print("=" * 70)
final_state = app.invoke(initial_state, config=config)

print("\n" + "=" * 70)
print("FINAL ANSWER")
print("=" * 70)
print(final_state["final_answer"])
print(f"\nrevisions: {final_state['revision_count']}")

# Checkpointing in action: the full state is recoverable after the run
snapshot = app.get_state(config)
print(f"state checkpoint available - next node: {snapshot.next or '(finished)'}")