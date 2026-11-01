"""Offline tests: no PIB website requests are performed."""
import tempfile
import unittest
from datetime import date
from pathlib import Path

from pibcrawler import (
    ArchiveClient, config_load, export_results, normalize_date, parse_callback,
    parse_index, retrieve_window, windows, write_bytes,
)


def page(relid="5928", next_page=None, release_date="22-Dec-2004"):
    next_link = (
        f'<a onclick="getSearchPara({next_page})">Next</a>'
        if next_page is not None else ""
    )
    return (
        '<ul><li><a onclick="Getrelease(' + relid + ', 1)" class="link1">'
        'Languages in the Eighth Schedule'
        f'<p class="feaDate">({release_date}:14:05:00)</p></a></li></ul>'
        + next_link
    )


class FakeClient:
    def __init__(self, by_page):
        self.by_page = by_page
        self.queries = []

    def search_page(self, query, first, last, page_number):
        self.queries.append((query, first, last, page_number))
        payload = self.by_page[page_number]
        return ("0|2|" + payload).encode("utf-8"), payload

    def fetch_original(self, relid, folder):
        path = folder / "originals" / (relid + ".html")
        digest = write_bytes(path, f"<h2>Original {relid}</h2>".encode("utf-8"))
        return "direct_html", str(path.relative_to(folder)), digest, "Ministry of Home Affairs", "ok", ""


class PIBTests(unittest.TestCase):
    def test_index_parser_follows_real_next_anchor(self):
        hits, next_page, empty = parse_index(page(next_page=3))
        self.assertEqual(hits[0]["relid"], "5928")
        self.assertEqual(hits[0]["source_date"], "2004-12-22")
        self.assertEqual(hits[0]["title"], "Languages in the Eighth Schedule")
        self.assertEqual(next_page, 3)
        self.assertFalse(empty)

    def test_index_empty_is_explicit(self):
        self.assertEqual(parse_index("<div>No Record found for this search</div>"),
                         ([], None, True))
        self.assertEqual(parse_index("<div>Unexpected markup</div>"),
                         ([], None, False))

    def test_callback_envelope(self):
        self.assertEqual(parse_callback("0|2|<p>Contains | symbol</p>"),
                         "<p>Contains | symbol</p>")
        with self.assertRaises(ValueError):
            parse_callback("not a callback")

    def test_research_config_and_windows(self):
        cfg = config_load(Path(__file__).resolve().parents[1] / "keywords.yaml")
        self.assertEqual(len(cfg["terms"]), 14)
        self.assertEqual(cfg["end_date"], "2026-10-28")
        self.assertEqual(
            list(windows(date(2024, 1, 30), date(2024, 2, 3), 3)),
            [(date(2024, 1, 30), date(2024, 2, 1)),
             (date(2024, 2, 2), date(2024, 2, 3))],
        )

    def test_metadata_dedup_preserves_each_keyword_hit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = last = date(2004, 12, 22)
            a = {"id": "eighth_schedule", "label": "Eighth Schedule"}
            b = {"id": "language_surveys", "label": "Language survey(s)"}
            retrieve_window(FakeClient({1: page()}), root, a, "Eighth Schedule",
                            1, first, last, 0, False)
            retrieve_window(FakeClient({1: page()}), root, b, "language survey",
                            1, first, last, 0, False)
            summary = export_results(root)
            self.assertEqual(summary["raw_search_occurrences"], 2)
            self.assertEqual(summary["unique_release_ids"], 1)
            self.assertEqual(summary["incomplete_windows"], 0)
            csv_content = (root / "unique_releases.csv").read_text(encoding="utf-8")
            self.assertIn("eighth_schedule", csv_content)
            self.assertIn("language_surveys", csv_content)
            self.assertTrue((root / "terms" / "eighth_schedule").exists())
            self.assertTrue((root / "terms" / "language_surveys").exists())

    def test_pagination_cap_is_not_marked_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = last = date(2004, 12, 22)
            t = {"id": "eighth_schedule", "label": "Eighth Schedule"}
            manifest = retrieve_window(FakeClient({1: page(next_page=3)}), root,
                                       t, "Eighth Schedule", 1, first, last, 1, False)
            self.assertEqual(manifest["search_status"], "partial")
            self.assertIn("page_cap_reached:1", manifest["errors"])

    def test_missing_release_date_not_marked_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = {"id": "tribal_language", "label": "Tribal language"}
            manifest = retrieve_window(FakeClient({1: page(release_date="unknown")}),
                                       Path(tmp), t, "tribal language", 1,
                                       date(2004, 12, 22), date(2004, 12, 22), 0, False)
            self.assertEqual(manifest["search_status"], "partial")
            self.assertIn("missing_listed_date:5928", manifest["errors"])

    def test_normalize_date(self):
        self.assertEqual(normalize_date("(9-Dec-2011:10:00)"), "2011-12-09")


if __name__ == "__main__":
    unittest.main()
