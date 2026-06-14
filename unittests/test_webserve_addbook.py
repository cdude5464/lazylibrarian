#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test search-result Add Book duplicate handling in webServe.py

import logging
from unittest import mock

import lazylibrarian
from lazylibrarian import ROLE
from lazylibrarian.config2 import CONFIG
from lazylibrarian.database import DBConnection
from lazylibrarian.dbupgrade import db_upgrade, upgrade_needed
from lazylibrarian.filesystem import DIRS, remove_file
from lazylibrarian.startup import StartupLazyLibrarian
from unittests.unittesthelpers import LLTestCaseWithConfigandDIRS


class WebServeAddBookTest(LLTestCaseWithConfigandDIRS):

    def setUp(self):
        logging.getLogger('').setLevel(logging.ERROR)
        DIRS.DBFILENAME = "test-db.db"
        self._remove_test_db()
        curr_ver = upgrade_needed()
        db_upgrade(curr_ver, restartjobs=False)
        lazylibrarian.INFOSOURCES = StartupLazyLibrarian.build_sources()
        CONFIG.set_str('BOOK_API', 'GoodReads')
        CONFIG.set_str('GB_API', 'test-google-books-key')
        CONFIG.set_bool('OL_API', False)
        CONFIG.set_bool('HC_API', False)

    def tearDown(self):
        self._remove_test_db()

    @staticmethod
    def _remove_test_db():
        for filename in [DIRS.get_dbfile(), DIRS.get_dbfile() + '-shm', DIRS.get_dbfile() + '-wal']:
            try:
                remove_file(filename)
            except FileNotFoundError:
                pass

    @staticmethod
    def _insert_author(db, authorid='author-1', authorname='Chuck Palahniuk'):
        db.upsert(
            'authors',
            {'AuthorName': authorname, 'Status': 'Paused', 'AuthorImg': 'images/nophoto.png'},
            {'AuthorID': authorid})

    @staticmethod
    def _insert_book(db, bookid, title, authorid='author-1', status='Skipped', audio_status='Skipped',
                     gr_id=None, gb_id=None):
        values = {
            'AuthorID': authorid,
            'BookName': title,
            'Status': status,
            'AudioStatus': audio_status,
            'BookAdded': '2026-06-14',
        }
        if gr_id:
            values['gr_id'] = gr_id
        if gb_id:
            values['gb_id'] = gb_id
        db.upsert('books', values, {'BookID': bookid})
        db.action(
            'INSERT into bookauthors (AuthorID, BookID, Role) VALUES (?, ?, ?)',
            (authorid, bookid, ROLE['PRIMARY']), suppress='UNIQUE')
        db.commit()

    @staticmethod
    def _google_result(bookid='GB1', title='Rant', authorid='author-1', authorname='Chuck Palahniuk'):
        return {
            'bookid': bookid,
            'bookname': title,
            'authorid': authorid,
            'authorname': authorname,
            'source': 'GoogleBooks',
            'highest_fuzz': 100,
            'bookrate_count': 0,
            'contributors': [],
            'series': [],
        }

    @staticmethod
    def _mock_search(result):
        def search(_term, source):
            if source == 'GoogleBooks':
                return [result]
            return []
        return search

    def test_update_existing_book_status_does_not_unignore_search_result(self):
        from lazylibrarian import webServe

        db = DBConnection()
        try:
            self._insert_author(db)
            self._insert_book(db, 'ignored-book', 'Rant', status='Ignored', gr_id='12345')
        finally:
            db.close()

        match = webServe.update_existing_book_status('12345', ebook_status='Wanted', preferred_key='gr_id')
        self.assertIsNone(match)

        db = DBConnection()
        try:
            row = db.match("SELECT Status FROM books WHERE BookID='ignored-book'")
            self.assertEqual('Ignored', row['Status'])
        finally:
            db.close()

    def test_google_result_updates_existing_canonical_row_without_audio_downgrade(self):
        from lazylibrarian import webServe

        db = DBConnection()
        try:
            self._insert_author(db)
            self._insert_book(db, 'canonical-book', 'Rant', status='Skipped', audio_status='Have', gb_id='GB1')
        finally:
            db.close()

        result = self._google_result()
        with mock.patch.object(webServe, 'search_for', side_effect=self._mock_search(result)):
            match = webServe._add_search_result_book_to_db(
                'GB1', 'Wanted', 'Skipped', title='Rant', authorname='Chuck Palahniuk',
                existing_ebook_status='Wanted', existing_audio_status=None)

        self.assertEqual('canonical-book', match['BookID'])
        db = DBConnection()
        try:
            row = db.match("SELECT Status,AudioStatus FROM books WHERE BookID='canonical-book'")
            self.assertEqual('Wanted', row['Status'])
            self.assertEqual('Have', row['AudioStatus'])
            count = db.match("SELECT count(*) AS counter FROM books WHERE AuthorID='author-1'")
            self.assertEqual(1, count['counter'])
        finally:
            db.close()

    def test_google_result_does_not_resurrect_ignored_duplicate_provider_row(self):
        from lazylibrarian import webServe

        db = DBConnection()
        try:
            self._insert_author(db)
            self._insert_book(db, 'ignored-duplicate', 'Rant', status='Ignored', gb_id='GB1')
        finally:
            db.close()

        result = self._google_result()
        with mock.patch.object(webServe, 'search_for', side_effect=self._mock_search(result)):
            match = webServe._add_search_result_book_to_db(
                'GB1', 'Wanted', 'Skipped', title='Rant', authorname='Chuck Palahniuk',
                existing_ebook_status='Wanted', existing_audio_status=None)

        self.assertTrue(webServe._is_blocked_add_result(match))
        db = DBConnection()
        try:
            row = db.match("SELECT Status FROM books WHERE BookID='ignored-duplicate'")
            self.assertEqual('Ignored', row['Status'])
            count = db.match("SELECT count(*) AS counter FROM books WHERE AuthorID='author-1'")
            self.assertEqual(1, count['counter'])
        finally:
            db.close()

    def test_google_result_does_not_insert_over_ignored_exact_title_match(self):
        from lazylibrarian import webServe

        db = DBConnection()
        try:
            self._insert_author(db)
            self._insert_book(db, 'ignored-duplicate', 'Rant', status='Ignored')
        finally:
            db.close()

        result = self._google_result()
        with mock.patch.object(webServe, 'search_for', side_effect=self._mock_search(result)):
            match = webServe._add_search_result_book_to_db(
                'GB1', 'Wanted', 'Skipped', title='Rant', authorname='Chuck Palahniuk',
                existing_ebook_status='Wanted', existing_audio_status=None)

        self.assertTrue(webServe._is_blocked_add_result(match))
        db = DBConnection()
        try:
            row = db.match("SELECT Status FROM books WHERE BookID='ignored-duplicate'")
            self.assertEqual('Ignored', row['Status'])
            count = db.match("SELECT count(*) AS counter FROM books WHERE AuthorID='author-1'")
            self.assertEqual(1, count['counter'])
        finally:
            db.close()

    def test_google_result_refuses_same_author_near_duplicate_title_insert(self):
        from lazylibrarian import webServe

        db = DBConnection()
        try:
            self._insert_author(db)
            self._insert_book(db, 'canonical-book', 'Rant', status='Skipped')
            row = db.match("SELECT BookID FROM books WHERE AuthorID='author-1'")
            self.assertEqual('canonical-book', row['BookID'])
        finally:
            db.close()

        result = self._google_result(title='Rant: An Oral Biography of Buster Casey')
        with mock.patch.object(webServe, 'search_for', side_effect=self._mock_search(result)):
            match = webServe._add_search_result_book_to_db(
                'GB1', 'Wanted', 'Skipped', title='Rant: An Oral Biography of Buster Casey',
                authorname='Chuck Palahniuk', existing_ebook_status='Wanted', existing_audio_status=None)

        self.assertTrue(webServe._is_blocked_add_result(match))
        db = DBConnection()
        try:
            count = db.match("SELECT count(*) AS counter FROM books WHERE AuthorID='author-1'")
            self.assertEqual(1, count['counter'])
        finally:
            db.close()

    def test_google_result_stamps_existing_normalized_title_match(self):
        from lazylibrarian import webServe

        db = DBConnection()
        try:
            self._insert_author(db)
            self._insert_book(db, 'canonical-book', 'Rant - An Oral Biography of Buster Casey',
                              status='Skipped')
            row = db.match("SELECT BookID FROM books WHERE AuthorID='author-1'")
            self.assertEqual('canonical-book', row['BookID'])
        finally:
            db.close()

        result = self._google_result(title='Rant: An Oral Biography of Buster Casey')
        with mock.patch.object(webServe, 'search_for', side_effect=self._mock_search(result)):
            match = webServe._add_search_result_book_to_db(
                'GB1', 'Wanted', 'Skipped', title='Rant: An Oral Biography of Buster Casey',
                authorname='Chuck Palahniuk', existing_ebook_status='Wanted', existing_audio_status=None)

        self.assertEqual('canonical-book', match['BookID'])
        db = DBConnection()
        try:
            row = db.match("SELECT Status,gb_id FROM books WHERE BookID='canonical-book'")
            self.assertEqual('Wanted', row['Status'])
            self.assertEqual('GB1', row['gb_id'])
            count = db.match("SELECT count(*) AS counter FROM books WHERE AuthorID='author-1'")
            self.assertEqual(1, count['counter'])
        finally:
            db.close()
