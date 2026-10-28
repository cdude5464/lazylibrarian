#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test that search_book() tries the titles of other translations when the book's own title
#   finds nothing, eg the Czech translation of a Slovak book from Databáze knih

from unittest import mock

from lazylibrarian import searchbook
from unittests.unittesthelpers import LLTestCase

SLOVAK_BOOK = {'BookID': '1', 'AuthorName': 'Edgar Wallace', 'BookName': 'Anjel hrôzy', 'BookSub': '',
               'Status': 'Wanted', 'AudioStatus': 'Skipped', 'OtherTitles': 'Anděl hrůzy'}


class FakeDB:
    """ Just enough of DBConnection for search_book() """

    def __init__(self, book):
        self.book = book

    def select(self, *_args, **_kwargs):
        return [self.book]

    def match(self, *_args, **_kwargs):
        return None

    def upsert(self, *_args, **_kwargs):
        pass

    def action(self, *_args, **_kwargs):
        pass

    def close(self):
        pass


class SearchBookOtherTitlesTest(LLTestCase):

    def _search(self, book, found_title=''):
        """ Search for book with only nzb providers, which find found_title in a book search.
            Return the (searchtype, title) searches and the book download_result got, or None """
        searched = []

        def fake_znab(book, searchtype):
            searched.append((searchtype, book['bookName']))
            return (['result'] if searchtype == 'book' and book['bookName'] == found_title else []), 1

        def fake_best(resultlist, book, searchtype, mode):
            return (100, {'NZBprov': 'test', 'NZBtitle': book['bookName']}, None, 0) if resultlist else None

        config = searchbook.CONFIG
        with mock.patch.object(searchbook.database, 'DBConnection', return_value=FakeDB(book)), \
                mock.patch.object(config, 'total_active_providers', return_value=1), \
                mock.patch.object(config, 'use_nzb', return_value=1), \
                mock.patch.object(config, 'use_tor', return_value=0), \
                mock.patch.object(config, 'use_direct', return_value=0), \
                mock.patch.object(config, 'use_rss', return_value=0), \
                mock.patch.object(config, 'use_irc', return_value=0), \
                mock.patch.object(searchbook, 'iterate_over_znab_sites', side_effect=fake_znab), \
                mock.patch.object(searchbook, 'find_best_result', side_effect=fake_best), \
                mock.patch.object(searchbook, 'download_result', return_value=2) as download:
            searchbook.search_book(books=[{'bookid': '1'}], library='eBook')
        return searched, download.call_args[0][1] if download.called else None

    def test_other_title_tried_last(self):
        searched, downloaded = self._search(SLOVAK_BOOK)
        self.assertIn(('book', 'Anjel hrôzy'), searched)
        self.assertEqual(searched[-1], ('book', 'Anděl hrůzy'))
        self.assertIsNone(downloaded)

    def test_other_title_downloaded_as_the_book(self):
        searched, downloaded = self._search(SLOVAK_BOOK, found_title='Anděl hrůzy')
        self.assertEqual(searched[-1], ('book', 'Anděl hrůzy'))
        # the match is still this book, under its own title
        self.assertEqual(downloaded['bookid'], '1')
        self.assertEqual(downloaded['bookName'], 'Anjel hrôzy')

    def test_own_title_found_first(self):
        searched, downloaded = self._search(SLOVAK_BOOK, found_title='Anjel hrôzy')
        self.assertNotIn(('book', 'Anděl hrůzy'), searched)
        self.assertEqual(downloaded['bookName'], 'Anjel hrôzy')

    def test_no_other_titles(self):
        book = dict(SLOVAK_BOOK, OtherTitles=None)
        searched, _ = self._search(book)
        self.assertNotIn(('book', 'Anděl hrůzy'), searched)
        # a book read without the column, eg by older code
        book = {key: value for key, value in SLOVAK_BOOK.items() if key != 'OtherTitles'}
        searched, _ = self._search(book)
        self.assertNotIn(('book', 'Anděl hrůzy'), searched)
