#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test search-result Add Book duplicate handling in webServe.py

import logging
from unittest import mock

import cherrypy

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
    def _google_result(bookid='GB1', title='Rant', authorid='author-1', authorname='Chuck Palahniuk',
                       highest_fuzz=100, bookrate_count=0):
        return {
            'bookid': bookid,
            'bookname': title,
            'authorid': authorid,
            'authorname': authorname,
            'source': 'GoogleBooks',
            'highest_fuzz': highest_fuzz,
            'bookrate_count': bookrate_count,
            'booksub': '',
            'bookisbn': '',
            'bookpub': '',
            'bookdate': '2026',
            'booklang': 'en',
            'booklink': '',
            'bookrate': 0.0,
            'bookimg': 'images/nocover.png',
            'bookpages': 0,
            'bookgenre': '',
            'bookdesc': '',
            'contributors': [],
            'series': [],
        }

    @classmethod
    def _goodreads_result(cls, bookid='12345', title='Rant', authorid='author-1',
                          authorname='Chuck Palahniuk', highest_fuzz=100, bookrate_count=0):
        result = cls._google_result(
            bookid=bookid, title=title, authorid=authorid, authorname=authorname,
            highest_fuzz=highest_fuzz, bookrate_count=bookrate_count)
        result['source'] = 'GoodReads'
        result['booklink'] = f'https://www.goodreads.com/book/show/{bookid}'
        return result

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

    def test_existing_status_update_requires_compatible_title_when_provided(self):
        from lazylibrarian import webServe

        db = DBConnection()
        try:
            self._insert_author(db)
            self._insert_book(db, 'polluted-book', 'Different Book', status='Skipped', gb_id='GB1')
        finally:
            db.close()

        match = webServe.update_existing_book_status(
            'GB1', ebook_status='Wanted', preferred_key='gb_id', title='Rant', authorid='author-1')

        self.assertIsNone(match)
        db = DBConnection()
        try:
            row = db.match("SELECT Status FROM books WHERE BookID='polluted-book'")
            self.assertEqual('Skipped', row['Status'])
        finally:
            db.close()

    def test_exact_fallback_provider_id_beats_higher_ranked_candidate(self):
        from lazylibrarian import webServe

        db = DBConnection()
        try:
            self._insert_author(db)
            self._insert_book(db, 'exact-canonical', 'Rant', status='Skipped', gb_id='GB1')
            self._insert_book(db, 'wrong-canonical', 'Rant', status='Skipped', gb_id='GB-WRONG')
        finally:
            db.close()

        wrong = self._google_result(bookid='GB-WRONG', highest_fuzz=100, bookrate_count=999)
        exact = self._google_result(bookid='GB1', highest_fuzz=95, bookrate_count=0)

        def search(_term, source):
            if source == 'GoogleBooks':
                return [wrong, exact]
            return []

        with mock.patch.object(webServe, 'search_for', side_effect=search):
            match = webServe._add_search_result_book_to_db(
                'GB1', 'Wanted', 'Skipped', title='Rant', authorname='Chuck Palahniuk',
                existing_ebook_status='Wanted', existing_audio_status=None)

        self.assertEqual('exact-canonical', match['BookID'])
        db = DBConnection()
        try:
            exact_row = db.match("SELECT Status FROM books WHERE BookID='exact-canonical'")
            wrong_row = db.match("SELECT Status FROM books WHERE BookID='wrong-canonical'")
            self.assertEqual('Wanted', exact_row['Status'])
            self.assertEqual('Skipped', wrong_row['Status'])
        finally:
            db.close()

    def test_preferred_search_result_source_is_tried_before_primary_source(self):
        from lazylibrarian import webServe

        db = DBConnection()
        try:
            self._insert_author(db)
            self._insert_book(db, 'canonical-book', 'Rant', status='Skipped', gb_id='GB1')
        finally:
            db.close()

        calls = []
        result = self._google_result()

        def search(_term, source):
            calls.append(source)
            if source == 'GoogleBooks':
                return [result]
            return []

        with (
            mock.patch.object(webServe, 'search_for', side_effect=search),
            mock.patch.object(webServe, '_search_result_detail_for_source', return_value=None),
        ):
            match = webServe._add_search_result_book_to_db(
                'GB1', 'Wanted', 'Skipped', title='Rant', authorname='Chuck Palahniuk',
                existing_ebook_status='Wanted', existing_audio_status=None,
                preferred_source='GoogleBooks')

        self.assertEqual('canonical-book', match['BookID'])
        self.assertEqual(['GoogleBooks'], calls)

    def test_preferred_source_does_not_fuzzy_add_from_primary_when_exact_missing(self):
        from lazylibrarian import webServe

        db = DBConnection()
        try:
            self._insert_author(db)
            self._insert_book(db, 'goodreads-book', 'Rant', status='Skipped', gr_id='12345')
        finally:
            db.close()

        calls = []
        google_other = self._google_result(bookid='GB-OTHER', highest_fuzz=100)
        goodreads_match = dict(google_other)
        goodreads_match['bookid'] = '12345'
        goodreads_match['source'] = 'GoodReads'

        def search(_term, source):
            calls.append(source)
            if source == 'GoogleBooks':
                return [google_other]
            if source == 'GoodReads':
                return [goodreads_match]
            return []

        with mock.patch.object(webServe, 'search_for', side_effect=search):
            match = webServe._add_search_result_book_to_db(
                'GB1', 'Wanted', 'Skipped', title='Rant', authorname='Chuck Palahniuk',
                existing_ebook_status='Wanted', existing_audio_status=None,
                preferred_source='GoogleBooks')

        self.assertIsNone(match)
        self.assertEqual(['GoogleBooks'], calls)
        db = DBConnection()
        try:
            row = db.match("SELECT Status FROM books WHERE BookID='goodreads-book'")
            self.assertEqual('Skipped', row['Status'])
        finally:
            db.close()

    def test_preferred_source_uses_exact_detail_when_search_omits_clicked_id(self):
        from lazylibrarian import webServe

        google_other = self._google_result(bookid='GB-OTHER', highest_fuzz=100)
        exact_detail = self._google_result(bookid='GB1', highest_fuzz=100)

        def search(_term, source):
            if source == 'GoogleBooks':
                return [google_other]
            return []

        with (
            mock.patch.object(webServe, 'search_for', side_effect=search),
            mock.patch.object(webServe, '_search_result_detail_for_source', return_value=exact_detail),
        ):
            match = webServe._add_search_result_book_to_db(
                'GB1', 'Wanted', 'Skipped', title='Rant', authorname='Chuck Palahniuk',
                existing_ebook_status='Wanted', existing_audio_status=None,
                preferred_source='GoogleBooks')

        self.assertEqual('GB1', match['BookID'])
        db = DBConnection()
        try:
            row = db.match("SELECT Status,gb_id FROM books WHERE BookID='GB1'")
            self.assertEqual('Wanted', row['Status'])
            self.assertEqual('GB1', row['gb_id'])
        finally:
            db.close()

    def test_goodreads_source_aware_safe_fallback_when_search_omits_clicked_id(self):
        from lazylibrarian import webServe

        goodreads_other = self._goodreads_result(
            bookid='999999', title='The Canterbury Tales',
            authorid='1838', authorname='Geoffrey Chaucer')

        def search(_term, source):
            if source == 'GoodReads':
                return [goodreads_other]
            return []

        with mock.patch.object(webServe, 'search_for', side_effect=search):
            match = webServe._add_search_result_book_to_db(
                '2696', 'Wanted', 'Skipped', title='The Canterbury Tales',
                authorname='Geoffrey Chaucer', authorid='1838',
                existing_ebook_status='Wanted', existing_audio_status=None,
                preferred_source='GoodReads')

        self.assertEqual('2696', match['BookID'])
        db = DBConnection()
        try:
            row = db.match("SELECT Status,AudioStatus,gr_id,BookLink FROM books WHERE BookID='2696'")
            self.assertEqual('Wanted', row['Status'])
            self.assertEqual('Skipped', row['AudioStatus'])
            self.assertEqual('2696', row['gr_id'])
            self.assertEqual('https://www.goodreads.com/book/show/2696', row['BookLink'])
            count = db.match("SELECT count(*) AS counter FROM books WHERE BookID='999999'")
            self.assertEqual(0, count['counter'])
        finally:
            db.close()

    def test_goodreads_source_aware_exact_title_retry_finds_clicked_id(self):
        from lazylibrarian import webServe

        derivative = self._goodreads_result(
            bookid='8131249',
            title='Works of Geoffrey Chaucer.  The Canterbury Tales/Troilus and Criseyde',
            authorid='1838',
            authorname='Geoffrey Chaucer')
        exact = self._goodreads_result(
            bookid='2696', title='The Canterbury Tales',
            authorid='1838', authorname='Geoffrey Chaucer')
        calls = []

        def search(term, source):
            calls.append((term, source))
            if source != 'GoodReads':
                return []
            if term == 'Geoffrey Chaucer The Canterbury Tales':
                return [derivative]
            if term == 'The Canterbury Tales':
                return [exact]
            return []

        with mock.patch.object(webServe, 'search_for', side_effect=search):
            match = webServe._add_search_result_book_to_db(
                '2696', 'Wanted', 'Skipped', title='The Canterbury Tales',
                authorname='Geoffrey Chaucer', authorid='1838',
                existing_ebook_status='Wanted', existing_audio_status=None,
                preferred_source='GoodReads')

        self.assertEqual('2696', match['BookID'])
        self.assertEqual(
            [('Geoffrey Chaucer The Canterbury Tales', 'GoodReads'), ('The Canterbury Tales', 'GoodReads')],
            calls)
        db = DBConnection()
        try:
            row = db.match("SELECT Status,AudioStatus,gr_id FROM books WHERE BookID='2696'")
            self.assertEqual('Wanted', row['Status'])
            self.assertEqual('Skipped', row['AudioStatus'])
            self.assertEqual('2696', row['gr_id'])
        finally:
            db.close()

    def test_goodreads_safe_fallback_stamps_existing_title_row(self):
        from lazylibrarian import webServe

        db = DBConnection()
        try:
            self._insert_author(db, authorid='1838', authorname='Geoffrey Chaucer')
            self._insert_book(db, 'canonical-book', 'The Canterbury Tales', authorid='1838',
                              status='Skipped')
        finally:
            db.close()

        goodreads_other = self._goodreads_result(
            bookid='999999', title='The Canterbury Tales',
            authorid='1838', authorname='Geoffrey Chaucer')

        def search(_term, source):
            if source == 'GoodReads':
                return [goodreads_other]
            return []

        with mock.patch.object(webServe, 'search_for', side_effect=search):
            match = webServe._add_search_result_book_to_db(
                '2696', 'Wanted', 'Skipped', title='The Canterbury Tales',
                authorname='Geoffrey Chaucer', authorid='1838',
                existing_ebook_status='Wanted', existing_audio_status=None,
                preferred_source='GoodReads')

        self.assertEqual('canonical-book', match['BookID'])
        db = DBConnection()
        try:
            row = db.match("SELECT Status,gr_id FROM books WHERE BookID='canonical-book'")
            self.assertEqual('Wanted', row['Status'])
            self.assertEqual('2696', row['gr_id'])
            count = db.match("SELECT count(*) AS counter FROM books WHERE AuthorID='1838'")
            self.assertEqual(1, count['counter'])
        finally:
            db.close()

    def test_goodreads_safe_fallback_refuses_unsafe_title(self):
        from lazylibrarian import webServe

        goodreads_other = self._goodreads_result(
            bookid='999999', title='Troilus and Criseyde',
            authorid='1838', authorname='Geoffrey Chaucer')

        def search(_term, source):
            if source == 'GoodReads':
                return [goodreads_other]
            return []

        with mock.patch.object(webServe, 'search_for', side_effect=search):
            match = webServe._add_search_result_book_to_db(
                '2696', 'Wanted', 'Skipped', title='The Canterbury Tales',
                authorname='Geoffrey Chaucer', authorid='1838',
                existing_ebook_status='Wanted', existing_audio_status=None,
                preferred_source='GoodReads')

        self.assertIsNone(match)
        db = DBConnection()
        try:
            count = db.match("SELECT count(*) AS counter FROM books")
            self.assertEqual(0, count['counter'])
        finally:
            db.close()

    def test_goodreads_safe_fallback_refuses_subset_title(self):
        from lazylibrarian import webServe

        goodreads_other = self._goodreads_result(
            bookid='999999', title='The Canterbury Tales and Other Poems',
            authorid='1838', authorname='Geoffrey Chaucer')

        def search(_term, source):
            if source == 'GoodReads':
                return [goodreads_other]
            return []

        with mock.patch.object(webServe, 'search_for', side_effect=search):
            match = webServe._add_search_result_book_to_db(
                '2696', 'Wanted', 'Skipped', title='The Canterbury Tales',
                authorname='Geoffrey Chaucer', authorid='1838',
                existing_ebook_status='Wanted', existing_audio_status=None,
                preferred_source='GoodReads')

        self.assertIsNone(match)
        db = DBConnection()
        try:
            count = db.match("SELECT count(*) AS counter FROM books")
            self.assertEqual(0, count['counter'])
        finally:
            db.close()

    def test_goodreads_safe_fallback_refuses_coauthor_author_name(self):
        from lazylibrarian import webServe

        goodreads_other = self._goodreads_result(
            bookid='999999', title='The Canterbury Tales',
            authorid='coauthor-row', authorname='Geoffrey Chaucer David Wright')

        def search(_term, source):
            if source == 'GoodReads':
                return [goodreads_other]
            return []

        with mock.patch.object(webServe, 'search_for', side_effect=search):
            match = webServe._add_search_result_book_to_db(
                '2696', 'Wanted', 'Skipped', title='The Canterbury Tales',
                authorname='Geoffrey Chaucer', authorid='1838',
                existing_ebook_status='Wanted', existing_audio_status=None,
                preferred_source='GoodReads')

        self.assertIsNone(match)
        db = DBConnection()
        try:
            count = db.match("SELECT count(*) AS counter FROM books")
            self.assertEqual(0, count['counter'])
        finally:
            db.close()

    def test_goodreads_safe_fallback_refuses_wrong_author_id_even_with_same_name(self):
        from lazylibrarian import webServe

        goodreads_other = self._goodreads_result(
            bookid='999999', title='The Canterbury Tales',
            authorid='wrong-author', authorname='Geoffrey Chaucer')

        def search(_term, source):
            if source == 'GoodReads':
                return [goodreads_other]
            return []

        with mock.patch.object(webServe, 'search_for', side_effect=search):
            match = webServe._add_search_result_book_to_db(
                '2696', 'Wanted', 'Skipped', title='The Canterbury Tales',
                authorname='Geoffrey Chaucer', authorid='1838',
                existing_ebook_status='Wanted', existing_audio_status=None,
                preferred_source='GoodReads')

        self.assertIsNone(match)
        db = DBConnection()
        try:
            count = db.match("SELECT count(*) AS counter FROM books")
            self.assertEqual(0, count['counter'])
        finally:
            db.close()

    def test_source_less_goodreads_search_result_still_requires_exact_id(self):
        from lazylibrarian import webServe

        goodreads_other = self._goodreads_result(
            bookid='999999', title='The Canterbury Tales',
            authorid='1838', authorname='Geoffrey Chaucer')

        def search(_term, source):
            if source == 'GoodReads':
                return [goodreads_other]
            return []

        with (
            mock.patch.object(webServe, 'search_for', side_effect=search),
            mock.patch.object(webServe, '_search_result_detail_for_source', return_value=None),
        ):
            match = webServe._add_search_result_book_to_db(
                '2696', 'Wanted', 'Skipped', title='The Canterbury Tales',
                authorname='Geoffrey Chaucer', authorid='1838',
                existing_ebook_status='Wanted', existing_audio_status=None)

        self.assertIsNone(match)

    def test_bulk_goodreads_safe_fallback_uses_submitted_author_id(self):
        from lazylibrarian import webServe

        goodreads_other = self._goodreads_result(
            bookid='999999', title='The Canterbury Tales',
            authorid='1838', authorname='Geoffrey Chaucer')

        def search(_term, source):
            if source == 'GoodReads':
                return [goodreads_other]
            return []

        interface = webServe.WebInterface()
        with (
            mock.patch.object(webServe.WebInterface, 'check_permitted', return_value=None),
            mock.patch.object(webServe, 'search_for', side_effect=search),
        ):
            response = interface.mark_results_ajax(
                action='AddBook',
                **{'2696': '1838|Geoffrey+Chaucer|The+Canterbury+Tales|GoodReads'})

        self.assertEqual(1, response['passed'])
        self.assertEqual(0, response['failed'])
        db = DBConnection()
        try:
            row = db.match("SELECT Status,gr_id FROM books WHERE BookID='2696'")
            self.assertEqual('Wanted', row['Status'])
            self.assertEqual('2696', row['gr_id'])
        finally:
            db.close()

    def test_no_source_nonnumeric_bookid_requires_exact_fallback_provider_match(self):
        from lazylibrarian import webServe

        db = DBConnection()
        try:
            self._insert_author(db)
            self._insert_book(db, 'other-canonical', 'Rant', status='Skipped', gb_id='GB-OTHER')
        finally:
            db.close()

        google_other = self._google_result(bookid='GB-OTHER', highest_fuzz=100)

        def search(_term, source):
            if source == 'GoogleBooks':
                return [google_other]
            return []

        with (
            mock.patch.object(webServe, 'search_for', side_effect=search),
            mock.patch.object(webServe, '_search_result_detail_for_source', return_value=None),
        ):
            match = webServe._add_search_result_book_to_db(
                'GB1', 'Wanted', 'Skipped', title='Rant', authorname='Chuck Palahniuk',
                existing_ebook_status='Wanted', existing_audio_status=None)

        self.assertIsNone(match)
        db = DBConnection()
        try:
            row = db.match("SELECT Status FROM books WHERE BookID='other-canonical'")
            self.assertEqual('Skipped', row['Status'])
        finally:
            db.close()

    def test_no_source_numeric_bookid_requires_exact_fallback_provider_match(self):
        from lazylibrarian import webServe

        CONFIG.set_bool('HC_API', True)
        hard_cover_other = self._google_result(bookid='99999', highest_fuzz=100)
        hard_cover_other['source'] = 'HardCover'

        def search(_term, source):
            if source == 'HardCover':
                return [hard_cover_other]
            return []

        with (
            mock.patch.object(webServe, 'search_for', side_effect=search),
            mock.patch.object(webServe, '_search_result_detail_for_source', return_value=None),
        ):
            match = webServe._add_search_result_book_to_db(
                '12345', 'Wanted', 'Skipped', title='Rant', authorname='Chuck Palahniuk',
                existing_ebook_status='Wanted', existing_audio_status=None)

        self.assertIsNone(match)

    def test_add_book_source_aware_click_does_not_fall_through_to_direct_provider_add(self):
        from lazylibrarian import gb, webServe

        google_other = self._google_result(bookid='GB-OTHER', highest_fuzz=100)

        def search(_term, source):
            if source == 'GoogleBooks':
                return [google_other]
            return []

        interface = webServe.WebInterface()
        with (
            mock.patch.object(webServe.WebInterface, 'check_permitted', return_value=None),
            mock.patch.object(webServe, 'search_for', side_effect=search),
            mock.patch.object(webServe, '_search_result_detail_for_source', return_value=None),
            mock.patch.object(gb.GoogleBooks, 'add_bookid_to_db', return_value=True) as direct_add,
            self.assertRaises(cherrypy.HTTPRedirect),
        ):
            interface.add_book(
                bookid='GB1', library='eBook', title='Rant',
                authorname='Chuck Palahniuk', source='GoogleBooks')

        direct_add.assert_not_called()
        db = DBConnection()
        try:
            count = db.match("SELECT count(*) AS counter FROM books WHERE BookID='GB1'")
            self.assertEqual(0, count['counter'])
        finally:
            db.close()

    def test_add_book_source_less_search_result_does_not_fall_through_to_direct_provider_add(self):
        from lazylibrarian import gr, webServe

        interface = webServe.WebInterface()
        with (
            mock.patch.object(webServe.WebInterface, 'check_permitted', return_value=None),
            mock.patch.object(webServe, 'search_for', return_value=[]),
            mock.patch.object(webServe, '_search_result_detail_for_source', return_value=None),
            mock.patch.object(gr.GoodReads, 'add_bookid_to_db', return_value=True) as direct_add,
            self.assertRaises(cherrypy.HTTPRedirect),
        ):
            interface.add_book(
                bookid='12345', library='eBook', title='Rant',
                authorname='Chuck Palahniuk')

        direct_add.assert_not_called()
        db = DBConnection()
        try:
            count = db.match("SELECT count(*) AS counter FROM books WHERE BookID='12345'")
            self.assertEqual(0, count['counter'])
        finally:
            db.close()

    def test_add_book_source_less_search_result_does_not_update_configured_id_collision(self):
        from lazylibrarian import gr, webServe

        db = DBConnection()
        try:
            self._insert_author(db, authorid='author-2', authorname='Different Author')
            self._insert_book(
                db, 'goodreads-collision', 'Rant', authorid='author-2',
                status='Skipped', gr_id='12345')
        finally:
            db.close()

        interface = webServe.WebInterface()
        with (
            mock.patch.object(webServe.WebInterface, 'check_permitted', return_value=None),
            mock.patch.object(webServe, 'search_for', return_value=[]),
            mock.patch.object(webServe, '_search_result_detail_for_source', return_value=None),
            mock.patch.object(gr.GoodReads, 'add_bookid_to_db', return_value=True) as direct_add,
            self.assertRaises(cherrypy.HTTPRedirect),
        ):
            interface.add_book(
                bookid='12345', library='eBook', title='Rant',
                authorid='author-1', authorname='Chuck Palahniuk')

        direct_add.assert_not_called()
        db = DBConnection()
        try:
            row = db.match("SELECT Status FROM books WHERE BookID='goodreads-collision'")
            self.assertEqual('Skipped', row['Status'])
        finally:
            db.close()

    def test_source_less_exact_fallback_does_not_update_author_mismatched_provider_row(self):
        from lazylibrarian import webServe

        db = DBConnection()
        try:
            self._insert_author(db, authorid='author-1', authorname='Chuck Palahniuk')
            self._insert_author(db, authorid='author-2', authorname='Different Author')
            self._insert_book(
                db, 'goodreads-collision', 'Rant', authorid='author-2',
                status='Skipped', gr_id='12345')
        finally:
            db.close()

        exact = self._google_result(bookid='12345', authorid='author-1', highest_fuzz=100)
        exact['source'] = 'GoodReads'

        def search(_term, source):
            if source == 'GoodReads':
                return [exact]
            return []

        with mock.patch.object(webServe, 'search_for', side_effect=search):
            match = webServe._add_search_result_book_to_db(
                '12345', 'Wanted', 'Skipped', title='Rant', authorname='Chuck Palahniuk',
                existing_ebook_status='Wanted', existing_audio_status=None)

        self.assertTrue(webServe._is_blocked_add_result(match))
        db = DBConnection()
        try:
            row = db.match("SELECT Status FROM books WHERE BookID='goodreads-collision'")
            self.assertEqual('Skipped', row['Status'])
        finally:
            db.close()

    def test_add_book_invalid_source_fails_closed(self):
        from lazylibrarian import gr, webServe

        interface = webServe.WebInterface()
        with (
            mock.patch.object(webServe.WebInterface, 'check_permitted', return_value=None),
            mock.patch.object(webServe, 'search_for') as search,
            mock.patch.object(gr.GoodReads, 'add_bookid_to_db', return_value=True) as direct_add,
            self.assertRaises(cherrypy.HTTPRedirect),
        ):
            interface.add_book(
                bookid='GB1', library='eBook', title='Rant',
                authorname='Chuck Palahniuk', source='BogusBooks')

        search.assert_not_called()
        direct_add.assert_not_called()
        db = DBConnection()
        try:
            count = db.match("SELECT count(*) AS counter FROM books WHERE BookID='GB1'")
            self.assertEqual(0, count['counter'])
        finally:
            db.close()

    def test_add_book_source_aware_exact_result_starts_search_on_canonical_row(self):
        from lazylibrarian import webServe

        db = DBConnection()
        try:
            self._insert_author(db)
            self._insert_book(db, 'canonical-book', 'Rant', status='Skipped', gb_id='GB1')
        finally:
            db.close()

        result = self._google_result()
        interface = webServe.WebInterface()
        with (
            mock.patch.object(webServe.WebInterface, 'check_permitted', return_value=None),
            mock.patch.object(webServe, 'search_for', side_effect=self._mock_search(result)),
            mock.patch.object(interface, 'start_book_search') as start_search,
            self.assertRaises(cherrypy.HTTPRedirect),
        ):
            interface.add_book(
                bookid='GB1', library='eBook', title='Rant',
                authorname='Chuck Palahniuk', source='GoogleBooks')

        start_search.assert_called_once_with(
            [{'bookid': 'canonical-book'}], library='eBook', force=True)

    def test_bulk_add_uses_source_payload_for_existing_canonical_row(self):
        from lazylibrarian import webServe

        db = DBConnection()
        try:
            self._insert_author(db)
            self._insert_book(db, 'canonical-book', 'Rant', status='Skipped', gb_id='GB1')
        finally:
            db.close()

        result = self._google_result()
        interface = webServe.WebInterface()
        with (
            mock.patch.object(webServe.WebInterface, 'check_permitted', return_value=None),
            mock.patch.object(webServe, 'search_for', side_effect=self._mock_search(result)),
        ):
            response = interface.mark_results_ajax(
                action='AddBook',
                **{'GB1': 'author-1|Chuck+Palahniuk|Rant|GoogleBooks'})

        self.assertEqual(1, response['passed'])
        self.assertEqual(0, response['failed'])
        db = DBConnection()
        try:
            row = db.match("SELECT Status FROM books WHERE BookID='canonical-book'")
            self.assertEqual('Wanted', row['Status'])
        finally:
            db.close()

    def test_bulk_add_source_aware_failure_does_not_fall_through_to_direct_provider_add(self):
        from lazylibrarian import gb, webServe

        google_other = self._google_result(bookid='GB-OTHER', highest_fuzz=100)

        def search(_term, source):
            if source == 'GoogleBooks':
                return [google_other]
            return []

        interface = webServe.WebInterface()
        with (
            mock.patch.object(webServe.WebInterface, 'check_permitted', return_value=None),
            mock.patch.object(webServe, 'search_for', side_effect=search),
            mock.patch.object(webServe, '_search_result_detail_for_source', return_value=None),
            mock.patch.object(gb.GoogleBooks, 'add_bookid_to_db', return_value=True) as direct_add,
        ):
            response = interface.mark_results_ajax(
                action='AddBook',
                **{'GB1': 'author-1|Chuck+Palahniuk|Rant|GoogleBooks'})

        self.assertEqual(0, response['passed'])
        self.assertEqual(1, response['failed'])
        direct_add.assert_not_called()

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
