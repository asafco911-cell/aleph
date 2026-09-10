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
`python scripts/build_manifest.py` does not compare against the committed
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
including the `Latest-period basis: 77.08` / `49.06` anchors - were run
against.

That line name matters and this file had it wrong until 2026-09-10: the CLI's
`Value per share` line prints a RANGE (`-14.13 to 77.08` for UBER_FY2024), and
77.08 is what the separate `Latest-period basis` line reports. Quoting the
anchor under the range's label is the point-estimate reading that CLAUDE.md's
seventh settled principle exists to refuse.

```
python -c "import hashlib; print(hashlib.sha256(open('data/uber_10k.pdf','rb').read()).hexdigest())"
```

## No filing is anywhere in git history

This section previously said the opposite, and said it correctly at the
time. `data/uber_10k.pdf` was committed in chapter 2, before the
`data/*.pdf` gitignore rule existed, and `git rm --cached` untracked it
going forward without touching history. Two cache databases were in the
same position. The decision recorded here was to leave them: neither is a
secret, and rewriting a fourteen-chapter commit lineage to scrub two files
would cost more than it fixes.

That decision was reversed on 2026-09-06, immediately before this
repository was first pushed to GitHub, because the cost calculation was
different than it looked. Nothing had been published yet, so a rewrite was
free - no one held the old history. And the claim at stake was not "is
this a secret" but "is what the repository says about itself true":
`docs/adr/0006`, `README.md` and this file all state that the filings are
not distributed here. Pushing with the PDF in history would have made all
three false on the day they became public.

`git filter-repo` removed every `data/*.pdf` and every `aleph_cache.db`
blob from all 84 commits. One commit disappeared - the one whose entire
content was untracking those two files, which became empty. The tracked
file list at HEAD was identical before and after, and `.git` went from
4.2 MB to 674 KB.

Verified from a fresh `git clone` of the public repository, not from the
local copy: `git rev-list --objects --all` matches no `.pdf`, no
`aleph_cache.db` and no `.env`. The commit hashes cited by the old version
of this section no longer exist in this history - every SHA changed, which
is what a rewrite means.

Neither statement was ever about secrecy. The PDFs are public SEC filings
and the cache holds LLM responses to that same public text. It is about a
repository whose entire argument is that a documented guarantee should be
enforced, not merely asserted.
