"""Explicit volume mismatches must not be hidden by high fuzzy title scores."""
from unittest import TestCase
from unittest.mock import Mock, patch

from lazylibrarian import resultlist
from lazylibrarian.ebook_identity import ebook_volume_conflict
from lazylibrarian.postprocess import _ebook_metadata_conflict


class EbookVolumeIdentityTest(TestCase):
    def test_wrong_volume_of_same_graphic_novel_is_a_conflict(self):
        expected = 'Dungeon Crawler Carl, Vol. 3 (Graphic Novel)'
        observed = 'Dungeon Crawler Carl, Vol. 1 (Graphic Novel)'
        self.assertTrue(ebook_volume_conflict(expected, observed))
        conflict, reason = _ebook_metadata_conflict('Matt Dinniman', expected, observed, 'Matt Dinniman')
        self.assertTrue(conflict)
        self.assertIn('different volume', reason)

    def test_explicit_conflict_does_not_require_embedded_creator(self):
        self.assertTrue(_ebook_metadata_conflict('Author', 'Title Vol. 3', 'Title Vol. 1', '')[0])

    def test_volume_spelling_and_roman_notation_are_equivalent(self):
        for expected, observed in [('Title Vol. 3', 'Title Volume III'),
                                   ('Title vol 1', 'Title volume I'),
                                   ('Title Volume 1.5', 'Title Vol. 1.50')]:
            with self.subTest(expected=expected, observed=observed):
                self.assertFalse(ebook_volume_conflict(expected, observed))
        self.assertTrue(ebook_volume_conflict('Title volume III', 'Title vol. IV'))

    def test_missing_or_non_volume_numbers_are_not_inferred(self):
        for expected, observed in [('Title Vol. 3', 'Title'),
                                   ('Series (Collection, #3)', 'Series'),
                                   ('Building 903', 'Building 904'),
                                   ('Title 10th Anniversary', 'Title'),
                                   ('Volume of Water', 'Volume of Air'),
                                   ('Title Vol. invalid', 'Title Vol. 1')]:
            with self.subTest(expected=expected, observed=observed):
                self.assertFalse(ebook_volume_conflict(expected, observed))

    def test_extra_explicit_volume_is_ambiguous(self):
        self.assertTrue(ebook_volume_conflict('Title Vol 3', 'Title Vol 1 and Vol 3'))
        self.assertFalse(ebook_volume_conflict('Title Vol 1 and Vol 3', 'Title Vol 3 and Vol 1'))

    def test_search_rejects_wrong_volume_then_selects_correct_lower_priority_candidate(self):
        class Config(dict):
            def __missing__(self, key): return ''
            def get_int(self, key): return int(self.get(key, 0))
            def get_bool(self, key): return bool(self.get(key, False))
        config = Config(MATCH_RATIO=85, EBOOK_TYPE='epub,mobi,pdf', AUDIOBOOK_TYPE='m4b,mp3')
        book = {'library': 'eBook', 'bookid': '42', 'authorName': 'Matt Dinniman',
                'bookName': 'Dungeon Crawler Carl, Vol. 3 (Graphic Novel)', 'bookSub': ''}
        def candidate(volume, priority):
            return {'tor_title': f'Matt Dinniman Dungeon Crawler Carl, Vol. {volume} (Graphic Novel).epub',
                    'tor_prov': 'annas', 'tor_type': 'direct', 'tor_url': str(volume) * 32,
                    'tor_size': 1048576, 'priority': priority}
        db = Mock(); db.match.return_value = None; db.select.return_value = []
        with patch.object(resultlist, 'CONFIG', config), patch.object(resultlist.database, 'DBConnection', return_value=db):
            self.assertIsNone(resultlist.find_best_result([candidate(1, 100)], book, 'book', 'direct'))
            match = resultlist.find_best_result([candidate(1, 100), candidate(3, 1)], book, 'book', 'direct')
        self.assertIsNotNone(match)
        self.assertEqual(match[2]['NZBurl'], '3' * 32)
