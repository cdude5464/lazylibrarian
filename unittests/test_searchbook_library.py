#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test that search_book() only searches the format it was asked for.
#
#   Regression: the `library` argument ("eBook" / "AudioBook") was only used in log messages, so every
#   per-format caller (web UI, API type=, GoodReads/HardCover sync, wishlist) searched *both* formats
#   whenever a book was Wanted in both, doubling the queries sent to every provider.

from unittest import mock

from unittests.unittesthelpers import LLTestCase
from lazylibrarian import searchbook

BOOK_WANTED_IN_BOTH = {'BookID': '1', 'AuthorName': 'Jane Austen', 'BookName': 'Emma', 'BookSub': '',
                       'Status': 'Wanted', 'AudioStatus': 'Wanted'}


class FakeDB:
    """ Just enough of DBConnection for search_book() """

    def select(self, *_args, **_kwargs):
        return [BOOK_WANTED_IN_BOTH]

    def match(self, *_args, **_kwargs):
        return None

    def upsert(self, *_args, **_kwargs):
        pass

    def action(self, *_args, **_kwargs):
        pass

    def close(self):
        pass


class SearchBookLibraryTest(LLTestCase):

    def _libraries_searched(self, library):
        searched = []

        def fake_znab(book, searchtype):
            searched.append(book['library'])
            return [], 1

        config = searchbook.CONFIG
        with mock.patch.object(searchbook.database, 'DBConnection', return_value=FakeDB()), \
                mock.patch.object(config, 'total_active_providers', return_value=1), \
                mock.patch.object(config, 'use_nzb', return_value=1), \
                mock.patch.object(config, 'use_tor', return_value=0), \
                mock.patch.object(config, 'use_direct', return_value=0), \
                mock.patch.object(config, 'use_rss', return_value=0), \
                mock.patch.object(config, 'use_irc', return_value=0), \
                mock.patch.object(searchbook, 'iterate_over_znab_sites', side_effect=fake_znab):
            searchbook.search_book(books=[{'bookid': '1'}], library=library)
        return set(searched)

    def test_ebook_search_does_not_search_audiobook(self):
        self.assertSetEqual(self._libraries_searched('eBook'), {'eBook'})

    def test_audiobook_search_does_not_search_ebook(self):
        self.assertSetEqual(self._libraries_searched('AudioBook'), {'AudioBook'})

    def test_no_library_searches_both(self):
        self.assertSetEqual(self._libraries_searched(None), {'eBook', 'AudioBook'})

    def test_library_name_is_case_insensitive(self):
        self.assertSetEqual(self._libraries_searched('audiobook'), {'AudioBook'})
        self.assertSetEqual(self._libraries_searched('EBOOK'), {'eBook'})

    def test_unrecognised_library_still_searches_both(self):
        self.assertSetEqual(self._libraries_searched('item'), {'eBook', 'AudioBook'})
