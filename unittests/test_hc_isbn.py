#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test the HardCover isbn search query and the handling of rejected queries

import contextlib
import json
import os
from queue import Queue
from unittest import mock

from lazylibrarian import hc
from lazylibrarian.filesystem import DIRS
from lazylibrarian.provider_utils import get_hashed_filename
from unittests.unittesthelpers import LLTestCaseWithConfigandDIRS

HOBBIT = {'id': 2459845, 'title': 'The Hobbit, or There and Back Again', 'cached_image': {}, 'cached_tags': {},
          'contributions': [{'author': {'id': 656983, 'name': 'J.R.R. Tolkien'}}], 'editions': [],
          'book_series': []}
REJECTED = {'errors': [{'message': "field 'isbn_13' not found in type: 'books_bool_exp'",
                        'extensions': {'code': 'validation-failed'}}]}


def remove_quietly(path):
    with contextlib.suppress(FileNotFoundError):
        os.remove(path)


class HardCoverIsbnTest(LLTestCaseWithConfigandDIRS):

    def setUp(self):
        for p in (mock.patch.object(hc, 'get_current_userid', return_value=(None, None)),
                  mock.patch.object(hc, 'hc_api_sleep'),
                  mock.patch.object(hc.BLOCKHANDLER, 'is_blocked', return_value=False),
                  mock.patch.object(hc.database, 'DBConnection')):
            p.start()
            self.addCleanup(p.stop)
        self.hc = hc.HardCover()

    def test_isbn_queries_filter_on_editions(self):
        for template, field in ((self.hc.HC_ISBN13_BOOKS, 'isbn_13'), (self.hc.HC_ISBN10_BOOKS, 'isbn_10')):
            with self.subTest(field=field):
                self.assertIn(f'where: {{editions: {{{field}: {{_eq: "[isbn]"}}}}}}', template)

    def test_isbn_search_sends_editions_query(self):
        with mock.patch.object(self.hc, 'result_from_cache', return_value=({}, False)) as fetch:
            self.hc.find_results('9780547928227')
        query = fetch.call_args[0][0]
        self.assertIn('{editions: {isbn_13: {_eq: "9780547928227"}}}', query)
        with mock.patch.object(self.hc, 'result_from_cache', return_value=({}, False)) as fetch:
            self.hc.find_results('054792822X')
        self.assertIn('{editions: {isbn_10: {_eq: "054792822X"}}}', fetch.call_args[0][0])

    def test_isbn_search_returns_the_book(self):
        queue = Queue()
        with mock.patch.object(self.hc, 'result_from_cache', return_value=({'data': {'books': [HOBBIT]}}, False)):
            self.hc.find_results('9780547928227', queue=queue)
        self.assertEqual([r['bookid'] for r in queue.get_nowait()], ['2459845'])

    def cache_file(self, searchcmd):
        filename = f"{self.hc.graphql_url}/{str({'query': searchcmd})}"
        cache_file = get_hashed_filename(DIRS.get_cachedir('JSONCache'), filename)[0]
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
        self.addCleanup(remove_quietly, cache_file)
        return cache_file

    def post(self, body):
        response = mock.Mock(status_code=200)
        response.json.return_value = body
        return mock.patch.object(hc.requests, 'post', return_value=response)

    def test_rejected_query_is_logged_and_not_cached(self):
        searchcmd = self.hc.HC_ISBN13_BOOKS.replace('[isbn]', '9780000000001')
        cache_file = self.cache_file(searchcmd)
        with self.post(REJECTED), self.assertLogs(self.hc.logger, 'ERROR') as logs:
            res, in_cache = self.hc.result_from_cache(searchcmd)
        self.assertEqual(res, REJECTED)
        self.assertFalse(in_cache)
        self.assertIn('validation-failed', '\n'.join(logs.output))
        self.assertFalse(os.path.exists(cache_file))

    def test_good_answer_is_cached(self):
        searchcmd = self.hc.HC_ISBN13_BOOKS.replace('[isbn]', '9780000000002')
        body = {'data': {'books': [HOBBIT]}}
        cache_file = self.cache_file(searchcmd)
        with self.post(body):
            self.hc.result_from_cache(searchcmd)
        with open(cache_file) as f:
            self.assertEqual(json.load(f), body)
