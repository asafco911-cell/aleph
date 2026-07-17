# Aleph · Chapter 2 Reference — Chunking

> Fixed reference format. One per chapter. English. Read in 5 minutes, use forever.

---

## TL;DR

Chunking is the decision of how to cut a long document into retrievable pieces, and it silently determines whether retrieval returns gold or garbage. Two forces pull against each other: chunks too **large** dilute meaning (one point in space that represents five topics at once, landing in a muddy center far from any specific query); chunks too **small** sever context (an orphaned number with no header, a pronoun with no antecedent). Naive fixed-size chunking (`text[i:i+500]`) ignores both and cuts blindly — breaking words mid-token and separating table rows from their column headers. This is catastrophic for financial documents, where the structure of a table *is* its meaning.

---

## Core concepts

**Why chunk at all — two reasons, both from Chapter 1:**
1. **Meaning concentration.** An embedding is the "meaning-average" of everything fed in. One sentence about revenue → a sharp point in the "revenue" region. 149 pages about everything → a muddy point at the center of mass, representing no single topic. Bigger chunk = more diluted meaning = worse retrieval. (Analogy: mixing every paint color gives muddy brown.)
2. **Context windows.** Both the embedder and the LLM have token limits. `all-MiniLM-L6-v2` reads ~256 tokens and silently truncates the rest. You must cut to fit.

**The core tension:** large enough to keep context intact, small enough to keep meaning sharp. There is no magic number — it depends on the document type.

**Why PDF extraction destroys tables (structural insight):** PDF text extraction reads **left-to-right, line-by-line**, like a human reading a page. So **horizontal** information (a row: `Freight 1,282 1,272 1,308...`) survives — it's read in sequence. But **vertical** information (that `1,308` is aligned *under* the `Q3 2024` header) is destroyed — the alignment lived only in the drawing coordinates on the page, which `extract_text()` throws away. Result: a 2D table collapses into a 1D "number soup" where the number↔column link is gone.

**Why overlap doesn't fix tables:** overlap is a *distance-based* tool (drag the last N characters into the next chunk). It saves close neighbors — a word cut at the boundary. But the table problem is *structural*: a header belongs to its rows no matter how far apart they are. If the header sits 300 characters above the severed row and overlap is 50, the header is out of reach. **You cannot solve a structural problem with a distance tool.** (Analogy: overlap is grabbing the hand of the person right next to you when you fall — useless if what saves you is six people to the left.)

---

## Evidence from the experiment (Uber 10-K, page 60)

**Naive chunker** (`text[i:i+500]`), the two crimes at the CHUNK 1 → CHUNK 2 boundary:
- Crime 1 — word split: `...net income (loss),income (1` | `oss) from operations...` — the word `(loss)` shattered into `(l` + `oss)`, dirtying the embedding and starting CHUNK 2 with a meaningless fragment.
- Crime 2 (the dangerous one) — a table row severed from its header. Only luck kept the whole table in one chunk here (page was short, 4027 chars → 9 chunks). A table starting near a boundary would split, leaving `Delivery 17,699 18,126...` with no `Q1 2024 Q2 2024` header and not even the word "revenue" — unretrievable, and unusable by the LLM even if retrieved.

**Structure-aware chunker** (split on lines, accumulate whole lines up to a max), same boundary:
- `(loss)` is now whole. Lines are never cut mid-way; a line that doesn't fit is pushed *entirely* to the next chunk.
- Chunk count dropped 9 → 7: respecting structure means giving up uniform size (a good trade — uniform size was never the goal; intact meaning is).
- **Still not solved:** it respects *lines*, not *tables*. A table longer than the max still splits, orphaning rows from the header. It sees lines, not tables.

---

## Code patterns learned

```python
from pypdf import PdfReader
reader = PdfReader("data/uber_10k.pdf")          # relative path — run from repo root (aleph/)
text = reader.pages[60].extract_text()           # one page's text layer

# Naive: blind, fixed-size
def naive_chunk(text, size=500):
    return [text[i:i+size] for i in range(0, len(text), size)]

# Structure-aware: accumulate whole lines, never cut a line
def structure_chunk(text, max_chars=500):
    chunks, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) > max_chars and current:
            chunks.append(current.strip())
            current = line
        else:
            current += "\n" + line
    if current.strip():
        chunks.append(current.strip())
    return chunks
```

---

## Gotchas / failure patterns

- **`FileNotFoundError: 'data/uber_10k.pdf'`** — the relative path is resolved from the *current working directory*. Run from `aleph/`, not a subfolder. Also check the exact filename with `dir data` (spaces, hyphens, casing all matter). Prefer short, space-free names like `uber_10k.pdf`.
- **Selectable PDF text = real text layer** → no OCR needed. If text can't be selected, it's a scanned image and needs OCR (a different pipeline).
- **Same extraction, two outcomes:** prose survives extraction fine; tables collapse. The problem isn't the PDF — it's that tables and prose need different handling.

---

## What this means for Aleph

Most "okay" RAG systems stop at structure-aware chunking on text and still break on financial tables. Aleph must go further: detect a table as a *whole unit*, keep the header attached to every row, and ideally convert the table to a format that preserves the number↔column link (Markdown table, or explicit `Mobility Q3-2025: 25,111`). This earns its own dedicated chapter (Table Extraction) — and now the reason it needs one is clear.

---

## 60-second self-test

1. In vector-space terms, what happens to the point of a huge chunk covering five topics, and why does it hurt retrieval?
2. Why does PDF extraction preserve table *rows* but destroy table *columns*?
3. Why can't overlap (a distance-based tool) fix a header-separated-from-rows problem?
4. Why did the structure-aware chunker produce *fewer* chunks than the naive one, and why is that fine?
5. What single problem remains unsolved after structure-aware chunking, and what kind of tool is needed instead?

<details>
<summary>Answers</summary>

1. It lands at the muddy center of mass of all five topics, far from any single-topic query point; cosine to the query is low, so the chunk isn't retrieved even though the answer is inside it.
2. Extraction reads horizontally, line-by-line; row order is horizontal (survives), column alignment is vertical (lived only in drawing coordinates, which are discarded).
3. Overlap only drags a fixed number of characters back; the header belongs to its rows structurally, at any distance. A distance tool can't express "this belongs to that regardless of gap."
4. It let chunk sizes flex to avoid cutting lines; uniform size was never the goal — intact meaning is.
5. Tables longer than the max still split, orphaning rows from their header. A *structure-aware* tool that treats a table as one indivisible unit is needed, not a size- or distance-based one.
</details>
