# Source provenance and reuse

This project implements a new, small retriever after examining the following publicly available GitHub work:

- [Project Anuvaad, PIB Archives crawler](https://github.com/project-anuvaad/anuvaad-corpus-tools/tree/master/pibarchives-crawler): date selectors, result ID discovery and direct archival release links. Repository code is MIT-licensed (EkStep-AI, 2020).
- [Ujjwal3009/pib-crawler](https://github.com/Ujjwal3009/pib-crawler): ASP.NET advanced-search callback request and paging patterns, including the keyword pagination diagnostic in `test_keyword_pagination.py`. Used as technical documentation; no code from this repository is copied.
- [nit-in/pib](https://github.com/nit-in/pib): Scrapy date-based collection and release-page extraction pattern.

The implementation is original code adapting known HTTP request patterns and data modelling principles. No third-party scraper code is redistributed here.

**Important:** A GitHub code licence does not establish the licensing or republication rights of PIB release texts or attachments. The tool preserves origin URLs, retrieval evidence and checksums. Researchers must assess the terms and applicable rights before distributing a source corpus.

The current public, undocumented PIB endpoints are not an officially guaranteed API. Source availability and historical indexing coverage require live validation.
