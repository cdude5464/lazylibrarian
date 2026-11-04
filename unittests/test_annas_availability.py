import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup
from requests.exceptions import ReadTimeout

from lazylibrarian import annas, providers


class FakeConfig(dict):
    def get_int(self, name):
        return int(self.get(name, 0))

    def set_int(self, name, value):
        self[name] = value


class AnnaAvailabilityTest(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name) / "IRCCache"
        self.cache.mkdir()
        self.config = FakeConfig(
            ANNA_HOST="https://one.invalid,https://two.invalid",
            ANNA_SEARCH_LANG="ANY", ANNA_DLLIMIT=0, ANNA_DLPRIORITY=5,
        )
        self.patches = [
            patch.object(annas, "CONFIG", self.config),
            patch.object(annas, "DIRS", SimpleNamespace(CACHEDIR=self.temp.name)),
            patch.object(annas, "annas_hosts_update"),
            patch.object(annas.BLOCKHANDLER, "is_blocked", return_value=False),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_http_and_transport_failures_raise_sanitized_provider_error(self):
        sensitive = "https://user:SECRET@one.invalid/search?key=SECRET"
        with patch.object(annas, "html_parser", side_effect=[
                annas.HTTPFailedError("server returned http status 403"),
                ReadTimeout(sensitive)]):
            with self.assertRaisesRegex(annas.HTTPFailedError, "HTTP 403, ReadTimeout") as failure:
                annas.annas_search("book")
        self.assertNotIn("SECRET", str(failure.exception))
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_real_empty_search_is_cached_as_success(self):
        soup = BeautifulSoup("<html><body><div>No files found.</div></body></html>", "html5lib")
        with patch.object(annas, "html_parser", return_value=soup):
            path = annas.annas_search("missing book")
        self.assertEqual(json.loads(Path(path).read_text()), [])

    def test_failed_first_mirror_does_not_override_successful_empty_second(self):
        soup = BeautifulSoup("<html><body>No files found.</body></html>", "html5lib")
        with patch.object(annas, "html_parser", side_effect=[
                annas.HTTPFailedError("server returned http status 403"), soup]):
            path = annas.annas_search("missing book")
        self.assertEqual(json.loads(Path(path).read_text()), [])
        self.assertTrue(self.config["ANNA_HOST"].startswith("https://two.invalid"))

    def test_unknown_success_page_does_not_poison_zero_result_cache(self):
        for html in (
            "<html><body>Scheduled maintenance. Please try later.</body></html>",
            "<html><body>Anna's Archive</body></html>",
            "<html><body>No files found. is an example phrase, not a result.</body></html>",
        ):
            with self.subTest(html=html), patch.object(annas, "html_parser", return_value=BeautifulSoup(html, "html5lib")):
                with self.assertRaisesRegex(annas.HTTPFailedError, "unrecognized results page"):
                    annas.annas_search("book")
            self.assertEqual(list(self.cache.iterdir()), [])

    def test_unparseable_result_cards_do_not_poison_zero_result_cache(self):
        soup = BeautifulSoup('<div class="pt-3 border-b">changed markup</div>', "html5lib")
        with patch.object(annas, "html_parser", return_value=soup):
            with self.assertRaisesRegex(annas.HTTPFailedError, "could not be parsed"):
                annas.annas_search("book")
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_success_status_access_challenge_is_error(self):
        for title in ("Just a moment...", "DDoS-Guard"):
            with self.subTest(title=title):
                response = Mock(status_code=200, text=f"<html><title>{title}</title></html>")
                with patch.object(annas, "_anna_search_response", return_value=response):
                    with self.assertRaisesRegex(annas.HTTPFailedError, "access challenge"):
                        annas.html_parser("https://annas-archive.gl/search")

    def test_adapter_returns_error_instead_of_successful_no_results(self):
        with patch.object(annas.BLOCKHANDLER, "is_blocked", return_value=False):
            with patch.object(annas, "annas_search", side_effect=annas.HTTPFailedError("Anna unavailable")):
                results, error = annas.anna_search({"bookid": "42", "searchterm": "book"})
        self.assertEqual(results, [])
        self.assertEqual(error, "Anna unavailable")

    def test_provider_test_returns_false_when_search_unavailable(self):
        with patch.object(annas.BLOCKHANDLER, "is_blocked", return_value=False):
            with patch.object(annas, "annas_search", side_effect=annas.HTTPFailedError("Anna unavailable")):
                self.assertFalse(annas.anna_search({"searchterm": "book"}, test=True))

    def test_cached_md5_result_remains_usable_during_html_search_backoff(self):
        query = "Author Book"
        cached = self.cache / (annas.md5_utf8(query) + ".anna")
        cached.write_text(json.dumps([{
            "authors": "Author", "title": "Book", "extension": "epub",
            "size": "1MB", "language": "English [en]", "id": "a" * 32,
        }]))
        with (
            patch.object(annas.BLOCKHANDLER, "is_blocked", side_effect=lambda key: key == "annas-search"),
            patch.object(annas, "annas_search") as network_search,
        ):
            results, error = annas.anna_search({"bookid": "42", "searchterm": query})
        self.assertEqual(error, "")
        self.assertEqual(results[0]["tor_url"], "a" * 32)
        network_search.assert_not_called()

    def test_confirmed_quota_block_still_prevents_search(self):
        with patch.object(annas.BLOCKHANDLER, "is_blocked", side_effect=lambda key: key == "annas"):
            results, error = annas.anna_search({"bookid": "42", "searchterm": "Book"})
        self.assertEqual((results, error), ([], "provider is already blocked"))

    def test_search_backoff_does_not_issue_http_requests(self):
        with (
            patch.object(annas.BLOCKHANDLER, "is_blocked", side_effect=lambda key: key == "annas-search"),
            patch.object(annas, "get") as network,
        ):
            with self.assertRaisesRegex(annas.HTTPFailedError, "search backoff"):
                annas.annas_search("Book")
        network.assert_not_called()


class AnnaProviderOutageBlockTest(TestCase):
    def test_stale_remaining_quota_does_not_extend_an_outage_block(self):
        config = FakeConfig(
            BOK=False, SLSK=False, WEBSHARE=False, ANNA=True, ANNA_DLTYPES="E",
            ANNA_DLLIMIT=50, BLOCKLIST_TIMER=300,
        )
        config.providers = lambda _: []
        book = {"bookid": "42", "bookName": "Book", "authorName": "Author", "searchterm": "Author Book"}
        with (
            patch.object(providers, "CONFIG", config),
            patch.object(providers.BLOCKHANDLER, "is_blocked", return_value=False),
            patch.object(providers.BLOCKHANDLER, "block_provider") as block,
            patch.object(providers, "anna_search", return_value=([], "Anna search unavailable")),
            patch.dict(providers.lazylibrarian.TIMERS, {"ANNA_REMAINING": 0}),
        ):
            result = providers.iterate_over_direct_sites(book, "generalbook")
        self.assertEqual(result, ([], 0))
        block.assert_called_once_with("annas-search", "Anna search unavailable", delay=300)


    def test_existing_search_backoff_is_not_extended_by_more_wanted_books(self):
        config = FakeConfig(BOK=False, SLSK=False, WEBSHARE=False, ANNA=True, ANNA_DLTYPES="E", BLOCKLIST_TIMER=300)
        config.providers = lambda _: []
        book = {"bookid": "42", "bookName": "Book", "authorName": "Author", "searchterm": "Author Book"}
        with (
            patch.object(providers, "CONFIG", config),
            patch.object(providers.BLOCKHANDLER, "is_blocked", side_effect=lambda key: key == "annas-search"),
            patch.object(providers.BLOCKHANDLER, "block_provider") as block,
            patch.object(providers, "anna_search", return_value=([], "Anna HTML search is in backoff")),
        ):
            self.assertEqual(providers.iterate_over_direct_sites(book, "generalbook"), ([], 0))
        block.assert_not_called()


class AnnaCredentialLoggingTest(TestCase):
    def test_api_transport_exception_and_http_error_do_not_log_secret_params(self):
        config = FakeConfig(ANNA_HOST="https://annas-archive.gl", ANNA_KEY="SECRET")
        for outcome in (ReadTimeout("https://annas-archive.gl/dyn/api/fast_download.json?key=SECRET"), Mock(status_code=403)):
            with self.subTest(outcome=outcome):
                logger, downloadlogger = Mock(), Mock()
                with (
                    patch.object(annas, "CONFIG", config),
                    patch.object(annas.logging, "getLogger", side_effect=[logger, downloadlogger]),
                    patch.object(annas, "get", side_effect=[outcome]),
                    patch.object(annas.BLOCKHANDLER, "block_provider"),
                ):
                    success, error = annas.annas_download("a" * 32, "", "Book", ".epub")
                self.assertFalse(success)
                self.assertNotIn("SECRET", error + str(logger.mock_calls) + str(downloadlogger.mock_calls))

    def test_signed_file_download_url_and_exception_are_not_logged(self):
        config = FakeConfig(ANNA_HOST="https://annas-archive.gl", ANNA_KEY="SECRET", ANNA_MAX_SERVERS=1)
        response = Mock(status_code=200)
        response.json.return_value = {
            "account_fast_download_info": {"downloads_per_day": 50, "downloads_left": 2},
            "download_url": "https://files.invalid/download?signature=SECRET",
        }
        logger, downloadlogger = Mock(), Mock()
        with (
            patch.object(annas, "CONFIG", config),
            patch.object(annas.logging, "getLogger", side_effect=[logger, downloadlogger]),
            patch.object(annas, "get", side_effect=[response, ReadTimeout("https://files.invalid/?signature=SECRET")]),
            patch.dict(annas.lazylibrarian.TIMERS, {"ANNA_REMAINING": 2}),
        ):
            success, error = annas.annas_download("a" * 32, "", "Book", ".epub")
        self.assertFalse(success)
        self.assertNotIn("SECRET", error + str(logger.mock_calls) + str(downloadlogger.mock_calls))

    def test_confirmed_fast_download_rate_limits_still_block_download_provider(self):
        config = FakeConfig(ANNA_HOST="https://annas-archive.gl", ANNA_KEY="SECRET", ANNA_DLLIMIT=50)
        for status in (409, 429):
            with self.subTest(status=status):
                response = Mock(status_code=status)
                with (
                    patch.object(annas, "CONFIG", config),
                    patch.object(annas, "get", return_value=response),
                    patch.object(annas, "block_annas") as quota_block,
                    patch.dict(annas.lazylibrarian.TIMERS, {"ANNA_REMAINING": 5}),
                ):
                    success, error = annas.annas_download("a" * 32, "", "Book", ".epub")
                    self.assertEqual(annas.lazylibrarian.TIMERS["ANNA_REMAINING"], 0)
                self.assertFalse(success)
                self.assertIn("rate limited", error)
                quota_block.assert_called_once_with(50, reason=error)
