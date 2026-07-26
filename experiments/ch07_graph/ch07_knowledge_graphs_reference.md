# Aleph · Chapter 7 Reference — Knowledge Graphs

> Fixed reference format. One per chapter. English. Read in 5 minutes, use forever.

---

## TL;DR

RAG retrieves *similar text*. It cannot answer questions whose answer isn't written anywhere — where the insight only exists once two facts from different documents are placed side by side. A knowledge graph changes the **representation**, not the information: entities become nodes, relationships become typed edges, and the relationship itself becomes a first-class queryable object. Questions that were structurally impossible (multi-hop, temporal, aggregation) become mechanical traversals. The division of labour is the point: **the LLM interprets language once, Python computes forever after.**

---

## Core concepts

**The wall RAG can't cross.** RAG's retrieval unit is a *chunk of text*, and its question is always "where is the relevant text?" That works when the answer is written somewhere. It fails on three question types:
- **Multi-hop** — "which risks are common to all gig-economy players?" needs 4 filings read, risks extracted from each, and the *intersection* computed. No chunk contains it.
- **Temporal** — "did the risk disclosed in 2023 materialize?" needs the same entity linked across filings from different years. The 2023 sentence and the 2025 sentence were never written next to each other.
- **Aggregation** — "how many of Uber's risk factors are regulatory?" RAG can't count. top-k=5 returns 5 chunks, not a count.

**Why bigger top-k or a better re-ranker doesn't fix it.** Three mechanical reasons: (1) the failure starts at *retrieval* — the query "did the risk materialize?" isn't semantically similar to either source sentence, so the system doesn't know it must look in two places; (2) even if the LLM connects them once, the connection **dies with the conversation** — a graph edge persists and is re-queryable; (3) aggregation needs to read *everything*, and no context window holds 4 companies × 5 years.

**The three building blocks:**
- **Nodes** — the things: companies, segments, metrics, risks, events, periods.
- **Edges** — typed relationships. The *type* is what makes the graph queryable: `HAS_SEGMENT` ≠ `REPORTED` ≠ `FACES_RISK`. `HAS` is not a relation type, it's a refusal to think.
- **Properties** — data hanging on a node or edge (`{period: FY2025, value: 5099, unit: "USD millions"}`).

A graph is essentially a pile of sentences decomposed into subject-verb-object triples: `(Uber) --[OPERATES]--> (Mobility)`.

**The node-vs-property decision (the hard part).** Ask one question: **"will anything else in the graph want to connect to this?"**
- `Freight` → yes (Uber connects to it, metrics connect to it) → **node**
- `Revenue` → yes — it's shared by every segment and every company; you'll want "show me Revenue across all segments" → **node**
- `$42 million` → nothing connects to "42 million"; it's the *value of one measurement* → **property**
- `FY2025` → **depends.** Just a label on a measurement → property. But if you want to query *time itself* ("what changed between 2023 and 2025?", "which risks materialized in year X?") → **node**. For Aleph, which is built on 5-year analysis, period must be a node.

