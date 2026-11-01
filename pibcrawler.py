#!/usr/bin/env python3
"""Auditable, keyword-first PIB archive retriever.

Method: ASP.NET advanced-search callback documented in Ujjwal3009/pib-crawler,
with source-page retrieval informed by project-anuvaad/anuvaad-corpus-tools.
Independent implementation; no upstream source copied.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
import yaml
from bs4 import BeautifulSoup

SEARCH_URL = "https://archive.pib.gov.in/archive2/AdvSearch.aspx"
RELEASE_URL = "https://archive.pib.gov.in/archive2/erelcontent.aspx?relid="
FIELDS = [
    "term_id", "term_label", "query", "window_start", "window_end", "page",
    "relid", "title", "source_date", "ministry", "source_url", "retrieval_method",
    "original_path", "sha256", "download_status", "error",
]
USER_AGENT = "PIB-Language-Corpus/0.1 (public scholarly research; polite serial retrieval)"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_bytes(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(data)
    temp.replace(path)
    return sha256(data)


def write_json(path: Path, obj: dict) -> None:
    write_bytes(path, (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temp.replace(path)


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def safe_segment(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return value[:65] or "empty"


def normalize_date(text: str) -> str:
    text = (text or "").strip(" ()\t\n")
    match = re.search(r"\d{1,2}-[A-Za-z]{3}-\d{4}", text)
    if match:
        try:
            return datetime.strptime(match.group(), "%d-%b-%Y").date().isoformat()
        except ValueError:
            pass
    match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", text)
    return match.group() if match else ""


def parse_callback(response: str) -> str:
    # PIB responds with status|type|HTML; the HTML itself may contain pipes.
    parts = response.split("|", 2)
    if len(parts) != 3 or parts[0].strip() != "0":
        raise ValueError("Unexpected ASP.NET callback envelope: " + response[:100])
    if not parts[2].strip():
        raise ValueError("Empty callback content")
    return parts[2]


def parse_index(markup: str) -> tuple[list[dict], int | None, bool]:
    """Extract actual Getrelease IDs and the *linked* next-page callback.

    Boolean indicates an explicit 'no records' message, not completeness.
    """
    soup = BeautifulSoup(markup, "html.parser")
    entries = []
    for anchor in soup.find_all("a"):
        action = (anchor.get("onclick") or "") + " " + (anchor.get("href") or "")
        found = re.search(r"Getrelease\s*\(\s*(\d+)\s*,\s*\d+\s*\)", action, re.I)
        if not found:
            continue
        relid = found.group(1)
        date_tag = anchor.find(class_=re.compile("feaDate", re.I))
        date_text = date_tag.get_text(" ", strip=True) if date_tag else ""
        if not date_text:
            date_text = anchor.get_text(" ", strip=True)
        title = anchor.get_text(" ", strip=True)
        if date_tag:
            title = title.replace(date_tag.get_text(" ", strip=True), "").strip()
        entries.append({"relid": relid, "title": title, "source_date": normalize_date(date_text)})
    next_page = None
    for tag in soup.find_all(["a", "input", "button"]):
        raw_action = (tag.get("onclick") or "") + " " + (tag.get("href") or "")
        label = tag.get_text(" ", strip=True) or tag.get("value") or tag.get("title") or ""
        if not re.search(r"\bnext\b", label, re.I):
            continue
        match = re.search(r"getSearchPara\s*\(\s*(\d+)\s*\)", raw_action, re.I)
        if match:
            next_page = int(match.group(1))
            break
    empty = bool(re.search(r"no\s+records?\s+found", soup.get_text(" ", strip=True), re.I))
    return entries, next_page, empty


def parse_release_html(markup: str) -> tuple[str, str]:
    soup = BeautifulSoup(markup, "html.parser")
    region = soup.select_one("div.contentdiv, div.innner-page-main-about-us-content-right-part")
    if region is None:
        return "", ""
    ministry_el = soup.select_one("div.content-ministry")
    ministry = ministry_el.get_text(" ", strip=True) if ministry_el else ""
    return region.get_text("\n", strip=True), ministry


def config_load(path: Path) -> dict:
    obj = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict) or not isinstance(obj.get("terms"), list):
        raise ValueError("Invalid YAML: expected 'terms' list")
    ids = [term["id"] for term in obj["terms"]]
    if len(set(ids)) != len(ids) or any(not term.get("variants") for term in obj["terms"]):
        raise ValueError("Each term requires a unique ID and nonempty variants")
    first, last = date.fromisoformat(obj["start_date"]), date.fromisoformat(obj["end_date"])
    if first > last:
        raise ValueError("Start date after end date")
    return obj


def windows(first: date, last: date, days: int):
    if days < 1:
        raise ValueError("--window-days must be positive")
    cursor = first
    while cursor <= last:
        until = min(last, cursor + timedelta(days=days - 1))
        yield cursor, until
        cursor = until + timedelta(days=1)


class ArchiveClient:
    def __init__(self, delay: float = 1.5, timeout: int = 30):
        self.delay = delay
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.viewstate = None
        self.generator = ""
        self.eventvalidation = ""
        self.last_call = 0.0

    def request(self, method: str, url: str, **kw) -> requests.Response:
        wait = self.delay - (time.monotonic() - self.last_call)
        if wait > 0:
            time.sleep(wait)
        try:
            response = self.session.request(method, url, timeout=self.timeout, **kw)
        finally:
            self.last_call = time.monotonic()
        # Fail closed: no proxy circumvention, disabled TLS, or forced retries.
        response.raise_for_status()
        return response

    def initialize(self) -> None:
        response = self.request("GET", SEARCH_URL)
        soup = BeautifulSoup(response.text, "html.parser")
        def val(name):
            tag = soup.find("input", attrs={"name": name}) or soup.find("input", id=name)
            return (tag.get("value") or "") if tag else ""
        self.viewstate = val("__VIEWSTATE")
        self.generator = val("__VIEWSTATEGENERATOR")
        self.eventvalidation = val("__EVENTVALIDATION")
        if not self.viewstate:
            raise RuntimeError("PIB page did not expose __VIEWSTATE; search not verified")

    def callback(self, param: str) -> tuple[bytes, str]:
        if self.viewstate is None:
            self.initialize()
        fields = {
            "__CALLBACKID": "__Page",
            "__CALLBACKPARAM": param,
            "__VIEWSTATE": self.viewstate,
            "__VIEWSTATEGENERATOR": self.generator,
        }
        if self.eventvalidation:
            fields["__EVENTVALIDATION"] = self.eventvalidation
        response = self.request("POST", SEARCH_URL, data=fields)
        return response.content, parse_callback(response.text)

    def search_page(self, query: str, first: date, last: date, page: int) -> tuple[bytes, str]:
        if "|" in query:
            raise ValueError("Pipe is not supported in PIB callback search phrases")
        param = (
            f"1|{query}|{first.day}|{first.month}|{first.year}|"
            f"{last.day}|{last.month}|{last.year}|0|2|{page}"
        )
        return self.callback(param)

    def fetch_original(self, relid: str, folder: Path) -> tuple[str, str, str, str, str, str]:
        """Return (method, relative_file, checksum, ministry, status, error).

        Try Anuvaad's direct release endpoint; if it fails, preserve the
        advanced-search content callback (not mislabelled as direct HTML).
        """
        source_url = RELEASE_URL + relid
        failures = []
        try:
            resp = self.request("GET", source_url)
            body, ministry = parse_release_html(resp.text)
            if len(body) < 25:
                raise ValueError("Direct page did not contain a recognizable release body")
            path = folder / "originals" / (relid + ".html")
            checksum = write_bytes(path, resp.content)
            return "direct_html", str(path.relative_to(folder)), checksum, ministry, "ok", ""
        except (requests.RequestException, ValueError) as e:
            failures.append("direct: " + str(e))
        try:
            raw, content = self.callback("2|" + relid + "|1")
            # The callback often returns header|body, preserve the entire original response.
            chunks = content.split("|", 1)
            header = chunks[0].strip() if len(chunks) == 2 else ""
            body_html = chunks[1] if len(chunks) == 2 else content
            soup = BeautifulSoup(body_html, "html.parser")
            if len(soup.get_text(" ", strip=True)) < 25:
                raise ValueError("Callback returned no recognizable release body")
            path = folder / "originals" / (relid + ".callback.txt")
            checksum = write_bytes(path, raw)
            ministry = re.split(r"\s+\d{1,2}[- ](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)", header, maxsplit=1, flags=re.I)[0]
            return "body_callback", str(path.relative_to(folder)), checksum, ministry, "ok", "; ".join(failures)
        except (requests.RequestException, ValueError) as e:
            failures.append("callback: " + str(e))
        return "", "", "", "", "failed", "; ".join(failures)


def retrieve_window(client: ArchiveClient, root: Path, term: dict, query: str,
                    variant_index: int, first: date, last: date, max_pages: int,
                    resume: bool) -> dict:
    folder = (root / "terms" / term["id"] /
              f"v{variant_index:02d}_{safe_segment(query)}" /
              f"{first.isoformat()}_{last.isoformat()}")
    folder.mkdir(parents=True, exist_ok=True)
    manifest_path = folder / "manifest.json"
    if resume and manifest_path.exists():
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        if old.get("search_status") == "complete" and old.get("documents_status") == "complete":
            return {"skipped": True, "manifest": str(manifest_path)}
    entries, errors, page_key, pages, visited = [], [], 1, 0, set()
    while page_key is not None:
        if page_key in visited:
            errors.append(f"pagination_loop:{page_key}")
            break
        if max_pages and pages >= max_pages:
            errors.append(f"page_cap_reached:{max_pages}")
            break
        visited.add(page_key)
        pages += 1
        try:
            raw, markup = client.search_page(query, first, last, page_key)
            write_bytes(folder / "raw" / f"search_{pages:04d}_param_{page_key}.txt", raw)
            hits, following, explicit_empty = parse_index(markup)
            if not hits and not explicit_empty:
                raise ValueError("No Getrelease links and no explicit no-records message")
            for hit in hits:
                entries.append({
                    "term_id": term["id"], "term_label": term["label"],
                    "query": query, "window_start": first.isoformat(),
                    "window_end": last.isoformat(), "page": pages,
                    "relid": hit["relid"], "title": hit["title"],
                    "source_date": hit["source_date"], "ministry": "",
                    "source_url": RELEASE_URL + hit["relid"],
                    "retrieval_method": "", "original_path": "",
                    "sha256": "", "download_status": "not_attempted", "error": "",
                })
            page_key = following
        except (requests.RequestException, ValueError, RuntimeError) as e:
            errors.append(f"search_page_{pages}:{type(e).__name__}:{e}")
            break
    # Duplicate IDs across separate result pages indicate potentially broken pagination.
    ids = [entry["relid"] for entry in entries]
    if len(ids) != len(set(ids)):
        errors.append("duplicate_relid_within_query_window")
    body_cache = {}
    for entry in entries:
        rid = entry["relid"]
        if rid not in body_cache:
            body_cache[rid] = client.fetch_original(rid, folder)
        method, relpath, checksum, ministry, status, error = body_cache[rid]
        entry.update(retrieval_method=method, original_path=relpath,
                     sha256=checksum, ministry=ministry, download_status=status,
                     error=error)
        if entry["source_date"] and not (first.isoformat() <= entry["source_date"] <= last.isoformat()):
            entry["error"] += "; listed_date_outside_requested_window"
            errors.append("listed_date_outside_requested_window:" + rid)
        elif not entry["source_date"]:
            entry["error"] += "; missing_listed_date"
            errors.append("missing_listed_date:" + rid)
    write_csv(folder / "occurrences.csv", entries, FIELDS)
    search_status = "complete" if not errors else "partial"
    documents_status = ("complete" if all(x["download_status"] == "ok" for x in entries)
                        else "partial")
    manifest = {
        "term_id": term["id"], "query": query,
        "window_start": first.isoformat(), "window_end": last.isoformat(),
        "searched_at": utc_now(), "source_search_url": SEARCH_URL,
        "source_release_url_pattern": RELEASE_URL + "{relid}",
        "method": "ASP.NET __Page callback", "pages": pages,
        "hits": len(entries), "distinct_relids_in_window": len(set(ids)),
        "downloaded": sum(x["download_status"] == "ok" for x in entries),
        "search_status": search_status, "documents_status": documents_status,
        "errors": sorted(set(errors)),
        "historical_coverage_verified": False,
        "note": "Search completion is only pagination termination, not proof of historical indexing coverage.",
    }
    write_json(manifest_path, manifest)
    return manifest


def export_results(root: Path) -> dict:
    rows, statuses = [], []
    for path in sorted((root / "terms").glob("**/occurrences.csv")):
        rows.extend(read_csv(path))
    for path in sorted((root / "terms").glob("**/manifest.json")):
        statuses.append(json.loads(path.read_text(encoding="utf-8")))
    write_csv(root / "raw_results.csv", rows, FIELDS)
    merged: dict[str, dict] = {}
    for row in rows:
        # No guessed identifiers: only IDs actually returned by PIB.
        key = "pib_archive:relid:" + row["relid"] if row["relid"] else row["source_url"]
        existing = merged.setdefault(key, {
            "identity": key, "relid": row["relid"], "title": row["title"],
            "source_date": row["source_date"], "ministry": row["ministry"],
            "source_url": row["source_url"], "search_groups": set(),
            "query_variants": set(), "search_occurrences": 0, "conflict": False,
        })
        for field in ("title", "source_date", "ministry", "source_url"):
            if row[field] and existing[field] and row[field] != existing[field]:
                existing["conflict"] = True
            if row[field] and not existing[field]:
                existing[field] = row[field]
        existing["search_groups"].add(row["term_id"])
        existing["query_variants"].add(row["query"])
        existing["search_occurrences"] += 1
    canonical = []
    for rec in merged.values():
        rec["search_groups"] = "; ".join(sorted(rec["search_groups"]))
        rec["query_variants"] = "; ".join(sorted(rec["query_variants"]))
        canonical.append(rec)
    unique_fields = ["identity", "relid", "title", "source_date", "ministry",
                     "source_url", "search_groups", "query_variants",
                     "search_occurrences", "conflict"]
    write_csv(root / "unique_releases.csv", canonical, unique_fields)
    write_csv(root / "coverage.csv", statuses, [
        "term_id", "query", "window_start", "window_end", "pages", "hits",
        "distinct_relids_in_window", "downloaded", "search_status", "documents_status",
        "historical_coverage_verified", "errors",
    ])
    summary = {"raw_search_occurrences": len(rows), "unique_release_ids": len(canonical),
               "window_manifests": len(statuses),
               "incomplete_windows": sum(x["search_status"] != "complete" or
                                         x["documents_status"] != "complete" for x in statuses),
               "historical_coverage_verified": False}
    write_json(root / "summary.json", summary)
    return summary


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="PIB keyword-first corpus retriever")
    commands = p.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Search terms and download discovered releases")
    run.add_argument("--config", type=Path, default=Path("keywords.yaml"))
    run.add_argument("--output", type=Path, default=Path("data"))
    target = run.add_mutually_exclusive_group(required=True)
    target.add_argument("--term", help="A term ID from YAML, e.g. tribal_language")
    target.add_argument("--all", action="store_true", help="Explicitly request all 14 groups")
    run.add_argument("--start", help="ISO date, inclusive (default from YAML)")
    run.add_argument("--end", help="ISO date, inclusive (default from YAML)")
    run.add_argument("--window-days", type=int, default=7)
    run.add_argument("--max-pages", type=int, default=0, help="Pilot cap, 0 unlimited; hitting it marks partial")
    run.add_argument("--max-windows", type=int, default=0, help="Pilot cap, 0 unlimited")
    run.add_argument("--delay", type=float, default=1.5)
    run.add_argument("--dry-run", action="store_true", help="Print planned queries, no network")
    run.add_argument("--no-resume", action="store_true")
    exp = commands.add_parser("export", help="Write separate raw and metadata-deduplicated CSVs")
    exp.add_argument("--output", type=Path, default=Path("data"))
    args = p.parse_args(argv)
    if args.command == "export":
        summary = export_results(args.output)
        print(json.dumps(summary, indent=2))
        return 0 if summary["incomplete_windows"] == 0 else 2
    cfg = config_load(args.config)
    first = date.fromisoformat(args.start or cfg["start_date"])
    last = date.fromisoformat(args.end or cfg["end_date"])
    if first > last or first < date.fromisoformat(cfg["start_date"]) or last > date.fromisoformat(cfg["end_date"]):
        p.error("Requested dates must lie inside the configured research period")
    if args.delay < 0 or args.max_pages < 0 or args.max_windows < 0:
        p.error("Delay and caps must be non-negative")
    selected = [term for term in cfg["terms"] if args.all or term["id"] == args.term]
    if not selected:
        p.error("Unknown term ID: " + str(args.term))
    tasks = [(term, query, i, start, end)
             for term in selected for i, query in enumerate(term["variants"], 1)
             for start, end in windows(first, last, args.window_days)]
    if args.max_windows:
        tasks = tasks[:args.max_windows]
    if args.dry_run:
        for term, query, i, start, end in tasks:
            print(f"{term['id']}\t{query}\t{start}\t{end}")
        print(f"{len(tasks)} query windows planned; no network")
        return 0
    client = ArchiveClient(delay=args.delay)
    failed = False
    for idx, (term, query, i, start, end) in enumerate(tasks, 1):
        print(f"[{idx}/{len(tasks)}] {term['id']}: {query!r} {start}..{end}", flush=True)
        result = retrieve_window(client, args.output, term, query, i, start, end,
                                 args.max_pages, resume=not args.no_resume)
        if not result.get("skipped"):
            if result["search_status"] != "complete" or result["documents_status"] != "complete":
                failed = True
                print("  INCOMPLETE: " + "; ".join(result["errors"]), file=sys.stderr)
            else:
                print(f"  {result['hits']} hits; {result['downloaded']} originals")
    summary = export_results(args.output)
    print(json.dumps(summary, indent=2))
    return 2 if failed or summary["incomplete_windows"] else 0


if __name__ == "__main__":
    sys.exit(main())
