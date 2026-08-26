"""Deterministic document layer: identity, structure, and section extraction.

No LLM touches anything in this package.
"""
from .errors import DocumentError
from .manifest import build_manifest
from .notes import extract_note, find_notes
from .statements import extract_statement, find_statements
from .structure import build_sections, extract_section, find_toc_page

__all__ = [
    "DocumentError", "build_manifest", "build_sections", "extract_section",
    "find_toc_page", "find_notes", "extract_note",
    "find_statements", "extract_statement",
]