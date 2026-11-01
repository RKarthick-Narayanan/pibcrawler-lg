# PIB keyword corpus: staged implementation plan

**Research period:** 1999-01-01 to 2026-10-28 inclusive.  
**Corpus:** PIB releases returned by 14 independently executed search-term groups.  
**Collection rule:** Preserve *every search occurrence* and its original release before producing a separate metadata-deduplicated export.

## Evidence-backed approach

1. Project Anuvaad's [PIB archive crawler](https://github.com/project-anuvaad/anuvaad-corpus-tools/tree/master/pibarchives-crawler) uses Selenium to select archival dates, obtain release identifiers and then fetch individual `erelcontent.aspx?relid=` resources.
2. [Ujjwal3009/pib-crawler](https://github.com/Ujjwal3009/pib-crawler) shows an ASP.NET callback to `/archive2/AdvSearch.aspx`: an initial GET provides view state; POST `__CALLBACKID=__Page` and `__CALLBACKPARAM=1|SearchText|FromDay|FromMonth|FromYear|ToDay|ToMonth|ToYear|Ministry|SearchType|Page` yields an index; `2|relid|1` yields release content. Its `test_keyword_pagination.py` specifically probes keyword pagination.
3. [nit-in/pib](https://github.com/nit-in/pib) provides an independent Scrapy-based, date-oriented PIB downloader.

These are *code-level precedents*, not a guarantee that the live endpoints work today or cover every historical year. This repository implements only the small request/parse/retrieve pieces needed for our research. No third-party source code is copied.

## Stages and acceptance criteria

- [x] **Stage 0: Source audit and fixed specification.** Record the exact upstream implementation, the 14 term groups and the inclusive date bounds.
- [x] **Stage 1: Safe local implementation.** Build a CLI for small keyword/date probes, per-query raw-response preservation, original HTML/text download, retryable logs, and metadata-only deduplication. Add offline fixtures/tests.
- [ ] **Stage 2: Live probe.** Query `tribal language`, `Eighth Schedule` and `dialect` over *small* windows. Confirm callback response format, first/next page, distinct IDs, source text and publication dates; capture response hashes and failures.
- [ ] **Stage 3: Historical coverage audit.** Test 1999-2001, 2002-2003 and 2004+ separately. Map missing/non-searchable parts to the phase-2 archive, and implement a separate enumerator only when evidence shows it is necessary.
- [ ] **Stage 4: Full retrieval.** Execute each query variant independently across the range, subdividing long windows; independently reconcile reported counts where PIB provides them; resume failures.
- [ ] **Stage 5: Deduplicate.** Create a *new* unique-releases CSV without modifying the raw per-query results or originals; review ambiguous metadata identities.

## Mandatory integrity rules

- A request succeeding with zero hits does **not** prove historical completeness.
- Any unexpected callback, missing pagination, HTTP error or body-fetch failure is logged as unresolved.
- If a user-provided page cap is hit, mark the window `partial`, never `complete`.
- Search-query matches are **source-returned**. Literal verification is a distinct field; PIB's indexing semantics are not assumed.
- The source's publication date, not retrieval date, determines inclusion.
- Store source response hashes, URL, method, request parameters, retrieval time and exact search variant.
- Rate-limit. Respect robots.txt, site restrictions and 429/503 responses. Never bypass access controls.
- Scraper code licensing does not imply permission to republish PIB document bodies.

## Acceptance test for a completed window

A window is marked complete only when we successfully parse every observed results page, establish the end of pagination without loops or truncation, and retain results and request evidence. Original document retrieval has a *separate* success/failure status. No claim of global corpus completeness is made until each archive period has been independently audited.
