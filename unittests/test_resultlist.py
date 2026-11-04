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

    def test_series_display_suffix_does_not_hide_exact_ebook(self):
        book = {
            "library": "eBook", "bookid": "68427",
            "bookName": "Elantris (Elantris, #1)", "bookSub": "",
            "authorName": "Brandon Sanderson", "searchterm": "Brandon Sanderson Elantris",
        }
        result = self._torrent_result(
            "Brandon Sanderson - Elantris - 01 - Elantris - epub",
            provider="http://jackett:9117/jackett/api/v2.0/indexers/abtorrents/results/torznab")
        match = find_best_result([result], book, "book", "tor")
        self.assertIsNotNone(match)
        self.assertGreaterEqual(match[0], CONFIG.get_int("MATCH_RATIO"))

    def test_decimal_series_position_is_not_part_of_work_title(self):
        book = {
            "library": "eBook", "bookid": "34703445",
            "bookName": "Edgedancer (The Stormlight Archive, #2.5)", "bookSub": "",
            "authorName": "Brandon Sanderson", "searchterm": "Brandon Sanderson Edgedancer",
        }
        result = self._torrent_result("Brandon Sanderson - Edgedancer - epub")
        match = find_best_result([result], book, "book", "tor")
        self.assertIsNotNone(match)
        self.assertGreaterEqual(match[0], CONFIG.get_int("MATCH_RATIO"))

    def test_series_suffix_normalization_does_not_accept_wrong_author_or_book(self):
        book = {
            "library": "eBook", "bookid": "68427",
            "bookName": "Elantris (Elantris, #1)", "bookSub": "",
            "authorName": "Brandon Sanderson", "searchterm": "Brandon Sanderson Elantris",
        }
        for title in ("Other Writer - Elantris - epub", "Brandon Sanderson - The Lost Metal - epub"):
            match = find_best_result([self._torrent_result(title)], book, "book", "tor")
            self.assertTrue(match is None or match[0] < CONFIG.get_int("MATCH_RATIO"))

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
                return "a" * 40, "", False

            with (
            patch.dict(os.environ, {"BOX_LL_SPOOL_DIR": temp,
                "BOX_LL_HANDOFF_PROTOCOL": "box-qbit-durable-intent-v1",
                "BOX_LL_QBIT_LIFECYCLE_OWNER": "helper"}),
            patch.object(downloadmethods, "CONFIG", DownloadConfig()),
            patch.object(qbittorrent, "add_torrent", side_effect=add_after_intent),
            patch.object(qbittorrent, "get_client", return_value=Mock()),
            patch.object(qbittorrent, "helper_add_preflight", return_value=""),
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


# Upstream result selection coverage retained through integration.
from unittest import mock
def _make_tor_result(title, url="http://test.com/book.torrent", size="50000000",
                     prov="TestProvider", priority=0, seeders=None):
    result = {
        "tor_title": title,
        "tor_url": url,
        "tor_size": size,
        "tor_prov": prov,
        "tor_type": "torrent",
        "priority": priority,
    }
    if seeders is not None:
        result["seeders"] = seeders
    return result


def _make_book(author, title, bookid="test_001", library="eBook"):
    return {
        "authorName": author,
        "bookName": title,
        "bookid": bookid,
        "library": library,
        "searchterm": f"{author} {title}",
    }


class LanguageRejectionTest(LLTestCaseWithStartup):

    def setUp(self):
        super().setUp()
        self.original_preflang = CONFIG["IMP_PREFLANG"]

    def tearDown(self):
        CONFIG["IMP_PREFLANG"] = self.original_preflang
        super().tearDown()

    def test_rejects_non_preferred_language_tag(self):
        CONFIG["IMP_PREFLANG"] = "en, eng, English"
        book = _make_book("Some Author", "Some Book")
        results = [_make_tor_result("Some Author - Some Book [SWE]")]

        match = find_best_result(results, book, "book", "tor")
        self.assertIsNone(match, "Swedish release should be rejected for English preference")

    def test_accepts_preferred_language_tag(self):
        CONFIG["IMP_PREFLANG"] = "en, eng, English"
        book = _make_book("Some Author", "Some Book")
        results = [_make_tor_result("Some Author - Some Book [ENG]")]

        match = find_best_result(results, book, "book", "tor")
        self.assertIsNotNone(match, "English release should be accepted")

    def test_german_wife_not_rejected(self):
        """Token boundaries: 'German' in 'The German Wife' is part of the
        title, not a language indicator."""
        CONFIG["IMP_PREFLANG"] = "en, eng, English"
        book = _make_book("Pam Jenoff", "The German Wife")
        results = [_make_tor_result("Pam Jenoff - The German Wife epub")]

        match = find_best_result(results, book, "book", "tor")
        self.assertIsNotNone(match, "'German' in the book title should not trigger rejection")

    def test_language_all_disables_filter(self):
        CONFIG["IMP_PREFLANG"] = "All"
        book = _make_book("Some Author", "Some Book")
        results = [_make_tor_result("Some Author - Some Book [SWE]")]

        match = find_best_result(results, book, "book", "tor")
        self.assertIsNotNone(match, "IMP_PREFLANG=All should accept any language")

    def test_rejects_full_language_name(self):
        CONFIG["IMP_PREFLANG"] = "en, eng, English"
        book = _make_book("Some Author", "Some Book")
        results = [_make_tor_result("Some Author - Some Book Swedish Edition")]

        match = find_best_result(results, book, "book", "tor")
        self.assertIsNone(match, "Full language name 'Swedish' should trigger rejection")

    def test_three_letter_code_in_brackets(self):
        CONFIG["IMP_PREFLANG"] = "en, eng, English"
        book = _make_book("Some Author", "Some Book")
        results = [_make_tor_result("Some Author - Some Book [FRE]")]

        match = find_best_result(results, book, "book", "tor")
        self.assertIsNone(match, "French 3-letter code should be rejected for English preference")

    def test_author_name_matching_language_not_rejected(self):
        """An author named 'Danish' should not trigger language rejection."""
        CONFIG["IMP_PREFLANG"] = "en, eng, English"
        book = _make_book("Barbara Danish", "The Puzzle")
        results = [_make_tor_result("Barbara Danish - The Puzzle epub")]

        match = find_best_result(results, book, "book", "tor")
        self.assertIsNotNone(match, "'Danish' in author name should not trigger rejection")


class CrossFormatRejectionTest(LLTestCaseWithStartup):

    def test_audiobook_format_rejected_for_ebook_search(self):
        book = _make_book("Some Author", "Some Book", library="eBook")
        results = [_make_tor_result("Some Author - Some Book m4b")]
        match = find_best_result(results, book, "book", "tor")
        self.assertIsNone(match, "m4b-only result should be rejected for eBook search")

    def test_ebook_format_rejected_for_audiobook_search(self):
        book = _make_book("Some Author", "Some Book", library="AudioBook")
        results = [_make_tor_result("Some Author - Some Book epub")]
        match = find_best_result(results, book, "audiobook", "tor")
        self.assertIsNone(match, "epub-only result should be rejected for AudioBook search")

    def test_correct_format_not_rejected(self):
        """epub in an eBook search should pass the cross-format check."""
        book = _make_book("Some Author", "Some Book", library="eBook")
        results = [_make_tor_result("Some Author - Some Book epub")]
        match = find_best_result(results, book, "book", "tor")
        self.assertIsNotNone(match, "Correct format should not be rejected")

    def test_no_format_tokens_not_rejected(self):
        book = _make_book("Some Author", "Some Book", library="eBook")
        results = [_make_tor_result("Some Author - Some Book")]
        match = find_best_result(results, book, "book", "tor")
        self.assertIsNotNone(match, "No format tokens should not trigger rejection")


class SeederFilterTest(LLTestCaseWithStartup):

    def test_zero_seeders_rejected_with_min_seeders_1(self):
        book = _make_book("Some Author", "Some Book")
        results = [_make_tor_result("Some Author - Some Book", seeders=0)]
        with mock.patch.object(CONFIG, 'get_int',
                               side_effect=lambda k: 1 if k == 'MIN_SEEDERS' else CONFIG.__class__.get_int(CONFIG, k)):
            match = find_best_result(results, book, "book", "tor")
        self.assertIsNone(match, "0-seeder result should be rejected when MIN_SEEDERS=1")

    def test_one_seeder_accepted_with_min_seeders_1(self):
        book = _make_book("Some Author", "Some Book")
        results = [_make_tor_result("Some Author - Some Book", seeders=1)]
        with mock.patch.object(CONFIG, 'get_int',
                               side_effect=lambda k: 1 if k == 'MIN_SEEDERS' else CONFIG.__class__.get_int(CONFIG, k)):
            match = find_best_result(results, book, "book", "tor")
        self.assertIsNotNone(match, "1-seeder result should be accepted when MIN_SEEDERS=1")

    def test_no_seeder_data_not_rejected(self):
        book = _make_book("Some Author", "Some Book")
        results = [_make_tor_result("Some Author - Some Book")]
        with mock.patch.object(CONFIG, 'get_int',
                               side_effect=lambda k: 5 if k == 'MIN_SEEDERS' else CONFIG.__class__.get_int(CONFIG, k)):
            match = find_best_result(results, book, "book", "tor")
        self.assertIsNotNone(match, "Result without seeder data should not be rejected")

    def test_seeder_filter_disabled_when_zero(self):
        book = _make_book("Some Author", "Some Book")
        results = [_make_tor_result("Some Author - Some Book", seeders=0)]
        with mock.patch.object(CONFIG, 'get_int',
                               side_effect=lambda k: 0 if k == 'MIN_SEEDERS' else CONFIG.__class__.get_int(CONFIG, k)):
            match = find_best_result(results, book, "book", "tor")
        self.assertIsNotNone(match, "0-seeder result should pass when MIN_SEEDERS=0")

    def test_higher_seeders_preferred_as_tiebreaker(self):
        book = _make_book("Some Author", "Some Book")
        results = [
            _make_tor_result("Some Author - Some Book", url="http://a/1", seeders=2),
            _make_tor_result("Some Author - Some Book", url="http://b/2", seeders=50),
        ]
        with mock.patch.object(CONFIG, 'get_int',
                               side_effect=lambda k: 0 if k == 'MIN_SEEDERS' else CONFIG.__class__.get_int(CONFIG, k)):
            match = find_best_result(results, book, "book", "tor")
        self.assertIsNotNone(match)
        self.assertIn("http://b/2", match[2]["NZBurl"])
