"""Isolated network diagnostics tests; no configuration or database fixtures."""
import http.client
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, quote, urlsplit
from xml.etree import ElementTree

import requests
from lazylibrarian import blockhandler, cache, providers
from lazylibrarian.formatter import md5_utf8
from lazylibrarian.providerlogging import provider_error_category, provider_log_origin

SECRET = 'sensitive+/credential'
URL = 'https://user:password@example.invalid/signed/' + quote(SECRET, safe='') + '?ApIkEy=' + quote(SECRET, safe='') + '&ToKeN=' + quote(SECRET, safe='') + '&PaSsWoRd=' + quote(SECRET, safe='') + '#private'


class ProviderSecretLoggingTest(TestCase):
    def assert_safe(self, logger):
        logs = str(logger.mock_calls)
        for value in (SECRET, quote(SECRET, safe=''), 'password', 'private', URL):
            self.assertNotIn(value, logs)

    def test_origin_omits_all_userinfo_paths_and_mixed_case_encoded_query(self):
        self.assertEqual(provider_log_origin(URL), 'https://example.invalid')
        self.assertEqual(provider_log_origin('https://[::1]:123/api?token=secret'), 'https://[::1]:123')
        self.assertEqual(provider_log_origin('example.invalid/api?token=secret'), 'example.invalid')
        self.assertEqual(provider_log_origin('https://host:bad/path'), '[provider]')
        self.assertEqual(provider_log_origin('ApIkEy=SECRET'), '[provider]')
        self.assertEqual(provider_log_origin(quote(URL, safe='')), '[provider]')

    def test_search_parameters_and_request_unchanged_but_logs_have_no_values(self):
        provider = {'HOST': 'https://example.invalid/torznab/abt', 'API': SECRET,
                    'GENERALSEARCH': 'search', 'EXTENDED': '1&ToKeN=' + SECRET + '&PaSsWoRd=' + SECRET}
        book = {'BookID': '123', 'searchterm': 'Author Title'}
        logger = Mock()
        response = b'<rss><channel /></rss>'
        with patch.object(providers.logging, 'getLogger', return_value=logger), patch.object(providers, 'fetch_url', return_value=(response, True)) as fetch:
            result = providers.newznab_plus(book, provider, 'generalbook', 'torznab')
        self.assertEqual(result, (True, []))
        args = fetch.call_args
        self.assertEqual(urlsplit(args.args[0]).path, '/torznab/abt/api')
        params = parse_qs(urlsplit(args.args[0]).query)
        self.assertEqual(params['apikey'], [SECRET])
        self.assertEqual(params['ToKeN'], [SECRET])
        self.assertEqual(params['PaSsWoRd'], [SECRET])
        self.assertEqual(params['q'], ['Author Title'])
        self.assertEqual(args.kwargs, {'raw': True})
        self.assert_safe(logger)

    def test_result_download_url_unchanged_without_result_dictionary_dump(self):
        logger = Mock()
        item = ElementTree.fromstring('<item><title>Title</title><link /></item>')
        item.find('link').text = URL
        with patch.object(providers.logging, 'getLogger', return_value=logger):
            result = providers.return_results_by_search_type({'bookid': '123'}, item, 'https://example.invalid', 'torznab')
        self.assertEqual(result['nzburl'], URL)
        self.assert_safe(logger)

    def fetch(self, side_effect=None, response=None, retry=False):
        logger = Mock()
        cfg = Mock(); cfg.get_bool.return_value = True; cfg.__getitem__ = Mock(return_value='')
        with patch.object(cache.logging, 'getLogger', return_value=logger), patch.object(cache, 'CONFIG', cfg), patch.object(cache, 'proxy_list', return_value={}), patch.object(cache, 'get_user_agent', return_value='test'), patch.object(cache.requests, 'get', side_effect=side_effect, return_value=response) as get, patch.object(cache.lazylibrarian, 'REQUESTSLOG', True):
            result = cache.fetch_url(URL, retry=retry, timeout=False, raw=True)
        self.assertEqual(get.call_args.args[0], URL)
        self.assertEqual(http.client.HTTPConnection.debuglevel, 0)
        self.assert_safe(logger)
        return result

    def test_requests_exceptions_never_return_or_log_secret_url(self):
        for error in (requests.Timeout, requests.TooManyRedirects, requests.ConnectionError):
            for retry in (False, True):
                with self.subTest(error=error.__name__, retry=retry):
                    result, ok = self.fetch(side_effect=error('failed at ' + URL), retry=retry)
                    self.assertFalse(ok)
                    self.assertNotIn(SECRET, result)
                    self.assertNotIn(quote(SECRET, safe=''), result)
                    self.assertNotIn(URL, result)

    def test_http_body_not_logged_and_success_bytes_unchanged(self):
        response = SimpleNamespace(status_code=599, text=SECRET, json=lambda: {})
        self.assertEqual(self.fetch(response=response), ('Response status 599: HTTP error', False))
        response = SimpleNamespace(status_code=200, content=SECRET.encode())
        self.assertEqual(self.fetch(response=response), (SECRET.encode(), True))

    def test_cache_url_and_hash_unchanged_including_xml_fetch(self):
        logger = Mock()
        with patch.object(cache.logging, 'getLogger', return_value=logger):
            request = cache.XMLCacheRequest(URL, True, True)
        filename, digest = request.get_hashed_filename('/tmp/testcache')
        self.assertEqual(digest, md5_utf8(URL))
        self.assertTrue(filename.endswith(digest + '.xml'))
        with patch.object(cache, 'fetch_url', return_value=(b'<rss />', True)) as fetch:
            self.assertEqual(request.fetch_data(), (b'<rss />', True))
        fetch.assert_called_once_with(URL, raw=True, headers=None)
        with patch.object(cache.DIRS, 'get_cachedir', return_value='/tmp/testcache'), patch.object(cache, 'CONFIG') as cfg, patch.object(request, 'is_in_cache', return_value=True), patch.object(request, 'read_from_cache', return_value=(b'<rss />', True)):
            cfg.get_int.return_value = 1
            self.assertEqual(request.get_cached_request(), (b'<rss />', True))
        self.assertEqual(request.url, URL)
        self.assert_safe(logger)

    def test_error_classification_preserves_authentication_evidence_without_response(self):
        for text, category in (
            ('The cookies did not work, login redirect at ' + URL, 'authentication-cookie'),
            ('HTTP 403: ' + URL, 'access-denied'),
            ('HTTP 429: ' + URL, 'rate-limit'),
            ('unknown error ' + SECRET, 'provider-error'),
        ):
            with self.subTest(category=category):
                self.assertEqual(provider_error_category(text), category)

    def test_block_handler_keeps_identity_and_reason_but_logs_only_origin_and_category(self):
        logger = Mock()
        handler = blockhandler.BlockHandler()
        reason = 'Cookie login failed at ' + URL
        with patch.object(blockhandler.logging, 'getLogger', return_value=logger):
            self.assertEqual(handler.block_provider(URL, reason, 30), 30)
            self.assertEqual(handler.block_provider(URL, reason, 0), 0)
        self.assertIn(URL, handler._provider_list)
        self.assertEqual(handler._provider_list[URL]['reason'], reason[:80])
        self.assertIn('authentication-cookie', str(logger.mock_calls))
        self.assert_safe(logger)

    def test_mam_response_not_written_to_raw_diagnostic_log(self):
        logger = Mock()
        with patch.object(providers.logging, 'getLogger', return_value=logger), patch.object(providers, 'fetch_url', return_value=(SECRET, False)), patch.object(providers, 'open', create=True) as output:
            self.assertEqual(providers.mam('https://example.invalid', test=True), 0)
        output.assert_not_called()
        self.assert_safe(logger)

    def test_cache_image_write_error_returns_only_exception_class(self):
        logger = Mock()
        with patch.object(cache.logging, 'getLogger', return_value=logger), patch.object(cache.DIRS, 'get_cachedir', return_value='/tmp/cache'), patch.object(cache, 'path_isfile', return_value=False), patch.object(cache, 'fetch_url', return_value=(b'image', True)), patch.object(cache, 'open', create=True, side_effect=OSError('failed at ' + URL)):
            result, success, _ = cache.cache_img(cache.ImageType.BOOK, '123', URL)
        self.assertFalse(success)
        self.assertEqual(result, 'OSError')
        self.assert_safe(logger)
