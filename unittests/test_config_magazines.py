#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test the per-title magazine and comic options on the config page are escaped

import os
from html.parser import HTMLParser
from unittest import mock

from lazylibrarian import webServe
from lazylibrarian.database import DBConnection
from lazylibrarian.filesystem import DIRS
from unittests.unittesthelpers import LLTestCaseWithStartup

TITLE = 'Mag & Co "Special" </label><script>alert(1)</script>'
REJECT = 'a & b "c" <d>'


class InputNames(HTMLParser):
    """ Collect name -> value of every input, attribute values come back unescaped like a browser sends them """
    def __init__(self):
        super().__init__()
        self.inputs = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'input' and attrs.get('name'):
            self.inputs[attrs['name']] = attrs.get('value')


class ConfigMagazinesTest(LLTestCaseWithStartup):

    def setUp(self):
        self.addCleanup(setattr, DIRS, 'PROG_DIR', DIRS.PROG_DIR)
        DIRS.PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        db = DBConnection()
        try:
            db.action("INSERT INTO magazines (Title, Status, Reject, Regex, Genre, DateType, CoverPage, Language) "
                      "VALUES (?, 'Active', ?, '', '', '', 1, 'en')", (TITLE, REJECT))
            db.action("INSERT INTO comics (ComicID, Title, Status, Genre) VALUES ('C1', ?, 'Active', '')", (TITLE,))
        finally:
            db.close()
        self.addCleanup(self.remove_rows)
        # put the write counts back, so these don't look changed to the next config save.
        # Cleanups run last in first out, so this one runs last
        for key in ('HTTP_LOOK', 'MAG_TAB', 'COMIC_TAB'):
            item = self.cfg().config[key]
            self.addCleanup(setattr, item, 'accesses', item.accesses.copy())
        look = self.cfg()['HTTP_LOOK']
        self.addCleanup(self.cfg().set_str, 'HTTP_LOOK', look)
        for key in ('MAG_TAB', 'COMIC_TAB'):
            old = self.cfg().get_bool(key)
            self.cfg().set_bool(key, True)
            self.addCleanup(self.cfg().set_bool, key, old)
        p = mock.patch.object(webServe.WebInterface, 'check_permitted')
        p.start()
        self.addCleanup(p.stop)

    @staticmethod
    def remove_rows():
        db = DBConnection()
        try:
            db.action('DELETE FROM magazines WHERE Title=?', (TITLE,))
            db.action("DELETE FROM comics WHERE ComicID='C1'")
        finally:
            db.close()

    def test_titles_escaped_and_field_names_round_trip(self):
        for look in ('bookstrap', 'modern'):
            with self.subTest(look=look):
                self.cfg().set_str('HTTP_LOOK', look)
                page = webServe.WebInterface().config()
                page = page.decode() if isinstance(page, bytes) else page
                self.assertNotIn('Mako Runtime Error', page)
                self.assertNotIn('<script>alert(1)', page)
                self.assertIn('&lt;/label&gt;&lt;script&gt;alert(1)&lt;/script&gt;', page)
                parser = InputNames()
                parser.feed(page)
                # config_update looks the fields up by the raw title
                self.assertEqual(parser.inputs[f'reject_list[{TITLE}]'], REJECT)
                for field in ('regex', 'genre_list', 'datetype', 'coverpage', 'language'):
                    self.assertIn(f'{field}[{TITLE}]', parser.inputs)
