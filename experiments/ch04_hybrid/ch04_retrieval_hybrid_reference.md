# Aleph · Chapter 4 Reference — Retrieval: the Real Bottleneck

> Fixed reference format. One per chapter. English. Read in 5 minutes, use forever.

---

## TL;DR

Dense (semantic) retrieval alone is the #1 cause of bad RAG answers because it's blind to exact words — the very things financial documents live on (tickers, years, "increased" vs "declined"). The fix is a layered pipeline: **hybrid search** (dense + BM25, fused with RRF) covers each method's blind spot; a **cross-encoder re-ranker** reads each candidate together with the query and re-scores true relevance; **query decomposition** breaks multi-intent questions into single-intent sub-questions so each retrieves cleanly from the right source. Fast-and-shallow filters the corpus; slow-and-accurate refines the survivors. This is what turns Aleph from "returns chunks" into a real multi-document analyst.

---

## Core concepts

**Two kinds of search, each blind to what the other sees:**
- **Dense (semantic)** — captures *meaning*, blind to exact words. `income ≈ earnings ≈ profit` (good), but `Q3 ≈ Q4` and `Uber ≈ Lyft` (bad). Works at the *average-meaning* resolution of a whole chunk, never per-word — so a rare word gets diluted in a noisy chunk.
- **Lexical (BM25)** — captures *exact words*, blind to meaning. `Q3 2024` = exactly `Q3 2024` (good), but `innovation ≠ R&D` (misses synonyms).

**BM25 in three principles:**
1. **TF (term frequency)** — more occurrences of a query word in a chunk → higher score (with diminishing returns).
2. **IDF (inverse document frequency)** — rare words are worth more; common words (`revenue`, in a 10-K) are nearly worthless for discrimination, rare ones (`Freight`, `LYFT`) are gold.
3. **Length normalization** — a short chunk mentioning the word twice beats a 10× longer chunk mentioning it twice.
BM25 never confuses `Q3 2024` with `Q2 2023` — different strings, no "almost." The exact inverse of dense's blindness.

**Why neither alone suffices (proven on Uber):** `Q3 2024` vs `Q2 2023` → BM25 saves (dense blurs); `innovation` vs `R&D` → dense saves (BM25 finds no string match). Need both.

**RRF (Reciprocal Rank Fusion):** BM25 and dense scores are on incompatible scales (kg vs km) — you can't add 8.3 to 0.34. RRF ignores scores entirely and uses only *rank position*, which is unit-free. Each chunk scores `sum of 1/(k + rank)` across both lists (k≈60 dampens the top ranks so one list can't dominate). A chunk that ranked well in *both* lists rises — agreement between two engines that see differently is a strong relevance signal.

**Re-ranking with a cross-encoder:**
- **Bi-encoder (Ch1 model)** — encodes query and chunk *separately* into two vectors, then measures angle. Fast (chunks precomputed once, stored in ChromaDB) but shallow — never sees the pair together.
- **Cross-encoder** — feeds query + chunk *together* through the model as a pair, scoring true relevance. Accurate but slow — nothing can be precomputed; every pair is a fresh model run. So it can't run on 500k chunks, only on the ~10–20 that hybrid already filtered.
- The pattern: hybrid (fast, 500k → 20) → cross-encoder (slow/accurate, 20 → reranked). Same "coarse filter then refine" as HNSW, one layer up. On Uber, a "Why did Freight revenue decline?" query pushed the *explanatory paragraph* above the *number table* — because the cross-encoder read the pair and understood the intent was "why," not "how much." Bi-encoder and BM25 couldn't; they only saw the words.

**Query decomposition:** a complex question ("Compare Uber's and Lyft's operating margin in 2024") fails retrieval for two reasons: (1) operational — no single chunk holds both companies (separate filings); (2) deep (Ch1) — a multi-intent query encodes to a *muddy point* averaging four intents (Uber, Lyft, margin, 2024), landing sharp on none. Decomposing into single-intent sub-questions fixes both: each sub-question encodes to a sharp point AND targets the right source. An LLM does the decomposition — the first place generation enters the retrieval pipeline, and the foundation of the multi-document layer.

---

## Code patterns learned

