"""Shared unit-scale vocabulary.

Single source of truth for the scale a unit string names. Three call sites
need to agree on what "thousand" means and must never drift apart:
gates.py verifies a fact's declared unit against its source caption,
bridge.py converts a declared unit to the engine's internal millions, and
assumptions.py checks that the observations feeding one derived quantity
share a scale. One implementation, one place it can be wrong.

Scale is matched on TOKENS within free text, never on an exact string: the
model is free to write "thousands", "USD thousands", or "thousands of
shares" for the same scale, and an exact-match table breaks on the first
phrasing it has not seen.
"""

SCALE_TOKENS = (
    ("billion", 1000.0),
    ("million", 1.0),
    ("thousand", 0.001),
)

# Units that name no scale at all - percentages, ratios, decimals. A
# quantity described this way is dimensionless and exempt from scale
# comparison entirely.
NON_SCALE_MARKERS = ("percent", "%", "decimal", "ratio")


def matching_scales(unit: str) -> list[tuple[str, float]]:
    """Return every (token, scale) whose token appears in the unit string."""
    lowered = unit.lower()
    return [(token, scale) for token, scale in SCALE_TOKENS if token in lowered]


def resolve_scale(unit: str | None) -> float | None:
    """Return the single scale factor a unit names.

    None means: empty, dimensionless (percent/decimal/ratio), names zero
    scale tokens, or names more than one and is therefore ambiguous. None is
    not itself an error signal - callers decide whether an unresolved unit
    blocks, rejects, or is simply not comparable.
    """
    if not unit:
        return None
    lowered = unit.lower()
    if any(marker in lowered for marker in NON_SCALE_MARKERS):
        return None
    matches = matching_scales(unit)
    if len(matches) != 1:
        return None
    return matches[0][1]
