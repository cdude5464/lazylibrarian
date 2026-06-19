#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test search result selection and rejection.

import sqlite3

from lazylibrarian.config2 import CONFIG
from lazylibrarian.database import DBConnection
from lazylibrarian.resultlist import _expected_book_language, find_best_result
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
