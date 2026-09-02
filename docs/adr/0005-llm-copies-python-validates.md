# 0005. The LLM copies from one bounded region; everything downstream is deterministic Python

## Context

An LLM extracts data points from unstructured filing text. Some errors it
could make - a wrong number, a fabricated quote, a mismatched column - are
errors later code could also make, if the boundary between what the model
does and what Python checks were drawn differently.

## Decision

The model's role is bounded to copying: one figure at a time, verbatim,
from one region of text Python has already located and handed it. It never
searches for the region, navigates the document, computes a derived value,
or chooses between candidate sources. Every one of those functions is
deterministic Python, and every copied fact passes through Python-written
gates before it is trusted.

## Alternative rejected

Letting the model perform locating, computing, or source-selection itself,
on the reasoning that a capable enough model could be trusted to do so
directly.

## What settled it

The LYFT_FY2025 unit-scale bug. The model correctly quoted the source text,
correctly copied the number, and correctly resolved the column - and still
produced a fact off by a factor of 1,000, because it labelled the value
with the wrong declared unit. That fact passed every gate that existed at
the time - five gates, each correct on its own terms (source present,
quote real, number in quote, rows cross-foot, columns aligned) - because
none of them looked at the unit at all. No gate caught it: a valuation of
$65,792 a share against a $17.35 market price carried no red flag from any
check in the pipeline. It was caught by a person reading a RESULT block,
not by the system. check_unit_matches_source was written afterwards,
specifically so it could not happen again - the response to a wrong answer
with no red flag was a new deterministic check, not a more careful prompt.
