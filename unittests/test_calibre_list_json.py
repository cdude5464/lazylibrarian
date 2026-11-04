#  This file is part of Lazylibrarian.
#
# Purpose:
#   Issue #2852 ("Extra data" on Calibre sync): `calibredb list --for-machine` returned a
#   complete, valid JSON array with extra bytes trailing after it on a real, large library.
#   json.loads() rejected the whole response over that trailing content, uncaught - breaking
#   calibre_list()'s own documented "return an error message (not a dict) on failure"
#   contract and turning into an unhandled exception in sync_calibre_list()'s caller instead
#   of the graceful string-error path it already expects (see calibre.py:294,
#   "if not isinstance(calibrelist, list): return f'\"{calibrelist}\"'").

from unittest import mock

from lazylibrarian import calibre
from unittests.unittesthelpers import LLTestCase


class FakeConfig(dict):
    def get_bool(self, key):
        return bool(self.get(key))


class CalibreListJsonTest(LLTestCase):

    def _run(self, res):
        cfg = FakeConfig(CALIBRE_USE_SERVER=False)
        with mock.patch.object(calibre, 'CONFIG', cfg), \
             mock.patch.object(calibre, 'calibredb', return_value=(res, '', 0)):
            return calibre.calibre_list(None, None)

    def test_plain_valid_json_still_parses_as_before(self):
        result = self._run('[{"id": 1, "title": "A Book", "authors": "Someone"}]')
        self.assertEqual(result, [{'id': 1, 'title': 'A Book', 'authors': 'Someone'}])

    def test_valid_json_with_trailing_garbage_still_parses_the_list(self):
        # the exact reported symptom: a complete, valid array followed by something else
        res = '[{"id": 1, "title": "A Book", "authors": "Someone"}]\nUpdating things ***\n'
        result = self._run(res)
        self.assertEqual(result, [{'id': 1, 'title': 'A Book', 'authors': 'Someone'}])

    def test_trailing_garbage_is_logged_not_silently_dropped(self):
        res = '[{"id": 1, "title": "A Book", "authors": "Someone"}]\nUpdating things ***\n'
        with mock.patch.object(calibre, 'CONFIG', FakeConfig(CALIBRE_USE_SERVER=False)), \
             mock.patch.object(calibre, 'calibredb', return_value=(res, '', 0)), \
             self.assertLogs('lazylibrarian.calibre', level='WARNING') as logs:
            calibre.calibre_list(None, None)
        self.assertTrue(any('trailing data' in m or 'Updating things' in m for m in logs.output))

    def test_genuinely_malformed_json_returns_an_error_string_not_an_exception(self):
        # truncated mid-array - not "extra data", a real parse failure - must still surface as
        # the documented "not a list" error contract, not propagate as an uncaught exception
        result = self._run('[{"id": 1, "title": "A Book"')
        self.assertIsInstance(result, str)

    def test_empty_response_returns_an_error_string_not_an_exception(self):
        result = self._run('')
        self.assertIsInstance(result, str)
