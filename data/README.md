# Filing PDFs

The six 10-K filings this project runs against are not distributed with the
repository. `data/*.pdf` is gitignored. Get each filing from SEC EDGAR at
the source below, place it at `data/<expected file name>`, and read
"Verifying a downloaded filing" further down before assuming a hash mismatch
means something is broken - for these specific files, it does not.

| doc_id | company | fiscal year | form | expected file name | sha256 |
|---|---|---|---|---|---|
| UBER_FY2025 | Uber Technologies, Inc. | 2025 | 10-K | `uber_10k.pdf` | `6e4603267ea61dc39a9a6c63e2b261660854db4fc04fd3b7fa1c719aaf732051` |
| UBER_FY2024 | Uber Technologies, Inc. | 2024 | 10-K | `uber_10k_fy2024.pdf` | `ab5f074a0afc29ad8b0ab365a83e4bc6dc5781feacc16c2062ada10ffb759920` |
| LYFT_FY2025 | Lyft, Inc. | 2025 | 10-K | `lyft_10k_fy2025.pdf` | `b092c0fff438fead68ae6b7937d7422025a90a7e77fdc93c15d679478682d152` |
| LYFT_FY2024 | Lyft, Inc. | 2024 | 10-K | `lyft_10k_fy2024.pdf` | `d71c688050046303c091906340bf09618f5122feb38e4650e37de3c23ebd842e` |
| DASH_FY2025 | DoorDash, Inc. | 2025 | 10-K | `dash_10k_fy2025.pdf` | `9c25e4edbf057b38b8aa0abe6d33513ee83ebd892672fc29eda42594de59f7de` |
| DASH_FY2024 | DoorDash, Inc. | 2024 | 10-K | `dash_10k_fy2024.pdf` | `57ee0a61ef4a7d72f7e335fad0e95347c53d81a361df8b4bdcc83c13d259e624` |

`UBER_FY2025`'s expected file name is `uber_10k.pdf`, not `uber_10k_fy2025.pdf`
- historically misnamed in chapter 2, before FY2024 or a second filer existed
to disambiguate against, and left as-is since `doc_id` is the interface the
pipeline resolves by, never the file name (see the "eight settled principles"
in `CLAUDE.md`).

## Source on EDGAR

Each filing below is the original 10-K, not an amendment - `manifest.py`
rejects 10-K/A filings outright, and DoorDash in particular has one on file
(filed 2026-05-06) that is not the document this project uses. The index
page lists every exhibit; the primary document is the 10-K itself.

| doc_id | CIK | accession number | index page |
|---|---|---|---|
| UBER_FY2025 | 1543151 | 0001543151-26-000015 | [index](https://www.sec.gov/Archives/edgar/data/1543151/000154315126000015/0001543151-26-000015-index.htm), primary doc `uber-20251231.htm` |
| UBER_FY2024 | 1543151 | 0001543151-25-000008 | [index](https://www.sec.gov/Archives/edgar/data/1543151/000154315125000008/0001543151-25-000008-index.htm), primary doc `uber-20241231.htm` |
| LYFT_FY2025 | 1759509 | 0001628280-26-006960 | [index](https://www.sec.gov/Archives/edgar/data/1759509/000162828026006960/0001628280-26-006960-index.htm), primary doc `lyft-20251231.htm` |
| LYFT_FY2024 | 1759509 | 0001759509-25-000025 | [index](https://www.sec.gov/Archives/edgar/data/1759509/000175950925000025/0001759509-25-000025-index.htm), primary doc `lyft-20241231.htm` |
| DASH_FY2025 | 1792789 | 0001792789-26-000013 | [index](https://www.sec.gov/Archives/edgar/data/1792789/000179278926000013/0001792789-26-000013-index.htm), primary doc `dash-20251231.htm` |
| DASH_FY2024 | 1792789 | 0001628280-25-005715 | [index](https://www.sec.gov/Archives/edgar/data/1792789/000162828025005715/0001628280-25-005715-index.htm), primary doc `dash-20241231.htm` |

Or browse from each company's EDGAR filing history: CIK 1543151 (Uber),
1759509 (Lyft), 1792789 (DoorDash), at
`https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=<CIK>&type=10-K`.

## Verifying a downloaded filing

The sha256 in the table above identifies the exact six PDF files this
project's results were produced from - a real integrity guarantee for
anyone who is given these specific files, since a byte changed anywhere
changes the hash. **It will not match a fresh download from EDGAR.**

These PDFs were produced by printing EDGAR's HTML filing to PDF from
Microsoft Edge, and that rendering is not deterministic: a different
browser version, a different rendering engine (Chrome, Firefox, a
command-line tool), or different page/margin settings all produce a
different PDF - different bytes, different embedded fonts, different page
breaks - from the identical underlying filing text. A hash comparison
would fail for the first person who tries it, for a reason that has
nothing to do with getting the wrong document.

So: get the filing from the EDGAR link above, render it to PDF however you
choose, and expect its hash to differ from the table. That is not a sign
of a broken pipeline or the wrong filing - it is a rendering artifact.
`python scripts\build_manifest.py` does not compare against the committed
hash at all; it computes whatever hash your PDF happens to have and writes
it straight into `data/manifest.json`, overwriting the recorded one,
without warning. Confirmed by reading `_sha256` and `build_manifest` in
`src/aleph/documents/manifest.py`: nothing there reads the old value before
writing the new one. A hash "mismatch" is not a failure state this pipeline
detects or blocks on - it is simply what a fresh `data/manifest.json` will
say after you build it locally.

What the hash is actually good for: if you are handed the six PDFs
directly (rather than rendering your own), verifying against this table
confirms you have the identical files this project's committed results -
including the `Value per share: 77.08` / `49.06` anchors - were run
against.

```
python -c "import hashlib; print(hashlib.sha256(open('data/uber_10k.pdf','rb').read()).hexdigest())"
```

## data/uber_10k.pdf is still in git history

The gitignore rule for `data/*.pdf` was added after `data/uber_10k.pdf` was
first committed (chapter 2, `24454c7`), so it does not retroactively remove
the file from history - only from future commits. The same is true of
`experiments/ch12_production/aleph_cache.db` (chapter 12, `a3a9be5`), now
covered by a gitignore rule broad enough to match a cache database at any
depth in the tree, not only under `data/`.

Both were untracked going forward (`git rm --cached`), but history was
deliberately **not** rewritten to remove them. This repository's commit
lineage across fourteen course chapters is part of what it demonstrates -
rewriting it to scrub two files would cost more than it fixes. Neither file
contains a secret: the PDF is a public SEC filing, and the cache database is
a content-addressed store of LLM responses to that same public text.
