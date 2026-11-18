#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test that the manual search Snatch link hands the provider url
#   and title back to snatch_book unchanged, in every interface

import html
import json
import os
import re
from unittest import mock
from urllib.parse import parse_qs, quote, quote_plus, urlsplit

from lazylibrarian import webServe
from lazylibrarian.filesystem import DIRS
from unittests.unittesthelpers import LLTestCaseWithStartup

URL = 'http://indexer.local/prowlarr/2/download?apikey=abc&link=x%2By&file=First+Among+Sequels'
TITLE = 'First Among Sequels & Other Tales'


class ManualSearchSnatchTest(LLTestCaseWithStartup):

    def setUp(self):
        # templates live under the program dir, which points at unittests here
        self.addCleanup(setattr, DIRS, 'PROG_DIR', DIRS.PROG_DIR)
        DIRS.PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        look = self.cfg()['HTTP_LOOK']
        self.addCleanup(self.cfg().set_str, 'HTTP_LOOK', look)
        # the result as manualbook.search_item builds it
        result = {'score': 99, 'title': TITLE, 'provider': 'Audiobook Bay', 'size': 1000, 'date': '',
                  'url': quote_plus(URL.encode('utf-8')), 'mode': 'torznab', 'url_title': quote(TITLE),
                  'prov_page': ''}
        for p in (mock.patch.object(webServe.WebInterface, 'check_permitted'),
                  mock.patch.object(webServe, 'search_item', return_value=[result])):
            p.start()
            self.addCleanup(p.stop)

    def snatch_link(self, look: str) -> str:
        self.cfg().set_str('HTTP_LOOK', look)
        page = webServe.WebInterface().booksearch(author='Jasper Fforde', title='x', bookid='1', action='a_full')
        page = page.decode() if isinstance(page, bytes) else page
        self.assertNotIn('Mako Runtime Error', page)
        if look == 'modern':
            rows = re.search(r'var llManualRows = (.*?);\n', page).group(1)
            return json.loads(rows)[0]['snatch']
        return html.unescape(re.search(r'href="(snatch_book\?[^"]+)"', page).group(1))

    def test_snatch_link_round_trips(self):
        for look in ('bookstrap', 'modern'):
            with self.subTest(look=look):
                # cherrypy decodes the query string once before calling snatch_book
                params = parse_qs(urlsplit(self.snatch_link(look)).query)
                self.assertEqual(params['url'], [URL])
                self.assertEqual(params['title'], [TITLE])
