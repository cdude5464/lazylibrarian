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
                with patch.object(annas, "get", return_value=response):
                    with self.assertRaisesRegex(annas.HTTPFailedError, "access challenge"):
                        annas.html_parser("https://one.invalid/search")

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


class AnnaProviderOutageBlockTest(TestCase):
    def test_stale_remaining_quota_does_not_extend_an_outage_block(self):
        config = FakeConfig(
            BOK=False, SLSK=False, ANNA=True, ANNA_DLTYPES="E",
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
        block.assert_called_once_with("annas", "Anna search unavailable", delay=300)
