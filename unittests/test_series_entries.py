#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test add_series_entries() in bookdict.py

import contextlib
from unittest import mock

from lazylibrarian import bookdict
from lazylibrarian.database import DBConnection
from lazylibrarian.dbupgrade import db_upgrade, upgrade_needed
from lazylibrarian.filesystem import DIRS, remove_file
from unittests.unittesthelpers import LLTestCaseWithConfigandDIRS


def member_bookdict(bookid: str):
    return ({'bookid': bookid, 'bookname': 'Krev elfu', 'bookimg': 'images/nocover.png', 'booklink': '',
             'bookdate': '1994', 'booklang': 'Czech', 'first_publish_year': '1994'}, True)


class SeriesEntriesTest(LLTestCaseWithConfigandDIRS):

    def setUp(self):
        DIRS.DBFILENAME = "test-series.db"
        with contextlib.suppress(FileNotFoundError):
            remove_file(DIRS.get_dbfile())
        db_upgrade(upgrade_needed(), restartjobs=False)
        db = DBConnection()
        try:
            # added first, and unlinked from dbk so its dbk_id is empty
            db.action("INSERT INTO authors (AuthorID, AuthorName, dbk_id, Status) "
                      "VALUES ('111', 'Unrelated Writer', '', 'Active')")
            db.action("INSERT INTO authors (AuthorID, AuthorName, AKA, dbk_id, Status) "
                      "VALUES ('DBK5', 'Andrzej Sapkowski', 'Sapkowski Andrzej', 'DBK5', 'Active')")
            db.action("INSERT INTO books (AuthorID, BookID, BookName, dbk_id) "
                      "VALUES ('DBK5', '433', 'Posledni prani', '433')")
        finally:
            db.close()
        status = self.cfg()['NEWSERIES_STATUS']
        self.cfg().set_str('NEWSERIES_STATUS', 'Active')
        self.addCleanup(self.cfg().set_str, 'NEWSERIES_STATUS', status)
        for p in (mock.patch.object(bookdict, 'CONFIG', self.cfg()),
                  mock.patch.object(bookdict, 'get_book_cover', return_value=('images/nocover.png', None))):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        remove_file(DIRS.get_dbfile())

    def add_member(self, author_link: str, author_name: str = 'Andrzej Sapkowski'):
        book = {'source': 'DBK', 'series': [('Zaklinac', 'DBK77', '1')], 'authorid': 'DBK5',
                'authorname': 'Andrzej Sapkowski', 'bookid': '433'}

        def members(_series_id, _series_name):
            return [('2', 'Krev elfu', author_name, author_link, '999', '1994')]

        bookdict.add_series_entries(book, 'Skipped', 'Skipped', members, member_bookdict)
        db = DBConnection()
        try:
            book_author = db.match("SELECT AuthorID FROM books WHERE BookID='999'")['AuthorID']
            series_authors = {row['AuthorID'] for row in
                              db.select("SELECT AuthorID FROM seriesauthors WHERE SeriesID='DBK77'")}
        finally:
            db.close()
        return book_author, series_authors

    def test_member_without_author_id_goes_to_named_author(self):
        book_author, series_authors = self.add_member('')
        self.assertEqual(book_author, 'DBK5')
        self.assertEqual(series_authors, {'DBK5'})

    def test_member_with_author_id(self):
        book_author, series_authors = self.add_member('DBK5')
        self.assertEqual(book_author, 'DBK5')
        self.assertEqual(series_authors, {'DBK5'})

    def test_member_without_author_id_aka(self):
        # get_preferred_author settles on the stored author, the lookup must follow it
        book_author, series_authors = self.add_member('', 'Sapkowski Andrzej')
        self.assertEqual(book_author, 'DBK5')
        self.assertEqual(series_authors, {'DBK5'})
