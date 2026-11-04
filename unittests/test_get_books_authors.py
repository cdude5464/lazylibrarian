#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test the book list rows get_books() returns for books with several authors

import contextlib
from unittest import mock

import lazylibrarian
from lazylibrarian import webServe
from lazylibrarian.database import DBConnection
from lazylibrarian.dbupgrade import db_upgrade, upgrade_needed
from lazylibrarian.filesystem import DIRS, remove_file
from unittests.unittesthelpers import LLTestCaseWithConfigandDIRS


class GetBooksAuthorsTest(LLTestCaseWithConfigandDIRS):

    def setUp(self):
        self.addCleanup(setattr, DIRS, 'DBFILENAME', DIRS.DBFILENAME)
        DIRS.DBFILENAME = "test-getbooks.db"
        with contextlib.suppress(FileNotFoundError):
            remove_file(DIRS.get_dbfile())
        db_upgrade(upgrade_needed(), restartjobs=False)
        db = DBConnection()
        try:
            db.action("INSERT INTO authors (AuthorID, AuthorName, Status) VALUES ('A1', 'Terry Pratchett', 'Active')")
            db.action("INSERT INTO authors (AuthorID, AuthorName, Status) VALUES ('A2', 'Neil Gaiman', 'Active')")
            db.action("INSERT INTO books (AuthorID, BookID, BookName, Status, AudioStatus) "
                      "VALUES ('A1', 'B1', 'Good Omens', 'Wanted', 'Skipped')")
            db.action("INSERT INTO bookauthors (BookID, AuthorID, Role) VALUES ('B1', 'A1', 1)")
            db.action("INSERT INTO bookauthors (BookID, AuthorID, Role) VALUES ('B1', 'A2', 2)")
            db.action("INSERT INTO series (SeriesID, SeriesName, Status) VALUES (7, 'Omens', 'Active')")
            db.action("INSERT INTO member (SeriesID, BookID, SeriesNum) VALUES (7, 'B1', '1')")
        finally:
            db.close()
        for key, value in (('USER_ACCOUNTS', False), ('EBOOK_TAB', True)):
            old = self.cfg().get_bool(key)
            self.cfg().set_bool(key, value)
            self.addCleanup(self.cfg().set_bool, key, old)
        p = mock.patch.object(lazylibrarian, 'PRIMARY_AUTHORS', True)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        remove_file(DIRS.get_dbfile())

    @staticmethod
    def authors_and_series(**kwargs):
        res = webServe.WebInterface().get_books(iDisplayLength=-1, **kwargs)
        # columns 8 and 12 of each row hold the author id and the series
        return sorted((row[8], row[12]) for row in res['aaData'])

    def test_primary_authors_one_row_per_book(self):
        for kwargs in ({'source': 'Books'}, {'source': 'Manage', 'whichStatus': 'All'}):
            with self.subTest(**kwargs):
                self.assertEqual(self.authors_and_series(**kwargs), [('A1', '7~Omens #1')])

    def test_co_writers_one_row_per_book(self):
        # writer and creator both map to the primary role
        db = DBConnection()
        try:
            db.action("UPDATE bookauthors SET Role=1 WHERE AuthorID='A2'")
        finally:
            db.close()
        for kwargs in ({'source': 'Books'}, {'source': 'Manage', 'whichStatus': 'All'}):
            with self.subTest(**kwargs):
                self.assertEqual(self.authors_and_series(**kwargs), [('A1', '7~Omens #1')])
        # the book's own author wins over the first one added
        db = DBConnection()
        try:
            db.action("UPDATE books SET AuthorID='A2' WHERE BookID='B1'")
        finally:
            db.close()
        self.assertEqual(self.authors_and_series(source='Books'), [('A2', '7~Omens #1')])
        # each co-writer's own page still lists the book
        for authorid in ('A1', 'A2'):
            with self.subTest(author=authorid):
                self.assertEqual(self.authors_and_series(source='Author', AuthorID=authorid),
                                 [(authorid, '7~Omens #1')])

    def test_book_author_not_primary(self):
        # a book whose own author is only a contributor still gets a row
        db = DBConnection()
        try:
            db.action("UPDATE books SET AuthorID='A2' WHERE BookID='B1'")
        finally:
            db.close()
        self.assertEqual(self.authors_and_series(source='Books'), [('A1', '7~Omens #1')])

    def test_all_authors_one_row_per_author(self):
        lazylibrarian.PRIMARY_AUTHORS = False
        for kwargs in ({'source': 'Books'}, {'source': 'Manage', 'whichStatus': 'All'}):
            with self.subTest(**kwargs):
                self.assertEqual(self.authors_and_series(**kwargs), [('A1', '7~Omens #1'), ('A2', '7~Omens #1')])
