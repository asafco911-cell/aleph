"""Deterministic document layer: identity, structure, and section extraction.

No LLM touches anything in this package.
"""
from .errors import DocumentError
from .manifest import build_manifest
from .structure import build_sections, extract_section, find_toc_page

__all__ = [
    "DocumentError", "build_manifest", "build_sections",
    "extract_section", "find_toc_page",
]