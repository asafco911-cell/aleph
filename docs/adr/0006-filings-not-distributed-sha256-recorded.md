# 0006. The filings are not distributed; the manifest records their sha256

## Context

The project runs against six real SEC 10-K PDFs. A public repository could
ship those files directly so it runs immediately after a clone, or leave
them out and give a way to verify that whatever a reader supplies is the
same document the results were produced from.

## Decision

The filing PDFs are not distributed with the repository (data/*.pdf is
gitignored). data/manifest.json records each filing's sha256, computed once
and committed. data/README.md tells a reader where to get each filing on
EDGAR and how to verify a downloaded copy's hash against the recorded one.

## Alternative rejected

Committing the six PDFs to the repository so it runs immediately after a
clone, with no separate download step.

## What settled it

The recorded hashes are a real integrity guarantee for exactly the six
files these results were produced from - stronger than shipping the files
would be, since a bundled file only proves nothing tampered with it after
the fact, not that it was the right file to begin with. That guarantee has
one honest limit, stated in data/README.md rather than discovered by a
reader's failed hash check: these PDFs were produced by printing EDGAR's
HTML to PDF from a browser, and browser rendering is not deterministic
across versions or engines, so a fresh render of the identical filing will
not reproduce these exact bytes. See #30 for the related, unresolved gap
this decision does not close on its own: nothing in build_manifest.py
compares a freshly computed hash against the one already committed, so a
replaced PDF under an existing doc_id would not be caught by any check
today.
