# Aleph · Chapter 11 Reference — Multi-Document Intelligence

> Fixed reference format. One per chapter. English. Read in 5 minutes, use forever.

---

## TL;DR

Comparing companies looks trivial and isn't: size differences make absolute figures meaningless, identical metric *names* hide different definitions, fiscal years don't align, and a company can silently redefine its own metric mid-period — turning a "trend" into an artifact. The engine answers this with **normalization to ratios only**, **trend slopes reported with a consistency measure**, and a **GAAP-vs-non-GAAP divergence detector** that catches what none of Chapter 10's forensic scores can see. This is what makes Aleph genuinely multi-doc: not retrieving from three filings, but reaching a conclusion **no single filing contains.**

---

## Core concepts

**Four obstacles to cross-company comparison:**
1. **Size.** "Uber spent more on R&D than Lyft" is true and useless. Every comparison must be **normalized** — R&D as a *percentage of revenue*. Same principle as accruals ÷ total assets (Ch10) and words per 1000 (Ch10 language forensics). **Normalization isn't a technical detail; it's a precondition for validity.**
2. **Different definitions behind identical names.** Two companies both report "Adjusted EBITDA" and compute it differently — one excludes SBC, the other doesn't. (Analogy: two runners both say "I ran a marathon in 3 hours," one ran 42km and the other 35.) **Safe comparison is on GAAP** (legally defined) or on metrics you compute yourself from raw figures.
3. **Non-overlapping fiscal years.** December-end vs June-end companies: "FY2025" covers different periods.
4. **Definition drift within one company over time.** The sneakiest one — a metric redefined in 2023 makes the 2021–2025 "trend" partly a definitional artifact rather than business improvement.

**Definition drift is also a forensic red flag — but no Chapter 10 tool catches it.** Beneish M-Score is computed **entirely from GAAP financials** (revenue, receivables, depreciation, assets, cash flow) and never looks at non-GAAP metrics. A company can redefine Adjusted EBITDA, inflate the number investors actually watch, and **pass M-Score clean** — the same lesson as Altman Z rating the Ch10 manipulator "safe." **Every tool is blind to what it doesn't measure.**

What *does* catch it: (a) **language forensics** (Ch10) — an SEC-required disclosure of the change shows up as new terms in `content_diff`; (b) **GAAP-vs-non-GAAP trajectory comparison** — the tool built here.

**When definition change is legitimate:** an accounting-standard change (e.g. ASC 606 across an industry) or a genuine structural change like a major acquisition. **The test: did the company restate prior years?** If yes, transparent. If no, and the trend breaks exactly at the change year — that's the flag.

**The adjusted-to-GAAP ratio.** `adjusted_ebitda / net_income` measures *how much management is excluding*. A ratio of 2.8x means the adjusted figure is 2.8× the actual profit. This is a metric none of the three forensic scores computes, and it needs no calculation to read — just two numbers on the same row.

**Level vs delta — the distinction that governs everything here:**

| | **Delta** (change) | **Level** (height) |
|---|---|---|
| Answers | Did management change behaviour? | Is the exclusion justified? |
| Tool | statistical, automatable | reading the reconciliation |
| Output | red flag | needs review |

