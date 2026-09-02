# Filing PDFs

The six 10-K filings this project runs against are not distributed with the
repository. `data/*.pdf` is gitignored; download each filing yourself and
verify it against the sha256 already recorded in `data/manifest.json` before
running the pipeline against it. A hash match is a stronger reproducibility
claim than shipping the PDF itself would be - it proves the exact bytes the
pipeline was built and tested against, rather than asking you to trust that
a bundled file was never altered.

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

Each filing is a public SEC 10-K, retrievable from EDGAR
(https://www.sec.gov/cgi-bin/browse-edgar) or the issuer's own investor
relations site. Place the downloaded file at `data/<expected file name>` and
verify it before running anything against it:

```
python -c "import hashlib; print(hashlib.sha256(open('data/uber_10k.pdf','rb').read()).hexdigest())"
```

Compare the printed hash against the table above. A mismatch means either a
different filing (a 10-K/A amendment, a different fiscal year) or a corrupted
download - not a file this pipeline was built or tested against.

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
