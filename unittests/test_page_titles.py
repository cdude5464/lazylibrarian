#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test that page titles built from request values are escaped

import os
from unittest import mock

from lazylibrarian import webServe
from lazylibrarian.filesystem import DIRS
from unittests.unittesthelpers import LLTestCaseWithStartup

PAYLOAD = '</title><script>alert(1)</script>'


class PageTitleTest(LLTestCaseWithStartup):

    def setUp(self):
        # templates live under the program dir, which points at unittests here
        self.addCleanup(setattr, DIRS, 'PROG_DIR', DIRS.PROG_DIR)
        DIRS.PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        look = self.cfg()['HTTP_LOOK']
        self.addCleanup(self.cfg().set_str, 'HTTP_LOOK', look)
        for p in (mock.patch.object(webServe.WebInterface, 'check_permitted'),
                  mock.patch.object(webServe, 'search_item', return_value=[])):
            p.start()
            self.addCleanup(p.stop)

    @staticmethod
    def text(page) -> str:
        return page.decode() if isinstance(page, bytes) else page

    def assert_escaped(self, page: str):
        self.assertNotIn('Mako Runtime Error', page)
        self.assertNotIn('<script>alert(1)', page)
        self.assertIn('&lt;/title&gt;&lt;script&gt;alert(1)&lt;/script&gt;', page)

    def test_manual_search_title(self):
        for look in ('bookstrap', 'modern'):
            with self.subTest(look=look):
                self.cfg().set_str('HTTP_LOOK', look)
                page = webServe.WebInterface().booksearch(author=PAYLOAD, title='x', bookid='1', action='e_author')
                self.assert_escaped(self.text(page))

    def test_title_in_script_and_link(self):
        self.cfg().set_str('HTTP_LOOK', 'bookstrap')
        page = self.text(webServe.serve_template(templatename='dlresult.html', title="it's", prefix='', message='',
                                                 rowid=''))
        self.assertIn('var title = "it\'s";', page)
        page = self.text(webServe.serve_template(templatename='coverwall.html', title='Books (Wanted) & more',
                                                 results=[], redirect='books', have='1', columns=4))
        self.assertIn('&title=Books+%28Wanted%29+%26+more"', page)
