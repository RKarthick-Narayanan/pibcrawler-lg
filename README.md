# PIB Language Discourse Crawler

**Purpose:** Discover and download Press Information Bureau releases returned by 14 defined language-related search-term groups. Research period: **1 January 1999 through 28 October 2026**, inclusive. Keep each keyword search independent; deduplicate from metadata only after retrieval.

**Status:** Stage 1, archive-search adapter and offline tests. **No successful live retrieval or exhaustive 1999–2003 coverage has yet been established.** See [PLAN.md](PLAN.md) for the staged acceptance criteria.

## Why this implementation?

We examined the actual source code of existing crawlers rather than inventing a new search protocol.

- [Ujjwal3009/pib-crawler](https://github.com/Ujjwal3009/pib-crawler): `AdvSearch.aspx` ASP.NET callback, query/date parameters, `getSearchPara` pagination, `Getrelease` IDs, and body callbacks. Its `test_keyword_pagination.py` examines keyword-result pagination.
- [Project Anuvaad's PIB Archives crawler](https://github.com/project-anuvaad/anuvaad-corpus-tools/tree/master/pibarchives-crawler): historical date selectors and direct `archive2/erelcontent.aspx?relid=` links.
- [nit-in/pib](https://github.com/nit-in/pib): an independent date-based PIB scraper.

The software is a fresh implementation of publicly documented request patterns. No third-party scraper code was copied. See [NOTICE.md](NOTICE.md).

## Install

Python 3.10 or newer:

```bash
git clone https://github.com/RKarthick-Narayanan/pibcrawler-lg.git
cd pibcrawler-lg
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m unittest discover -s tests -v
```

## Run a limited pilot

**Plan the search locally, with no network:**

```bash
python3 pibcrawler.py run --term tribal_language --start 2024-08-01 --end 2024-08-07 --dry-run
```

**Submit one date-limited query and retrieve its original releases:**

```bash
python3 pibcrawler.py run --term tribal_language --start 2024-08-01 --end 2024-08-07 --output data/pilot
```

**Repeat with the two other pilot terms:**

```bash
python3 pibcrawler.py run --term eighth_schedule --start 2004-12-01 --end 2004-12-31 --output data/pilot
python3 pibcrawler.py run --term dialect --start 2024-08-01 --end 2024-08-07 --output data/pilot
```

To check pagination, add `--max-pages 2`. If a next page exists when that cap is reached, the window is marked **partial**, never complete.

## Full retrieval (not yet validated for all historical years)

After validating the actual source response and 1999–2003 coverage:

```bash
python3 pibcrawler.py run --all --output data/full
python3 pibcrawler.py export --output data/full
```

The YAML file lists 14 term groups; survey plural and hyphenation variants are submitted as independent searches. Default date windows are 7 days; use `--window-days 30` to change them if safe in the pilot. This can involve many thousands of requests. Stop with Ctrl+C, then run the same command to resume already-complete windows. Failures are not silently skipped.

## What is saved?

```text
data/
  terms/<term_id>/vNN_<query>/<start>_<end>/
    raw/search_0001_param_1.txt       # full raw callback response
    originals/<relid>.html            # direct original if valid
    originals/<relid>.callback.txt    # raw source callback fallback
    occurrences.csv                   # keyword-discovery hits, unmerged
    manifest.json                     # pages, errors and status
  raw_results.csv                     # all search occurrences
  unique_releases.csv                 # deduplicated by sourced relid
  coverage.csv                        # per-search completeness
  summary.json
```

The `unique_releases.csv` report retains all matched groups/variants and flags conflicting metadata. Raw occurrences are preserved. The `relid` is taken only from actual search results, never generated or guessed.

## The limits we will not conceal

1. Historical PIB sources include older digitised collections and post-2003 electronic releases. There is **no evidence yet** that `AdvSearch.aspx` indexes every release back to 1999. A zero-hit year is **not** evidence of no government discussion.
2. The ASP.NET callback is undocumented, so its search behaviour and pagination must be verified against saved live responses. `source_returned` is not proof of a literal full-text phrase match.
3. Dates, page counts and original links are extracted conservatively; missing or contradictory values are recorded as unresolved.
4. The crawler uses polite, serial requests with TLS verification. Respect PIB's published access rules, `robots.txt`, throttling and rights. No proxy rotation or access-control bypass is implemented.
5. The repository contains **code**, not a validated corpus or a republication licence for PIB releases.

The research and testing roadmap is in [PLAN.md](PLAN.md).