**Rule of thumb:** metrics and concepts are nodes (they're shared); numbers and dates of a specific measurement are properties on the edge. The `REPORTED` edge *is* the measurement, and the numbers live on it.

**Encoding levels without duplicating nodes.** Company-level and segment-level Adjusted EBITDA use the **same metric node**; what distinguishes them is the *edge source*:
```
(Uber)     -[REPORTED {2025, 8730}]-> (Adjusted EBITDA)   # company level
(Mobility) -[REPORTED {2025, 7899}]-> (Adjusted EBITDA)   # segment level
```
Creating `Company Adjusted EBITDA` and `Mobility Adjusted EBITDA` as separate nodes would destroy the link between them.

**Shared entities are the whole point.** `(Uber) -[FACES_RISK]-> (Driver reclassification) <-[FACES_RISK]- (Lyft)` — both point at the *same object*. That's **identity, not similarity**. It turns "which risks are shared across gig-economy players?" into: find risk nodes with more than one incoming FACES_RISK edge. If risks were a property on the company (`{risks: [...]}`), that query would be impossible.

**Graph vs table.** Extracting to structured parameters (company / segment / period / metric / value) already beats RAG — you can filter and slice. A graph adds three things a table can't: **variable depth** (a chain of any length: risk → ruling → year), **cross-type relationships** (entities of different kinds as equal citizens, no column planned per relation), and **entity sharing** (identity, per above). Short version: RAG retrieves similar text; a table retrieves filtered values; a graph walks paths and surfaces relationships nobody wrote down.

**Division of labour — the principle the whole course converges on:**

| Stage | Who | Why |
|---|---|---|
| Language understanding — read prose, recognize "Freight is a segment, 5,099 is a Revenue value" | **LLM** | Only it can parse natural language and infer intent |
| Computation and inference — subtraction, sorting, set intersection | **Python** | Deterministic, zero hallucination risk |

The graph **freezes the LLM's work**. Extract once, then ask a thousand new questions with zero API calls and zero new hallucination exposure. In RAG, every question re-runs the model and re-exposes you.

---

## Code patterns learned

Schema that enforces the node/property rule (Ch6 techniques applied):
```python
class Node(BaseModel):
    id: str      # canonical name
    type: str    # Company | Segment | Metric | Risk | Event | Period
    # NOTE: no value field — a node can never be a number

class Edge(BaseModel):
    source: str; relation: str; target: str      # relation is UPPERCASE: HAS_SEGMENT, REPORTED...
    period: Optional[str] = None                  # numbers live on the edge
    value: Optional[float] = None
    unit: Optional[str] = None
```

Prompt rules that made the extraction obey:
- "NEVER create a node for a number. Numbers belong on the edge as `value`."
- "Metrics are shared nodes reused across segments and companies."
- "Encode the reporting level by the edge source. Do not rename the metric per level."

Building and traversing:
```python
G = nx.MultiDiGraph()          # directed (direction matters) + multi-edge
                               # (Mobility)->(Revenue) exists once per period
for n in data["nodes"]: G.add_node(n["id"], type=n["type"])
for e in data["edges"]: G.add_edge(e["source"], e["target"], **e)

for _, target, attrs in G.out_edges(seg, data=True):    # traversal
    if target == "Revenue" and attrs["relation"] == "REPORTED":
        by_period[attrs["period"]] = attrs["value"]
growth = by_period["2025"] - by_period["2024"]           # computed in Python, never by the LLM
```

---

## Evidence from the experiment (Uber page 58 → 15 nodes, 26 edges)

- **No node is a number.** All 15 nodes are companies, segments, metrics, or periods. The rule held.
- **`Revenue` is one shared node** — Uber, Mobility, Delivery, and Freight all point to it.
- **Level encoding worked:** `(Uber)->(Adjusted EBITDA) {8730}` and `(Mobility)->(Adjusted EBITDA) {7899}` — same node, distinguished by source.
- **Q1 (deterministic computation):** Mobility contributed most in dollars (+4,583M, 18.3%) while Delivery grew faster in percent (+3,498M, 25.4%); Freight declined (−42M, −0.8%). Two valid answers to "contributed most," visible *because* the numbers were computed rather than narrated. The −42M independently reproduced the manually verified ground truth.
- **Q2 (aggregation — the RAG-impossible one):** company level reports only `Revenue` and `Adjusted EBITDA`; segment level additionally exposes `Driver payments and incentives`, `Insurance expense`, `Network costs`, `Credit card processing costs`, `Advertising and marketing`, `Gross Bookings`. **Real analytical insight: the actual unit economics are disclosed only at segment level.** No sentence in the filing states this — it emerged from a set difference over graph structure.
- **The graph also exposed structure behind prose:** Freight Adjusted EBITDA was −74 (2024) → −33 (2025), which is exactly the "$41 million, or 55% improvement" the filing narrates. Now it's computable instead of quotable.

---

## Gotchas / failure patterns

- **Inconsistent period granularity.** Some edges got `period: "2024"` (point), others `"2024 to 2025"` (range). A query filtering `period == "2025"` silently misses the ranges. Not a model bug — a **schema gap**. Fix: add `period_type`, or split into `period_start` / `period_end`. *(Open issue.)*
- **`HAS` as a relation type** is a smell — it means the extraction didn't decide what the relationship actually is.
- **Use `MultiDiGraph`, not `Graph`.** Direction matters, and multiple edges between the same pair (one per period) are required — a simple graph overwrites them.
- **Don't create a node per number** — the fastest way to turn a graph into spaghetti.

---

## What this means for Aleph

This is the layer that makes Aleph unusual. The next steps: extract across *all* pages and *all* companies into one persistent graph (Neo4j once it outgrows networkx), add `Risk` and `Event` nodes with `REALIZED_BY` edges to answer the temporal question ("did the 2023 risk materialize?"), and build **GraphRAG hybrid** — use vector retrieval to find the entry node, then traverse the graph from there, combining semantic search with structural reasoning. Every number surfaced still runs through Python.

---

## 60-second self-test

1. Name the three question types RAG structurally cannot answer, with one example each.
2. Why doesn't a larger top-k fix the temporal question?
3. What's the test for node vs property? Apply it to `Revenue`, `$42 million`, and `FY2025`.
4. How do you represent company-level and segment-level Adjusted EBITDA without duplicating the metric node?
5. Which stage uses the LLM, which uses Python — and why does the graph reduce hallucination exposure over time?

<details>
<summary>Answers</summary>

1. Multi-hop ("common risks across gig-economy players"), temporal ("did the 2023 risk materialize?"), aggregation ("how many risk factors are regulatory?").
2. The failure starts at retrieval — the query isn't semantically similar to either source sentence, so the system doesn't know it needs two places; and even if both are retrieved, the connection isn't stored and dies with the conversation.
3. "Will anything else connect to this?" Revenue → yes (shared across segments/companies) → node. $42 million → nothing connects to a number → property. FY2025 → property if it's just a label, node if you want to query time itself (Aleph needs it as a node).
4. Same metric node for both; the level is encoded by the edge source — `(Uber)->(Adjusted EBITDA)` vs `(Mobility)->(Adjusted EBITDA)`.
5. LLM for extraction (language → structure), Python for all traversal and computation. The graph freezes the LLM's work: extract once, then answer unlimited questions with no further model calls and no new hallucination risk.
</details>
