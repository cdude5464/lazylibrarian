"""Authenticated Anna search stays origin-, key-, and generation-scoped."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.parse import urlparse, parse_qs

from curl_cffi.requests import Cookies
from requests.cookies import create_cookie

from lazylibrarian import annas, cache


class FakeSession:
    def __init__(self):
        self.cookies = Cookies()
        self.post = Mock(side_effect=self.login)
        self.get = Mock(return_value=SimpleNamespace(status_code=200, text='<html>Search results</html>', headers={}))

    def login(self, url, **kwargs):
        self.cookies.jar.set_cookie(create_cookie('aa_account_id2', 'FAKE_SESSION',
                                                  domain=urlparse(url).hostname, path='/'))
        return SimpleNamespace(status_code=302)


class AuthenticatedAnnaSessionTest(TestCase):
    def setUp(self):
        self.config = {'ANNA_KEY': 'FAKE_MEMBER_KEY', 'ANNA_HOST': 'https://annas-archive.gl'}
        self.sessions = []

        def new_session(**kwargs):
            session = FakeSession()
            self.sessions.append(session)
            return session

        self.factory = self.enterContext(patch.object(annas.curl_cffi.requests, 'Session', side_effect=new_session))
        self.enterContext(patch.object(annas, 'CONFIG', self.config))
        self.enterContext(patch.dict(annas._annas_sessions, clear=True))

    def test_login_and_search_reuse_existing_member_cookie_with_timeouts(self):
        annas.html_parser('https://annas-archive.gl/search', {'q': 'Book', 'lang': ['en', 'de']})
        annas.html_parser('https://annas-archive.gl/search', {'q': 'Another'})
        session = self.sessions[0]
        session.post.assert_called_once_with('https://annas-archive.gl/account/',
                                             data={'key': 'FAKE_MEMBER_KEY'},
                                             timeout=annas.ANNA_HTTP_TIMEOUT, allow_redirects=False)
        self.assertEqual(session.get.call_count, 2)
        first = session.get.call_args_list[0]
        self.assertEqual(parse_qs(urlparse(first.args[0]).query), {'q': ['Book'], 'lang': ['en', 'de']})
        self.assertEqual(first.kwargs, {'timeout': annas.ANNA_HTTP_TIMEOUT, 'allow_redirects': False})
        self.factory.assert_called_once_with(impersonate='chrome')

    def test_missing_key_never_posts_or_reuses_previous_credentials(self):
        annas.annas_login('https://annas-archive.gl')
        self.config['ANNA_KEY'] = ''
        annas.html_parser('https://annas-archive.gl/search')
        self.assertEqual(self.sessions[0].post.call_count, 1)
        self.assertFalse(list(self.sessions[0].cookies.jar))

    def test_key_change_and_expired_cookie_force_fresh_login(self):
        annas.annas_login('https://annas-archive.gl')
        session = self.sessions[0]
        session.cookies.jar.set_cookie(create_cookie('aa_account_id2', 'EXPIRED',
                                                     domain='annas-archive.gl', path='/', expires=1))
        annas.annas_login('https://annas-archive.gl')
        self.config['ANNA_KEY'] = 'NEW_FAKE_KEY'
        annas.annas_login('https://annas-archive.gl')
        self.assertEqual(session.post.call_count, 3)
        self.assertEqual(session.post.call_args.kwargs['data'], {'key': 'NEW_FAKE_KEY'})

    def test_cookies_and_login_failures_cannot_cross_mirrors(self):
        annas.annas_login('https://annas-archive.gl')
        origin = 'https://annas-archive.pk'
        state, _, _ = annas._anna_state(origin)
        state['session'].post.side_effect = lambda *a, **k: SimpleNamespace(status_code=302)
        with self.assertRaisesRegex(annas.HTTPFailedError, 'valid session'):
            annas.annas_login(origin)
        state['session'].get.assert_not_called()
        self.assertEqual(len(self.sessions), 2)

    def test_parallel_searches_serialize_one_login_per_origin(self):
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(lambda _: annas.html_parser('https://annas-archive.gl/search'), range(12)))
        self.assertEqual(len(self.sessions), 1)
        self.assertEqual(self.sessions[0].post.call_count, 1)
        self.assertEqual(self.sessions[0].get.call_count, 12)

    def test_member_403_gets_one_reauthentication_then_stops(self):
        annas.annas_login('https://annas-archive.gl')
        session = self.sessions[0]
        session.get.return_value = SimpleNamespace(status_code=403, headers={})
        with self.assertRaisesRegex(annas.HTTPFailedError, 'http status 403'):
            annas.html_parser('https://annas-archive.gl/search')
        self.assertEqual(session.post.call_count, 2)
        self.assertEqual(session.get.call_count, 2)
        self.assertFalse(list(session.cookies.jar))

    def test_cross_origin_redirect_never_sends_cookie_or_key_to_target(self):
        annas.annas_login('https://annas-archive.gl')
        session = self.sessions[0]
        session.get.return_value = SimpleNamespace(status_code=302, headers={'Location': 'https://evil.invalid/steal'})
        with self.assertRaisesRegex(annas.HTTPFailedError, 'cross-origin|approved HTTPS'):
            annas.html_parser('https://annas-archive.gl/search')
        self.assertEqual(session.get.call_count, 1)
        self.assertNotIn('evil.invalid', session.get.call_args.args[0])
        self.assertFalse(session.post.call_args.kwargs['allow_redirects'])

    def test_same_origin_redirect_is_bounded_and_login_page_is_not_cached_success(self):
        annas.annas_login('https://annas-archive.gl')
        session = self.sessions[0]
        session.get.return_value = SimpleNamespace(status_code=302, headers={'Location': '/search?check=1'})
        with self.assertRaisesRegex(annas.HTTPFailedError, 'redirect limit'):
            annas.html_parser('https://annas-archive.gl/search')
        self.assertEqual(session.get.call_count, 4)
        session.get.return_value = SimpleNamespace(status_code=200, headers={}, text='<title>Log in</title>')
        with self.assertRaisesRegex(annas.HTTPFailedError, 'authentication required'):
            annas.html_parser('https://annas-archive.gl/search')

    def test_unapproved_hosts_cannot_receive_membership_key(self):
        for host in ('http://annas-archive.gl', 'https://annas-archive.cc',
                     'https://annas-archive.gl.evil.invalid', 'https://u:p@annas-archive.gl',
                     'https://annas-archive.gl:444'):
            with self.subTest(host=host), self.assertRaisesRegex(annas.HTTPFailedError, 'approved HTTPS'):
                annas.annas_login(host)
        self.factory.assert_not_called()

    def test_login_transport_exception_does_not_expose_key_or_cookie(self):
        origin = 'https://annas-archive.gl'
        state, _, _ = annas._anna_state(origin)
        state['session'].post.side_effect = RuntimeError('FAKE_MEMBER_KEY and FAKE_SESSION')
        with self.assertRaises(annas.HTTPFailedError) as error:
            annas.annas_login(origin)
        self.assertNotIn('FAKE_MEMBER_KEY', str(error.exception))
        self.assertNotIn('FAKE_SESSION', str(error.exception))

    def test_language_filters_have_separate_cache_identity(self):
        self.assertNotEqual(annas._anna_cache_key('Same book', [annas.Language.EN]),
                            annas._anna_cache_key('Same book', [annas.Language.DE]))
        self.assertEqual(annas._anna_cache_key('Same book', []), annas.md5_utf8('Same book'))
        self.assertEqual(annas._anna_cache_key('Same book', [annas.Language.EN, annas.Language.DE]),
                         annas._anna_cache_key('Same book', [annas.Language.DE, annas.Language.EN]))

    def test_wikipedia_cannot_authorize_a_new_credential_domain(self):
        response = SimpleNamespace(status_code=200, content=b'<span class="url"><a href="https://annas-archive.cc/">fake</a></span><span class="url"><a href="https://annas-archive.pk/">official</a></span>')
        with patch.object(annas, 'get', return_value=response):
            annas.annas_hosts_update()
        self.assertNotIn('.cc', self.config['ANNA_HOST'])
        self.assertIn('annas-archive.pk', self.config['ANNA_HOST'])
        self.factory.assert_not_called()


class UpstreamCacheTransportTest(TestCase):
    def test_curl_timeout_is_bounded_and_does_not_echo_sensitive_exception(self):
        config = Mock(); config.__getitem__ = Mock(return_value=''); config.get_bool.return_value = True
        error = cache.requests_cffi.exceptions.Timeout('https://host.invalid/?apikey=FAKE_SECRET')
        with patch.object(cache, 'CONFIG', config), patch.object(cache, 'proxy_list', return_value={}), \
             patch.object(cache.requests_cffi, 'get', side_effect=error) as request:
            value, ok = cache.fetch_url('https://host.invalid/path', retry=True, timeout=False, impersonate='chrome')
        self.assertFalse(ok)
        self.assertNotIn('FAKE_SECRET', value)
        self.assertEqual(request.call_count, 2)
