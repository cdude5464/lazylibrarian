#  This file is part of Lazylibrarian.
#
# Purpose:
#   Issue #3102: the REST client in calibre.py sent HTTP Basic auth, but a Calibre
#   Content Server with auth enabled only accepts HTTP Digest. Basic credentials
#   are rejected with "400 Unsupported authentication method", so every REST call
#   failed and the code silently fell back to calibredb CLI / local metadata.db.
#   calibre_server_request() must build an HTTPDigestAuth when CALIBRE_USER/PASS
#   are set, and pass no auth object at all when they are empty (so servers
#   without auth are unaffected - Digest only sends credentials after a 401
#   challenge, it never volunteers them).

from unittest import mock

from requests.auth import HTTPBasicAuth, HTTPDigestAuth

from lazylibrarian import calibre
from unittests.unittesthelpers import LLTestCase


class FakeConfig(dict):
    def get_bool(self, key):
        return bool(self.get(key))


class CalibreServerRequestAuthTest(LLTestCase):

    def _run(self, user, passwd, server='http://192.0.2.10:8081/#my-library'):
        cfg = FakeConfig(CALIBRE_SERVER=server, CALIBRE_USER=user,
                         CALIBRE_PASS=passwd, HTTPS_ENABLED=False)
        with mock.patch.object(calibre, 'CONFIG', cfg), \
             mock.patch.object(calibre.requests, 'request', return_value=mock.Mock(status_code=200)) as req:
            calibre.calibre_server_request('ajax/library-info')
        return req.call_args

    def test_credentials_set_uses_digest_auth(self):
        auth = self._run('terje', 'secret').kwargs['auth']
        self.assertIsInstance(auth, HTTPDigestAuth)
        self.assertEqual(auth.username, 'terje')
        self.assertEqual(auth.password, 'secret')

    def test_empty_credentials_send_no_auth(self):
        # no auth object at all - not a BasicAuth tuple, not a DigestAuth
        self.assertIsNone(self._run('', '').kwargs['auth'])

    def test_library_fragment_is_not_left_in_url(self):
        # "#library" suffix must not stay in the URL (would swallow the endpoint)
        called_url = self._run('terje', 'secret').args[1]
        self.assertNotIn('#', called_url)
        self.assertTrue(called_url.endswith('/ajax/library-info'))

    def test_library_goes_in_the_path(self):
        # the server ignores ?library=, ajax/search, ajax/books, ajax/book and cdb/delete-books
        # take the library id as their last path segment, anything else uses the default library
        cfg = FakeConfig(CALIBRE_SERVER='http://192.0.2.10:8081/#My Library', CALIBRE_USER='',
                         CALIBRE_PASS='', HTTPS_ENABLED=False)
        with mock.patch.object(calibre, 'CONFIG', cfg), \
             mock.patch.object(calibre.requests, 'request', return_value=mock.Mock(status_code=200)) as req:
            calibre.calibre_server_search('title:"x"')
            self.assertEqual(req.call_args.args[1].split('?')[0], 'http://192.0.2.10:8081/ajax/search/My%20Library')
            self.assertNotIn('library=', req.call_args.args[1])
            calibre.calibre_server_get_books()
            self.assertEqual(req.call_args.args[1], 'http://192.0.2.10:8081/ajax/books/My%20Library')
            calibre.calibre_server_get_book(5)
            self.assertEqual(req.call_args.args[1], 'http://192.0.2.10:8081/ajax/book/5/My%20Library')
            with mock.patch.object(cfg, 'get_bool', return_value=True):
                calibre.delete_from_calibre('7')
            self.assertEqual(req.call_args.args[1], 'http://192.0.2.10:8081/cdb/delete-books/7/My%20Library')

    def test_basic_challenge_retries_with_basic_auth(self):
        # with ssl, or --auth-mode basic, the server sends a basic challenge digest can't answer
        challenge = mock.Mock(status_code=401, headers={'WWW-Authenticate': 'Basic realm="calibre"'}, text='',
                              url='https://192.0.2.10:8081/ajax/library-info')
        ok = mock.Mock(status_code=200)
        ok.json.return_value = {'ok': 1}
        cfg = FakeConfig(CALIBRE_SERVER='https://192.0.2.10:8081', CALIBRE_USER='terje',
                         CALIBRE_PASS='secret', HTTPS_ENABLED=False)
        with mock.patch.object(calibre, 'CONFIG', cfg), \
             mock.patch.object(calibre.requests, 'request', side_effect=[challenge, ok]) as req:
            self.assertEqual(calibre.calibre_server_request('ajax/library-info'), ({'ok': 1}, None))
        auth = req.call_args.kwargs['auth']
        self.assertIsInstance(auth, HTTPBasicAuth)
        self.assertEqual((auth.username, auth.password), ('terje', 'secret'))

    def test_https_redirected_to_http_does_not_send_password(self):
        challenge = mock.Mock(status_code=401, headers={'WWW-Authenticate': 'Basic realm="calibre"'}, text='',
                              url='http://192.0.2.10:8081/ajax/library-info')
        cfg = FakeConfig(CALIBRE_SERVER='https://192.0.2.10:8081', CALIBRE_USER='terje',
                         CALIBRE_PASS='secret', HTTPS_ENABLED=False)
        with mock.patch.object(calibre, 'CONFIG', cfg), \
             mock.patch.object(calibre.requests, 'request', return_value=challenge) as req:
            self.assertIsNone(calibre.calibre_server_request('ajax/library-info')[0])
        self.assertEqual(req.call_count, 1)

    def test_delete_only_sends_a_single_id(self):
        cfg = FakeConfig(CALIBRE_USE_SERVER=True, CALIBRE_SERVER='http://192.0.2.10:8081')
        with mock.patch.object(calibre, 'CONFIG', cfg), \
             mock.patch.object(calibre, 'calibre_server_request') as rest, \
             mock.patch.object(calibre, 'calibredb', return_value=('', '', 1)):
            calibre.delete_from_calibre('1,2,3')
        rest.assert_not_called()

    def test_digest_failure_is_not_retried(self):
        denied = mock.Mock(status_code=401, headers={'WWW-Authenticate': 'Digest realm="calibre"'}, text='')
        cfg = FakeConfig(CALIBRE_SERVER='http://192.0.2.10:8081', CALIBRE_USER='terje',
                         CALIBRE_PASS='wrong', HTTPS_ENABLED=False)
        with mock.patch.object(calibre, 'CONFIG', cfg), \
             mock.patch.object(calibre.requests, 'request', return_value=denied) as req:
            self.assertEqual(calibre.calibre_server_request('ajax/library-info'), (None, 'HTTP 401: '))
        self.assertEqual(req.call_count, 1)

    def test_rest_failure_still_tests_calibredb(self):
        cfg = FakeConfig(CALIBRE_USE_SERVER=True, CALIBRE_SERVER='http://192.0.2.10:8081', IMP_CALIBREDB='calibredb')
        with mock.patch.object(calibre, 'CONFIG', cfg), \
             mock.patch.object(calibre, 'calibre_server_request', return_value=(None, 'HTTP 401: ')), \
             mock.patch.object(calibre, 'calibredb_test', return_value='calibredb ok, version 9.16'):
            result = calibre.calibre_test()
        self.assertIn('REST API communication failed: HTTP 401', result)
        self.assertIn('calibredb ok, version 9.16', result)

    def test_rest_failure_without_calibredb(self):
        cfg = FakeConfig(CALIBRE_USE_SERVER=True, CALIBRE_SERVER='http://192.0.2.10:8081', IMP_CALIBREDB='')
        with mock.patch.object(calibre, 'CONFIG', cfg), \
             mock.patch.object(calibre, 'calibre_server_request', return_value=(None, 'HTTP 401: ')), \
             mock.patch.object(calibre, 'calibredb_test') as cdb_test:
            result = calibre.calibre_test()
        self.assertEqual(result, 'Calibre Content Server REST API communication failed: HTTP 401: ')
        cdb_test.assert_not_called()

    def test_failed_search_is_not_read_ok(self):
        cfg = FakeConfig(CALIBRE_USE_SERVER=True, CALIBRE_SERVER='http://192.0.2.10:8081/#nolib', IMP_CALIBREDB='')
        info = {'default_library': 'LibA', 'library_map': {'LibA': 'LibA'}}
        with mock.patch.object(calibre, 'CONFIG', cfg), \
             mock.patch.object(calibre, 'calibre_server_request', side_effect=[(info, None), (None, 'HTTP 404: ')]):
            result = calibre.calibre_test()
        self.assertIn('Database READ failed: HTTP 404', result)
        self.assertNotIn('READ ok', result)

    def test_basic_challenge_over_http_does_not_send_password(self):
        challenge = mock.Mock(status_code=401, headers={'WWW-Authenticate': 'Basic realm="calibre"'}, text='',
                              url='http://192.0.2.10:8081/ajax/library-info')
        cfg = FakeConfig(CALIBRE_SERVER='http://192.0.2.10:8081', CALIBRE_USER='terje',
                         CALIBRE_PASS='secret', HTTPS_ENABLED=False)
        with mock.patch.object(calibre, 'CONFIG', cfg), \
             mock.patch.object(calibre.requests, 'request', return_value=challenge) as req:
            data, err = calibre.calibre_server_request('ajax/library-info')
        self.assertIsNone(data)
        self.assertIn('https', err)
        self.assertEqual(req.call_count, 1)
        self.assertIsInstance(req.call_args.kwargs['auth'], HTTPDigestAuth)

    def test_rest_list_joins_authors_like_calibredb(self):
        # "A, B" would be read as surname, forename and turned into a made up author
        books = {'3': {'title': 'Good Omens', 'authors': ['Terry Pratchett', 'Neil Gaiman']}}
        cfg = FakeConfig(CALIBRE_USE_SERVER=True, CALIBRE_SERVER='http://192.0.2.10:8081')
        with mock.patch.object(calibre, 'CONFIG', cfg), \
             mock.patch.object(calibre, 'calibre_server_get_books', return_value=(books, None)):
            result = calibre.calibre_list('', '')
        self.assertEqual(result[0]['authors'], 'Terry Pratchett & Neil Gaiman')

    def test_server_without_fragment_unchanged(self):
        called_url = self._run('terje', 'secret', server='http://192.0.2.10:8081').args[1]
        self.assertNotIn('#', called_url)
        self.assertNotIn('library=', called_url)
        self.assertTrue(called_url.startswith('http://192.0.2.10:8081/ajax/library-info'))
