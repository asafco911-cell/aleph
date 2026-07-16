# Aleph · Chapter 1 Reference — Embeddings

> Fixed reference format. One per chapter. English. Read in 5 minutes, use forever.

---

## TL;DR

An embedding turns a piece of text into a fixed point in a high-dimensional space (here, 384 numbers), computed **absolutely** — one sentence in, one vector out, no comparison needed. Similar meaning lands at nearby points; distance and angle between points encode semantic similarity. The catch that defines the whole project: general-purpose embedders judge two sentences by shared **topic and words**, not by **direction of meaning** — so `"Revenue increased 12%"` and `"Revenue declined 12%"` score as highly similar. Every retrieval layer we build later exists to fix this.

---

## Core concepts

**Meaning becomes geometry.** A model trained on billions of texts fixes a coordinate grid where meaning maps to position. `encode()` doesn't build that grid — it looks up where a sentence falls on a grid already baked into the model's weights. This is why a single sentence gets a meaningful location with no other sentence present (the GPS analogy: Tel Aviv has coordinates whether or not another city is on the map).

**Two separate operations — never conflate them:**
1. `encode(sentence)` → absolute address. One sentence, one vector. No second sentence required.
2. `cosine(v1, v2)` → relative comparison. Needs two vectors. Returns how aligned they are.

**Why so many dimensions.** Meaning has many independent axes of similarity that must hold *simultaneously without colliding* (`apple` is near fruits AND tech companies AND colors, each on a different axis). Two dimensions would force those relationships to conflict. More dimensions = more independent directions to satisfy at once.

**Three ways to measure "near":** think of each vector as an arrow from the origin.
- **Euclidean** — straight-line distance between arrow *tips*. Sensitive to both direction and length.
- **Dot product** — mixes alignment and length.
- **Cosine** — the *angle* between arrows only; ignores length. This is the default for semantic search, because vector length usually encodes things you don't care about (text length, emphasis) while direction carries meaning.

**Normalization corollary.** When a model returns unit-length vectors (all arrows touch the same circle), the length component Euclidean is sensitive to cancels out, and cosine / dot / Euclidean produce the **same ranking** of nearest neighbors. `all-MiniLM-L6-v2` returns normalized vectors — verified: norm ≈ 1.0.

---

## Evidence from the experiment (10 financial sentences, `all-MiniLM-L6-v2`)

| Pair | Sentences | Cosine | Reading |
|---|---|---|---|
| 0 vs 1 | "Revenue increased 12%" vs "Sales grew strongly" | **0.60** | true agreement |
| 0 vs 3 | "Revenue increased 12%" vs "Revenue **declined** 12%" | **0.78** | the failure — opposite meaning, scored *higher* than true agreement |
| 1 vs 4 | "Sales grew" vs "Sales dropped" | **0.69** | same failure, second pair |
| 0 vs 8 | "Revenue increased 12%" vs "The cat sat on the mat" | **−0.04** | this is what "unrelated" actually looks like |

**The headline:** the failure isn't that 0.78 is high — it's that **0.78 > 0.60**. The model is *more* confident that "increased" relates to "declined" than that "increased" relates to "grew". A general embedder is blind to direction of change.

---

## Code patterns learned

```python
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

model = SentenceTransformer("all-MiniLM-L6-v2")   # 384-dim, local, free, normalized

v = model.encode("one sentence")                  # -> shape (384,)
V = model.encode([s1, s2, s3])                     # -> shape (N, 384), batched
sim = cosine_similarity(V)                         # -> (N, N) matrix, diagonal = 1.0
```

---

## Gotchas / failure patterns

- **HF Hub warnings** (`unauthenticated requests`, `symlinks not supported on Windows`) are cosmetic — cache works, just uses more disk. Ignore, or set `HF_TOKEN` / enable Developer Mode to silence.
- **Global vs venv installs.** If `pip` reports "Requirement already satisfied" from `AppData\...\pythoncore`, packages are going to the *global* interpreter, not the venv. The tell: no `(venv)` prefix and no `venv/` folder. Fix: create + activate the venv first.
- **First `encode()` downloads the model (~90 MB)** once, then caches. Slowness on run 1 is normal.

---

## The problem this chapter surfaced (carry it forward)

General embeddings collapse antonyms that share surface form. For an analyst querying *"companies whose revenue fell,"* this returns companies whose revenue **rose** — a dangerous answer. Later chapters attack this directly: hybrid search (BM25 catches exact tokens like "declined"), re-ranking (a cross-encoder reads both sentences together), and light fine-tuning on financial sentence pairs.

---

## 60-second self-test

1. Does `encode()` need a second sentence to place the first? Why or why not?
2. What does cosine measure geometrically, and what does it deliberately ignore?
3. If vectors are normalized to length 1, does cosine-vs-Euclidean still change the ranking?
4. In one line: why did `"Revenue increased 12%"` and `"Revenue declined 12%"` score 0.78?
5. Which is more alarming — that 0.78 is high, or that 0.78 beat 0.60? Why?

<details>
<summary>Answers</summary>

1. No. The coordinate grid is baked into the model weights; `encode()` looks up an absolute position on a pre-existing map.
2. The angle between two vectors; it ignores their length (magnitude).
3. No — length is what Euclidean is sensitive to, and once it's fixed at 1, both metrics rank neighbors identically.
4. The two sentences share almost every word and the topic; the single word that flips the meaning (increased↔declined) barely moves the vector.
5. That 0.78 beat 0.60 — it means the model treats an antonym as *more* related than a genuine paraphrase, which is exactly backwards for analysis.
</details>
