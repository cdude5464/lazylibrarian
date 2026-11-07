"""Subtitle query fallback must retain full source identity and rejection policy."""
import sqlite3
from unittest import TestCase, mock

from lazylibrarian import providers, resultlist, searchbook
from lazylibrarian.subtitle_search import exact_primary_result, primary_title
from unittests.test_searchbook_other_titles import FakeDB
from unittests.unittesthelpers import LLTestCase


BOOK = {'bookid': '247150129', 'authorName': 'Adam Grant',
        'bookName': 'Vibe - The Secrets of Strong Connections in a Lonely World',
        'bookSub': 'The Secrets of Strong Connections in a Lonely World', 'library': 'eBook'}


class Config(dict):
    def __missing__(self, key): return ''
    def get_int(self, key): return int(self.get(key, 0))
    def get_bool(self, key): return bool(self.get(key, False))


class SubtitleIdentityTest(TestCase):
    def test_primary_requires_exact_structured_suffix_and_separator(self):
        self.assertEqual('Vibe', primary_title(BOOK))
        for separator in (': ', ' — ', ' – ', ' - '):
            self.assertEqual('Vibe', primary_title({**BOOK, 'bookName': 'Vibe' + separator + BOOK['bookSub']}))
        for changes in ({'bookSub': ''}, {'bookSub': 'Strong Connections'},
                        {'bookName': 'Vibe-' + BOOK['bookSub']},
                        {'bookName': 'Vibe ' + BOOK['bookSub']},
                        {'bookName': BOOK['bookName'] + ' extra'},
                        {'bookName': 'Vibe - Coding', 'bookSub': ''}):
            with self.subTest(changes=changes):
                self.assertEqual('', primary_title({**BOOK, **changes}))

    def test_identity_bearing_subtitles_are_never_omitted_or_score_lifted(self):
        for subtitle in ('Vol. 3', 'Book 2', 'Part II', '#3', 'III', 'French Edition',
                         'German', 'Abridged', 'Graphic Novel', 'Illustrated Edition',
                         'An Adaptation', 'An Omnibus', 'A Companion', 'Revised', 'Expanded',
                         'Updated', 'Anniversary', 'Definitive', 'Deluxe', 'Annotated', 'iv', 'epub', 'fr-CA'):
            with self.subTest(subtitle=subtitle):
                book = {**BOOK, 'bookName': 'Vibe: ' + subtitle, 'bookSub': subtitle}
                self.assertEqual('', primary_title(book))
                self.assertFalse(exact_primary_result(book, 'Grant, Adam Vibe.epub', ['epub']))
                match = self.match('Grant, Adam Vibe.epub', book=book)
                # Existing fuzzy policy is unchanged: compare against the
                # normal matcher with this shortcut explicitly disabled.
                with mock.patch.object(resultlist, 'exact_primary_result', return_value=False):
                    baseline = self.match('Grant, Adam Vibe.epub', book=book)
                self.assertEqual(match[0] if match else None, baseline[0] if baseline else None)

    def test_exact_author_and_primary_with_only_format_suffix(self):
        for title in ('Adam Grant Vibe.epub', 'Grant, Adam Vibe.epub', 'Vibe - Adam Grant [M4B]'):
            self.assertTrue(exact_primary_result(BOOK, title, ['epub', 'm4b']))
        for title in ('Vibe.epub', 'Other Author Vibe.epub', 'Adam Grantson Vibe.epub',
                      'Adam Grant Vibe Coding.epub', 'Adam Grant Originals.epub',
                      'Adam Grant Vibe abridged.m4b', 'Adam Grant Vibe companion.epub',
                      'Grant Adam Vibe.epub'):
            with self.subTest(title=title):
                self.assertFalse(exact_primary_result(BOOK, title, ['epub', 'm4b']))

    def match(self, title, library='eBook', language='en', db=None, book=None):
        config = Config(MATCH_RATIO=85, EBOOK_TYPE='epub,mobi,pdf', AUDIOBOOK_TYPE='m4b,mp3',
                        REJECT_WORDS='abridged', REJECT_AUDIO='abridged', IMP_PREFLANG='en')
        if db is None:
            db = mock.Mock(); db.match.return_value = None; db.select.return_value = []
        result = {'tor_title': title, 'tor_prov': 'annas', 'tor_type': 'direct',
                  'tor_url': 'a' * 32, 'tor_size': 1048576, 'priority': 1, 'tor_lang': language}
        with mock.patch.object(resultlist, 'CONFIG', config), mock.patch.object(
                resultlist.database, 'DBConnection', return_value=db):
            return resultlist.find_best_result([result], {**(book or BOOK), 'library': library},
                                              'book' if library == 'eBook' else 'audio', 'direct')

    def test_exact_short_result_reaches_threshold_for_ebook_and_audio(self):
        for library, ext in [('eBook', 'epub'), ('AudioBook', 'm4b')]:
            with self.subTest(library=library):
                match = self.match('Adam Grant Vibe.' + ext, library)
                self.assertGreaterEqual(match[0], 85)
                self.assertEqual(BOOK['bookid'], match[1]['BookID'])

    def test_short_identity_does_not_bypass_author_work_format_or_language(self):
        for library, title, language in [
            ('eBook', 'Adam Grant Vibe Coding.epub', 'en'),
            ('eBook', 'Adam Grant Originals.epub', 'en'),
            ('eBook', 'Other Author Vibe.epub', 'en'),
            ('eBook', 'Vibe.epub', 'en'),
            ('eBook', 'Adam Grant Vibe.m4b', 'en'),
            ('AudioBook', 'Adam Grant Vibe.epub', 'en'),
            ('AudioBook', 'Adam Grant Vibe abridged.m4b', 'en'),
            ('eBook', 'Adam Grant Vibe.epub', 'fr'),
            ('AudioBook', 'Adam Grant Vibe.m4b', 'fr'),
        ]:
            with self.subTest(library=library, title=title, language=language):
                match = self.match(title, library, language)
                self.assertTrue(match is None or match[0] < 85)

    def test_manual_or_content_md5_block_cannot_be_overridden_by_exact_identity(self):
        for reason in ('Blocked by user', 'Embedded ebook metadata declares a different volume'):
            with self.subTest(reason=reason):
                connection = sqlite3.connect(':memory:'); connection.row_factory = sqlite3.Row
                self.addCleanup(connection.close)
                connection.execute('CREATE TABLE wanted (NZBurl,Status,NZBprov,DLResult)')
                connection.execute('INSERT INTO wanted VALUES (?,?,?,?)', ('A' * 32, 'Failed', 'annas', reason))
                db = mock.Mock(); db.match.return_value = None
                db.select.side_effect = lambda query, args: connection.execute(query, args).fetchall()
                self.assertIsNone(self.match('Adam Grant Vibe.epub', db=db))

    def test_graphic_volume_identity_still_uses_original_full_title(self):
        book = {**BOOK, 'authorName': 'Matt Dinniman',
                'bookName': 'Dungeon Crawler Carl Vol. 3 (Graphic Novel) - An Adaptation',
                'bookSub': 'An Adaptation'}
        for title in ('Matt Dinniman Dungeon Crawler Carl.epub',
                      'Matt Dinniman Dungeon Crawler Carl Vol. 3.epub',
                      'Matt Dinniman Dungeon Crawler Carl Vol. 1 (Graphic Novel).epub'):
            self.assertIsNone(self.match(title, book=book))
        self.assertGreaterEqual(self.match('Matt Dinniman Dungeon Crawler Carl Vol. 3 (Graphic Novel).epub', book=book)[0], 85)
        subtitle_identity = {**book, 'bookName': 'Dungeon Crawler Carl: Vol. 3 (Graphic Novel)',
                             'bookSub': 'Vol. 3 (Graphic Novel)'}
        self.assertIsNone(self.match('Matt Dinniman Dungeon Crawler Carl.epub', book=subtitle_identity))