```python
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

# BM25 needs tokens (words), not raw text — it counts word matches
tokenized = [c.lower().split() for c in chunks]
bm25 = BM25Okapi(tokenized)
scores = bm25.get_scores(query.lower().split())   # score per chunk, unsorted

# RRF: fuse two ranked id-lists by position, not score
def rrf(dense_ids, bm25_ids, k=60):
    s = {}
    for r, cid in enumerate(dense_ids): s[cid] = s.get(cid, 0) + 1/(k+r)
    for r, cid in enumerate(bm25_ids):  s[cid] = s.get(cid, 0) + 1/(k+r)
    return sorted(s.items(), key=lambda x: x[1], reverse=True)

# Cross-encoder re-rank: score (query, chunk) PAIRS together
reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
pairs = [(query, id_to_chunk[cid]) for cid in candidate_ids]
reranked = sorted(zip(candidate_ids, reranker.predict(pairs)),
                  key=lambda x: x[1], reverse=True)
```

---

## Gotchas / failure patterns

- **`JSONDecodeError: Expecting value: line 1 column 1 (char 0)`** — an LLM asked for JSON returned prose or a markdown fence around it (`Here are...` / ```` ```json ````). LLM output is probabilistic, not structured — never trust its format. Robustness layer: strip fences, then slice from first `[` to last `]` before `json.loads`. Belt *and* suspenders: tighten the prompt AND defend in code.
- **`NameError: name 'complex_q' is not defined`** — replacing a code block accidentally deleted adjacent lines. Watch block boundaries when swapping code. Module-level calls (`complex_q = ...`, `subs = decompose_query(...)`) must stay *outside* the function (no indentation) or they change meaning.
- **Cross-encoder scores are raw logits** (can be negative, e.g. 2.488, −1.872, −4.711), not probabilities. Only the *relative order* matters.
- **Small candidate pools hide errors:** with few chunks, even a weak method hits the right one by luck. The advantage of hybrid/re-ranking only becomes visible at real corpus size.
- **HF warnings** (`unauthenticated`, `symlinks`) are cosmetic — models download and cache fine.

---

## Evidence from the experiment (Uber, ~20 pages, 151 chunks)

- Query "Uber Freight revenue": dense top-3 `[c21, c147, c22]` vs BM25 top-3 `[c29, c30, c22]` — almost no overlap (they see differently). RRF fused `[c21, c29, c22]` — a blend: `c21` (table, from dense) + `c29` (explanatory paragraph, from BM25, found via rare word "Freight"×4).
- Query "Why did Uber Freight revenue decline?": hybrid `[c29, c21, c30]` → after cross-encoder `[c29, c30, c147]`. The number table `c21` *dropped out* of the top-3 because it shows the decline but doesn't *explain* it; the "decreased primarily…" paragraph rose. Only the cross-encoder, reading query+chunk together, caught "why" ≠ "how much."
- Decomposition: "Compare Uber's and Lyft's operating margin in 2024" → `["What is Uber's operating margin in 2024?", "What is Lyft's operating margin in 2024?"]` — two single-intent, single-company sub-questions.

---

## What this means for Aleph

The full retrieval pipeline now exists and is understood: decompose → (hybrid: dense + BM25 → RRF) → cross-encoder re-rank. This is the layer that makes Aleph multi-document — one user question can now pull from Uber, Lyft, and five years, because it's split into sub-questions that each hit the right place, and the survivors are re-ranked by true relevance. The decomposition step is also the first hand-off from retrieval to generation, which the grounding chapters build on. Standing lesson carried forward: LLM output is never trusted as structured — always defend the parse.

---

## 60-second self-test

1. Give a financial example where dense retrieval fails and BM25 saves — and the reverse.
2. Why does RRF use rank position instead of the raw scores?
3. Why is a cross-encoder too slow to run on the whole corpus, but a bi-encoder isn't? (What can be precomputed?)
4. Why does a multi-intent query ("compare A and B") produce a bad embedding, and how does decomposition fix it — in Ch1 terms?
5. Why did the number table drop out of the top-3 after re-ranking on a "why" question?

<details>
<summary>Answers</summary>

1. `Q3 2024` vs `Q2 2023` — dense blurs the near-identical meaning, BM25 sees different strings (BM25 saves). `innovation expenses` vs `R&D` — BM25 finds no matching string, dense knows they're semantically close (dense saves).
2. BM25 and dense scores are on incompatible scales; rank position is unit-free, so it fairly combines two methods that measure different things.
3. Cross-encoder feeds query+chunk together, so nothing can be precomputed — every pair is a fresh model run. Bi-encoder encodes chunks separately, so all chunk vectors are computed once, stored, and only a fast angle comparison happens at query time.
4. It encodes to a muddy average-of-four-intents point that lands sharp on none; single-intent sub-questions each encode to a sharp point (and target the right source).
5. It shows the decline but doesn't explain it; the cross-encoder read the query "why…" together with the chunk and scored the explanatory paragraph as more relevant than the number table.
</details>
