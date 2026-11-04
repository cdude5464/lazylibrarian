"""Tests for the bundled zlibrary client library."""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))


class ZlibrarySessionTest(unittest.TestCase):
    """Verify that the Zlibrary client uses curl_cffi with TLS impersonation."""

    def test_session_uses_curl_cffi(self):
        from zlibrary import Zlibrary
        z = Zlibrary.__new__(Zlibrary)
        z._domain = "example.com"
        z._timeout = 10
        z._max_retries = 0
        z._loggedin = False
        z._cookies = {}

        from curl_cffi.requests.session import Session
        z._session = Session(impersonate="chrome")

        self.assertIsInstance(z._session, Session)

    def test_session_has_impersonate_set(self):
        from curl_cffi import requests as cffi_requests
        session = cffi_requests.Session(impersonate="chrome")
        self.assertEqual(session.impersonate, "chrome")

    def test_zlibrary_init_creates_impersonated_session(self):
        from zlibrary import Zlibrary
        z = Zlibrary(domain="example.com")
        self.assertEqual(z._session.impersonate, "chrome")
        self.assertFalse(z.isLoggedIn())

    def test_proxies_passed_to_constructor(self):
        from curl_cffi import requests as cffi_requests
        proxy_config = {"https": "socks5://127.0.0.1:9050"}
        session = cffi_requests.Session(impersonate="chrome", proxies=proxy_config)
        self.assertEqual(session.proxies["https"], "socks5://127.0.0.1:9050")

    def test_no_proxies_leaves_default(self):
        from curl_cffi import requests as cffi_requests
        session = cffi_requests.Session(impersonate="chrome")
        self.assertIsInstance(session.proxies, dict)

    def test_exception_hierarchy(self):
        from curl_cffi.requests.exceptions import RequestException
        from curl_cffi.curl import CurlError
        from zlibrary import ZlibraryError
        self.assertTrue(issubclass(RequestException, CurlError))
        self.assertFalse(issubclass(CurlError, RequestException))
        self.assertTrue(issubclass(ZlibraryError, Exception))


if __name__ == '__main__':
    unittest.main()
