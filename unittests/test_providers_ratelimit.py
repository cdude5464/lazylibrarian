#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test that a provider answering "429 Too Many Requests" is backed off with an escalating delay

from unittest import mock

from unittests.unittesthelpers import LLTestCase
from lazylibrarian.blockhandler import BLOCKHANDLER
from lazylibrarian.config2 import LLConfigHandler
from lazylibrarian.configdefs import BASE_DEFAULTS
from lazylibrarian.providers import newznab_plus

RESPONSE_429 = 'Response status 429: Too Many Requests'
EMPTY_RESULTS = b'<?xml version="1.0"?><rss><channel></channel></rss>'


class ProvidersRateLimitTest(LLTestCase):
    HOST = 'http://prowlarr.invalid:9696/7/api'
    BOOK = {'bookid': '1', 'authorName': 'Jane Austen', 'bookName': 'Emma', 'bookSub': '',
            'searchterm': 'Jane Austen Emma', 'library': 'eBook'}

    def setUp(self):
        super().setUp()
        BLOCKHANDLER.clear_all()
        cfg = LLConfigHandler(defaults=BASE_DEFAULTS, configfile=self.COMPLEX_INI_FILE)
        self.provider = cfg.providers('TORZNAB')[0]
        self.provider['HOST'] = self.HOST
        self.provider['GENERALSEARCH'] = 'search'
        self.provider['BOOKCAT'] = '7000'

    def tearDown(self):
        BLOCKHANDLER.clear_all()
        super().tearDown()

    def _search(self, response, clock):
        with mock.patch('lazylibrarian.providers.fetch_url', return_value=response), \
                mock.patch('lazylibrarian.blockhandler.time.time', side_effect=lambda: clock[0]):
            newznab_plus(self.BOOK, self.provider, 'book', 'nzb')

    def _blocked_for(self, clock):
        return BLOCKHANDLER._provider_list[self.HOST]['resume'] - clock[0]

    def test_repeated_429_escalates_and_success_resets(self):
        clock = [1_000_000]
        self._search((RESPONSE_429, False), clock)
        self.assertEqual(self._blocked_for(clock), 30)

        clock[0] += 31
        self._search((RESPONSE_429, False), clock)
        self.assertEqual(self._blocked_for(clock), 120)

        clock[0] += 121
        self._search((EMPTY_RESULTS, True), clock)  # answered normally: escalation is forgotten
        clock[0] += 1
        self._search((RESPONSE_429, False), clock)
        self.assertEqual(self._blocked_for(clock), 30)