class SubtitleQueryTest(LLTestCase):
    def run_search(self, library='eBook', full_match=False, accepted_prefix='short'):
        row = {'BookID': BOOK['bookid'], 'AuthorName': BOOK['authorName'], 'BookName': BOOK['bookName'],
               'BookSub': BOOK['bookSub'], 'Status': 'Wanted', 'AudioStatus': 'Wanted', 'OtherTitles': ''}
        queries = []; matched_contexts = []
        def provider(book, searchtype):
            author, title = providers.get_searchterm(book, searchtype)
            queries.append((searchtype, author, title))
            return (['candidate'] if full_match or searchtype.startswith(accepted_prefix) else []), 1
        def match(results, book, searchtype, mode):
            matched_contexts.append(dict(book))
            return [100, {'NZBprov': 'test', 'NZBtitle': 'Adam Grant Vibe'}, None, 0] if results else None
        config = searchbook.CONFIG
        with (mock.patch.object(searchbook.database, 'DBConnection', return_value=FakeDB(row)),
              mock.patch.object(config, 'total_active_providers', return_value=1),
              mock.patch.object(config, 'use_nzb', return_value=1),
              mock.patch.object(config, 'use_tor', return_value=0),
              mock.patch.object(config, 'use_direct', return_value=0),
              mock.patch.object(config, 'use_rss', return_value=0),
              mock.patch.object(config, 'use_irc', return_value=0),
              mock.patch.object(searchbook, 'iterate_over_znab_sites', side_effect=provider),
              mock.patch.object(searchbook, 'find_best_result', side_effect=match),
              mock.patch.object(searchbook, 'download_result', return_value=2)):
            searchbook.search_book(books=[{'bookid': BOOK['bookid']}], library=library)
        return queries, matched_contexts

    def test_short_query_preserves_existing_author_normalization(self):
        prefixed = {**BOOK, 'bookName': 'Adam Grant ' + BOOK['bookName']}
        self.assertEqual(('Adam Grant', 'Vibe'), providers.get_searchterm(prefixed, 'shortbook'))
        named = {**BOOK, 'authorName': 'Spike Milligan',
                 'bookName': 'Spike Milligan: Man of Letters', 'bookSub': 'Man of Letters'}
        self.assertEqual('', primary_title(named))
        self.assertEqual(('Spike Milligan', 'Man of Letters'), providers.get_searchterm(named, 'shortbook'))

    def test_bounded_primary_query_preserves_original_match_context_for_both_media(self):
        for library, kind in [('eBook', 'book'), ('AudioBook', 'audio')]:
            with self.subTest(library=library):
                queries, contexts = self.run_search(library)
                self.assertEqual([(kind, 'Adam Grant', BOOK['bookName']),
                                  ('short' + kind, 'Adam Grant', 'Vibe')], queries)
                self.assertTrue(contexts)
                for context in contexts:
                    self.assertEqual(BOOK['bookName'], context['bookName'])
                    self.assertEqual(BOOK['bookSub'], context['bookSub'])

    def test_primary_general_nzb_fallback_remains_bounded(self):
        queries, contexts = self.run_search(accepted_prefix='shortgeneral')
        primary_queries = [query for query in queries if query[2] == 'Vibe']
        self.assertEqual([('shortbook', 'Adam Grant', 'Vibe'),
                          ('shortgeneralbook', 'Adam Grant', 'Vibe')], primary_queries)
        for context in contexts:
            self.assertEqual(BOOK['bookName'], context['bookName'])
            self.assertEqual(BOOK['bookSub'], context['bookSub'])

    def test_primary_query_not_run_after_accepted_full_result(self):
        queries, _ = self.run_search(full_match=True)
        self.assertEqual(1, len(queries))