A permanently high ratio (say 8.0x, stable) is **not a red flag** — it means management excludes the same thing, the same amount, every year, which is consistent reporting. Capital-heavy businesses (infrastructure, airlines, real estate) legitimately show high stable ratios forever. But the *level* still warrants a qualitative check of *what* is being excluded: real depreciation is reasonable; SBC and "restructuring costs" recurring every year are **a recurring expense disguised as one-time** (Buffett's classic objection). **Delta is what can be automated, which is why the tools measure it; level requires judgment, so Aleph should mark it "needs review" rather than declare a flag.**

**Trend detection needs a consistency measure, not just a slope.** `r²` distinguishes a smooth structural improvement (r²≈1.0) from random jumps that happen to trend upward (r²≈0.3). **Consistency is evidence of structure; noise is evidence of luck or manipulation.** Also judge slope *relative to the starting level* — 0.5pp/year is trivial on a 40% margin and dramatic on a 3% one.

**Contradiction detection.** The tell isn't that the adjusted metric jumped — it's that it jumped **while GAAP moved the other way**. A business cannot simultaneously improve and deteriorate; divergence in opposite directions has no operating explanation.

---

## Code patterns learned

Normalization enforced by structure — the function returns *only* ratios, so absolute figures can't leak into a comparison:
```python
def normalized_metrics(cy):
    return {"operating_margin": cy.operating_income / cy.revenue,
            "rnd_intensity": cy.rnd / cy.revenue,
            "adj_to_net_ratio": cy.adjusted_ebitda / cy.net_income if cy.net_income else 0.0,
            ...}
```

Trend with consistency, and the flat-series edge case:
```python
r2 = 1 - (ss_res / ss_tot) if ss_tot else 1.0
rel = abs(slope) / abs(start)                    # judge slope against the starting level
direction = "flat" if rel < 0.02 else ("improving" if slope > 0 else "deteriorating")
if direction == "flat":
    consistency = "stable"                       # a flat series has no variance to explain
```

Divergence detection — the GAAP cross-check is what makes it a signal:
```python
if prev_val > 0 and curr_val / prev_val >= 1.5:
    gaap_change = gaap[i][1] - gaap[i-1][1]
    # jumped while GAAP did NOT improve -> definition change, not operating change
```

---

## Evidence from the experiment (3 synthetic companies × 5 years, known stories)

All three started at **exactly 5.0% operating margin** and diverged completely:

| | Trajectory | adj/GAAP ratio path | Verdict |
|---|---|---|---|
| **ALPHA** | 5.0% → 15.4%, +2.63%/yr, **r²=1.00** | 3.0x → 1.7x (falling) | genuine structural improvement |
| **BETA** | 5.0% → 5.0%, flat, stable | 2.8x flat | revenue doubled, **no operating leverage** |
| **GAMMA** | 5.0% → 4.5%, −0.11%/yr, noisy | 2.8x → **9.2x** | definition change |

- **ALPHA's falling ratio is the healthy signature:** as the business improves, GAAP profit converges toward the adjusted figure — less and less needs "correcting."
- **GAMMA flagged in 2023:** ratio jumped 3.1x → 6.8x (2.2×) while GAAP net margin **fell** 0.26pp. Looking only at `adjusted_ebitda` (500 → 1,480) would show **196% growth**; actual net income fell 180 → 160. **The metric investors watch told the opposite of reality.** No Ch10 score would catch it — GAMMA's GAAP figures decay slowly and consistently, with no anomaly at all.
- **No false positives:** ALPHA and BETA both scanned clean.
- **Peer benchmark showed why normalization matters:** GAMMA leads on R&D intensity (8.4%) despite spending $680 vs ALPHA's $1,470 — less than half in dollars, more as a share of revenue. Its full profile is coherent: highest R&D intensity, highest leverage (26.8%), lowest margin.

---

## Gotchas / failure patterns

- **`r²` is meaningless on a flat series.** With zero variance the denominator collapses and it returns 0.00, which reads as "erratic" — the exact opposite of the truth. Special-case it.
- **Pasting multi-line commands into PowerShell** can swallow newlines, merging three commands into one nonsense path. Run one line at a time.
- **Function definition order matters.** Python reads top to bottom; a call above its definition raises `NameError`. Keep the run block inside `if __name__ == "__main__":` **at the end of the file**.
- **Never compare non-GAAP metrics across companies** without checking definitions — the name is not the metric.
- **A stable high ratio is not a flag.** Don't let a level-based alarm fire where only a delta-based one is warranted.

---

## What this means for Aleph

Aleph can now take N companies × M years and reach conclusions no single filing contains: who is genuinely improving efficiency (with a consistency measure attached), how peers rank on size-independent ratios, and where a company's own reporting contradicts itself across time. All of it is deterministic Python — the LLM's role remains extraction only. Next: feed it real filings (SEC EDGAR, free) instead of synthetic data, and connect the divergence flag to the Ch10 language-forensics scan so a flagged year automatically triggers a search for the disclosed definition change.

---

## 60-second self-test

1. Why is "Uber spent more on R&D than Lyft" a meaningless comparison, and what's the fix?
2. Two companies both report "Adjusted EBITDA." Why can't you compare them directly?
3. Why won't Beneish M-Score catch a non-GAAP definition change?
4. A company shows a stable 8.0x adjusted/GAAP ratio for five years. Red flag or not — and what *would* warrant checking?
5. What makes a non-GAAP jump a *contradiction* rather than just a large number?

<details>
<summary>Answers</summary>

1. Absolute figures reflect size, not behaviour. Normalize to a ratio — R&D as a percentage of revenue.
2. The name is standardized but the calculation isn't; one may exclude SBC or restructuring costs and the other may not. Compare on GAAP or on metrics you compute yourself.
3. M-Score is built entirely from GAAP financials and never touches non-GAAP metrics, so a redefinition leaves its inputs unchanged. Every tool is blind to what it doesn't measure.
4. Not a red flag — stability means consistent reporting, and capital-heavy businesses legitimately run high ratios. But the *level* warrants reading the reconciliation to see *what* is excluded: real depreciation is fine, recurring "one-time" SBC and restructuring is not.
5. That it jumped while GAAP moved the *opposite* way. A business can't improve and deteriorate at once, so opposing movement has no operating explanation.
</details>
