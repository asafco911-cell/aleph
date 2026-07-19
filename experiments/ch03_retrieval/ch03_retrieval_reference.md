# Aleph · Chapter 3 Reference — Vector Stores & Retrieval

> Fixed reference format. One per chapter. English. Read in 5 minutes, use forever.

---

## TL;DR

A vector store answers "which chunks are nearest to this query?" at scale. The naive method — brute-force / exact search — compares the query to every stored vector: 100% accurate but O(n), so it collapses as chunk count grows (Aleph will hit 500k+ chunks). Real vector stores use an ANN (Approximate Nearest Neighbor) index; ChromaDB uses HNSW, which navigates a hierarchy of "small-world" graphs to find neighbors in ~O(log n) without scanning everything. The trade: it's *approximate* — it can return an almost-right top-k, not always the exact one, because greedy search can get stuck in a local minimum. This is fine for **finding** chunks (answers are spread across several, top-k is insurance) but the reason the numeric layer must never be approximate.

---

## Core concepts

**Why brute-force fails.** Comparing a query to every vector is exact but linear: double the chunks, double the time. At Aleph's scale (company + 5 competitors × 5 years) that's hundreds of thousands of comparisons per query, paid fresh every query. (Analogy: finding a word by reading the dictionary front to back.)

**HNSW = Hierarchical Navigable Small World.** Three ideas stacked:
1. **Small world** — like six degrees of separation: each node links to near neighbors plus a few far ones. Those long links are shortcuts that shrink the whole graph.
2. **Navigable (greedy search)** — from any node, hop to whichever neighbor is closest to the query; stop when no neighbor is closer. Like walking downhill in fog — you follow the descent without seeing the whole hill.
3. **Hierarchical** — layers like map zoom levels. The top layer is sparse with huge jumps (get to the right region fast); each layer down is denser with smaller hops; the bottom layer holds every node for the final precise landing. Search starts at the top and descends. (Country → city → street, not house-by-house.)

**Why it's approximate — local minima.** Greedy "always step downhill" can get trapped in a small dip: every next step is uphill, so it stops, thinking it found the bottom — but the true valley is beyond a small ridge it would have had to climb over first. That's the exact source of the "approximate" in ANN: the returned neighbor is locally closest, not guaranteed globally closest. HNSW mitigates this with the long shortcut links (jump over ridges), multiple layers (start near the right region), and the `ef` parameter (hold several candidate paths at once instead of betting on one dip).

**The dividing line that defines Aleph.** Approximate is acceptable for the *retrieval* step (which chunks are relevant) — answers are spread across several, top-k is insurance, a miss is at the margin. It is forbidden for the *computation* step (Owner Earnings, DCF, FCF) — a "roughly right" valuation is a wrong valuation with real money on it. Approximate the finding, never the math.

**In-memory vs persistent.** `chromadb.Client()` keeps the index in RAM — wiped when the script ends, rebuilt from scratch (re-read, re-chunk, re-encode) every run. `PersistentClient(path=...)` saves the HNSW index to disk and loads it next run. Encoding is the expensive step; at Aleph's scale (100k+ chunks, minutes to encode) persistent means paying once, not every run. (Analogy: build the report library once and leave it on the shelf vs rebuild it every morning.) This chapter used in-memory deliberately — 10 chunks, instant, and it forces the whole pipeline (load → chunk → encode → store → query) to run visibly each time.

---

## Evidence from the experiment (Uber page 60, 7 chunks, in-memory)

Query: *"How much revenue did Uber Mobility generate?"* → `n_results=3`

- **Result 1 (distance 1.339)** — the Mobility revenue table. The full pipeline worked: query encoded → HNSW navigation → nearest neighbor is the correct table. It worked *despite* the chunk being "number soup," because the words "Mobility" / "Revenue" pulled the point to the right region — and the structure-chunker from Ch2 kept the whole table (header + rows) intact in one chunk.
- Results 2–3 (1.567, 1.618) — adjacent prose about non-GAAP measures. Correctly ranked lower (smaller distance = closer).
- **Metric gotcha:** ChromaDB's default distance is **squared L2 (Euclidean)**, not cosine — that's why scores are ~1.3, not ~0.8 like the Ch1 cosine heatmap. Default metric is a *decision*, not a given; for text we usually want cosine (Ch1 reasons), set explicitly.
- **The remaining problem:** retrieval succeeded, but the returned chunk is still `Mobility $ 18,670 $ 20,554 ...` — the number↔quarter link is still gone (Ch2). Good retrieval found the right chunk; it did not make the chunk *usable*. Retrieval is necessary but not sufficient.

---

## Code patterns learned

```python
import chromadb

client = chromadb.Client()                          # in-memory (PersistentClient(path=...) to persist)
collection = client.create_collection(name="uber_page60")

collection.add(                                     # ChromaDB encodes internally (all-MiniLM default)
    documents=chunks,
    ids=[f"chunk_{i}" for i in range(len(chunks))],
)

results = collection.query(                          # encodes query, navigates HNSW, returns top-k
    query_texts=["How much revenue did Uber Mobility generate?"],
    n_results=3,
)
results["documents"][0]   # the chunk texts
results["distances"][0]   # squared-L2 distances, smaller = closer
```

---

## Gotchas / failure patterns

- **Default metric is L2, not cosine.** Distances look like ~1.3, not ~0.8. For text, prefer cosine — set it explicitly on the collection (`metadata={"hnsw:space": "cosine"}`).
- **`add(documents=...)` hides the encode step.** You pass raw text; ChromaDB runs `all-MiniLM-L6-v2` under the hood. Convenient, but know it's happening — it's the expensive part at scale.
- **In-memory wipes on exit.** Fine for learning; switch to `PersistentClient` before building on many documents, or you re-encode everything every run.
- **Retrieval success ≠ usable answer.** The right chunk can still be number soup. Don't conclude the pipeline works just because rank-1 is correct.

---

## What this means for Aleph

The retrieval layer is in place and understood end to end. Two decisions carry forward: (1) switch to `PersistentClient` and set the metric to cosine when the corpus grows; (2) retrieval is only half — the returned chunk must also preserve structure (number↔column), which is why Table Extraction and grounding get their own chapters. Approximate is confined to *finding*; every number Aleph reports still runs through exact Python.

---

## 60-second self-test

1. Why does brute-force search fail at Aleph's scale despite being 100% accurate?
2. What do the sparse top layers of HNSW buy you over searching only the dense bottom layer?
3. Why is greedy search not guaranteed to find the true nearest neighbor? Name the phenomenon.
4. Where is "approximate" acceptable in Aleph, and where is it forbidden — and why?
5. Retrieval returned the correct Mobility table first. Why is the user's question still not really answered?

<details>
<summary>Answers</summary>

1. It's O(n) — linear. Double the chunks, double the time; at hundreds of thousands of chunks, every query pays the full cost.
2. Big jumps that reach the right region fast, so the search does few steps overall (start near the target, then refine) instead of many small hops from far away.
3. Greedy "always step to the closest neighbor" can get trapped in a local minimum — a dip where every next step is uphill, even though a deeper valley exists beyond a ridge it won't climb.
4. Acceptable for retrieval (finding relevant chunks — answers are spread out, top-k is insurance); forbidden for the numeric computation (DCF/Owner Earnings), where "roughly right" is a wrong valuation.
5. The chunk is still number soup: `Mobility $ 18,670 $ 20,554 ...` with the number↔quarter link lost in extraction. Retrieval found the right chunk but didn't make it usable.
</details>
