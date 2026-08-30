#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test search result selection and rejection.

import sqlite3
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from lazylibrarian import downloadmethods, qbittorrent, resultlist
from lazylibrarian.config2 import CONFIG
from lazylibrarian.database import DBConnection
from lazylibrarian.resultlist import _expected_book_language, download_result, find_best_result
from unittests.unittesthelpers import LLTestCaseWithStartup


class ResultListMatchingTest(LLTestCaseWithStartup):
    def setUp(self):
        super().setUp()
        self.db = DBConnection()
        self.db.action("DELETE FROM wanted")

    def tearDown(self):
        self.db.close()
        super().tearDown()

    @staticmethod
    def _keeper_book():
        return {
            "library": "eBook",
            "bookid": "s0ZPEQAAQBAJ",
            "bookName": "The Keeper",
            "bookSub": "Part 1",
            "authorName": "Robert Cain",
            "searchterm": "Robert Cain The Keeper: Part 1",
        }

    @staticmethod
    def _direct_result(title, url="abcdef1234"):
        return {
            "tor_title": title,
            "tor_url": url,
            "tor_prov": "annas",
            "tor_size": 1048576,
            "tor_type": "direct",
            "priority": 5,
        }

    @staticmethod
    def _torrent_result(title, provider="bibliotik", url="http://example.com/torrent"):
        return {
            "tor_title": title,
            "tor_url": url,
            "tor_prov": provider,
            "tor_size": 1048576,
            "tor_type": "torrent",
            "priority": 50,
        }

    def test_ebook_result_rejects_weak_author_subset_title(self):
        match = find_best_result(
            [self._direct_result("Scott-Norton, Robert The Remnant Keeper.epub")],
            self._keeper_book(),
            "book",
            "direct",
        )

        self.assertIsNone(match)

    def test_ebook_result_accepts_matching_author_and_title(self):
        match = find_best_result(
            [self._direct_result("Cain, Robert - The Keeper.epub")],
            self._keeper_book(),
            "book",
            "direct",
        )

        self.assertIsNotNone(match)
        self.assertGreaterEqual(match[0], CONFIG.get_int("MATCH_RATIO"))
        self.assertEqual("Cain, Robert - The Keeper.epub", match[1]["NZBtitle"])

    def test_ebook_result_rejects_explicit_wrong_language(self):
        book = self._keeper_book()
        book["BookLang"] = "eng"
        result = self._direct_result("Cain, Robert - The Keeper.epub")
        result["tor_lang"] = "it"

        match = find_best_result([result], book, "book", "direct")

        self.assertIsNone(match)

    def test_ebook_result_accepts_matching_expected_language(self):
        book = self._keeper_book()
        book["BookLang"] = "ita"
        result = self._direct_result("Cain, Robert - The Keeper.epub")
        result["tor_lang"] = "it"

        match = find_best_result([result], book, "book", "direct")

        self.assertIsNotNone(match)
        self.assertEqual("Cain, Robert - The Keeper.epub", match[1]["NZBtitle"])

    def test_expected_book_language_accepts_sqlite_row(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE books (BookLang TEXT)")
        conn.execute("INSERT INTO books VALUES (?)", ("eng",))
        row = conn.execute("SELECT BookLang FROM books").fetchone()

        class RowDb:
            @staticmethod
            def match(_query, _params):
                return row

        self.assertEqual("eng", _expected_book_language(RowDb(), {"bookid": "x"}))

    def test_ebook_result_rejects_bibliotik_title_only_subset_title(self):
        result = self._torrent_result("The Remnant Keeper.epub")
        result["booksearch"] = "bibliotik"

        match = find_best_result([result], self._keeper_book(), "book", "tor")

        self.assertIsNone(match)

    def test_ebook_result_does_not_hard_reject_title_only_classic_edition_suffix(self):
        book = {
            "library": "eBook",
            "bookid": "classic-east-of-eden",
            "bookName": "East of Eden",
            "bookSub": "",
            "authorName": "John Steinbeck",
            "searchterm": "John Steinbeck East of Eden",
        }

        match = find_best_result(
            [self._direct_result("East of Eden Penguin Classics.epub", url="abcdef5678")],
            book,
            "book",
            "direct",
        )

        self.assertIsNotNone(match)
        self.assertEqual("East of Eden Penguin Classics.epub", match[1]["NZBtitle"])

    def test_ebook_result_accepts_bibliotik_classic_edition_suffix(self):
        book = {
            "library": "eBook",
            "bookid": "classic-east-of-eden",
            "bookName": "East of Eden",
            "bookSub": "",
            "authorName": "John Steinbeck",
            "searchterm": "John Steinbeck East of Eden",
        }
        result = self._torrent_result("East of Eden Penguin Classics.epub")
        result["booksearch"] = "bibliotik"

        match = find_best_result([result], book, "book", "tor")

        self.assertIsNotNone(match)
        self.assertGreaterEqual(match[0], CONFIG.get_int("MATCH_RATIO"))

    def test_ebook_result_rejects_edition_phrase_inside_title(self):
        result = self._torrent_result("The Keeper of the Modern Library.epub")
        result["booksearch"] = "bibliotik"

        match = find_best_result([result], self._keeper_book(), "book", "tor")

        self.assertIsNone(match)

    def test_qbit_post_add_rejection_emits_mandatory_helper_spool_with_reason(self):
        book_id = "box-helper-rejected-book"
        author_id = "box-helper-author"
        magnet = "magnet:?xt=urn:btih:" + "a" * 40
        self.db.upsert(
            "authors",
            {"AuthorName": "Expected Author", "Status": "Paused"},
            {"AuthorID": author_id},
        )
        self.db.upsert(
            "books",
            {
                "AuthorID": author_id,
                "BookName": "Expected Book",
                "Status": "Wanted",
                "AudioStatus": "Skipped",
            },
            {"BookID": book_id},
        )

        class Setting:
            def __init__(self, value):
                self.value = value

        class Provider(dict):
            def get_item(self, key):
                return Setting({"SEED_RATIO": 0, "SEED_DURATION": 20160}[key])

        class DownloadConfig:
            @staticmethod
            def get_bool(key):
                return key == "TOR_DOWNLOADER_QBITTORRENT"

            @staticmethod
            def providers(_kind):
                return [Provider(NAME="ABT", DISPNAME="ABT", HOST="ABT")]

            @staticmethod
            def __getitem__(key):
                return {
                    "QBITTORRENT_HOST": "qbit",
                    "REJECT_WORDS": "",
                }.get(key, "")

        new_value = {
            "BookID": book_id,
            "NZBtitle": "Expected Book",
            "NZBdate": "2026-08-30 12:00:00",
            "NZBprov": "ABT",
            "Status": "Wanted",
            "NZBsize": 1000,
            "AuxInfo": "eBook",
            "NZBmode": "magnet",
        }
        match = [100, new_value, {"NZBurl": magnet}, 1]
        book = {"authorName": "Expected Author", "bookName": "Expected Book"}
        with tempfile.TemporaryDirectory() as temp:
            def add_after_intent(*_args, **_kwargs):
                existing = [
                    json.loads(path.read_text(encoding="utf-8"))
                    for path in Path(temp).glob("*.json")
                ]
                self.assertEqual(len(existing), 1)
                self.assertEqual(existing[0]["ll_handoff_phase"], "intent")
                return True, ""

            with (
            patch.dict(os.environ, {"BOX_LL_SPOOL_DIR": temp}),
            patch.object(downloadmethods, "CONFIG", DownloadConfig()),
            patch.object(qbittorrent, "add_torrent", side_effect=add_after_intent),
            patch.object(qbittorrent, "get_name", return_value="Wrong Author - Wrong Book"),
            patch.object(qbittorrent, "preserve_rejected_torrent", return_value=True) as preserve,
            patch.object(downloadmethods, "check_contents", return_value="embedded title mismatch"),
            patch.object(resultlist, "custom_notify_snatch") as optional_notifier,
            patch.object(resultlist, "notify_snatch"),
            patch.object(resultlist, "schedule_job"),
            ):
                outcome = download_result(match, book)
                spool = {
                    item["ll_handoff_phase"]: item
                    for item in (
                        json.loads(path.read_text(encoding="utf-8"))
                        for path in Path(temp).glob("*.json")
                    )
                }

        self.assertEqual(outcome, 2)
        self.assertEqual(set(spool), {"intent", "final"})
        self.assertEqual(spool["intent"]["ll_download_id"], "a" * 40)
        self.assertEqual(spool["final"]["ll_provider"], "ABT")
        self.assertEqual(
            spool["final"]["ll_pre_rejected_reason"], "embedded title mismatch"
        )
        self.assertEqual(
            spool["final"]["ll_handoff_protocol"],
            downloadmethods.BOX_HELPER_HANDOFF_PROTOCOL,
        )
        preserve.assert_called_once_with("a" * 40, {"seed_duration": 20160})
        optional_notifier.assert_called_once_with(f"{book_id} eBook")
        wanted = self.db.match(
            "SELECT Status,Source,DownloadID,DLResult FROM wanted WHERE BookID=? AND NZBurl=?",
            (book_id, magnet),
        )
        self.assertEqual(wanted["Status"], "Snatched")
        self.assertEqual(wanted["Source"], "QBITTORRENT")
        self.assertEqual(wanted["DownloadID"], "a" * 40)
        self.assertTrue(wanted["DLResult"].startswith(downloadmethods.PRE_REJECTED_PREFIX))
