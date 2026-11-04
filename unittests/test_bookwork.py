#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test the language identifier to make sure it returns sensible results 
#   This test uses examples from GoodReads Agatha Christie books

import os
import unittest
from unittest.mock import patch

from unittests.unittesthelpers import LLTestCase
from lazylibrarian.bookwork import language_from_words, is_set_or_part
from lazylibrarian.formatter import check_year
from lazylibrarian import TIMERS

TESTS = [
    ("Why Didn't they ask Evans?", 'en'),
    ("Cinque romanzi, 1931-1934", 'it'),
    ('le français', 'fr'),
    ("Una broma extraña", 'es'),
    ("Dubbele Detective Het geheim van de blauwe trein Bewijs met de handschoen", 'nl'),
    ("Gutenacht Geschichten Kriminalgeschichten für eine Gänsehaut vor dem Einschlafen", 'de'),
    ("আগাথা ক্রিস্টি সমগ্র ১৬", 'bn'),
    ("", 'None')
]


class LanguageTest(LLTestCase):
    def test_correct_detection(self):
        TIMERS['LAST_GLANG'] = 0
        for title in TESTS:
            lang, confidence = language_from_words(title[0])
            self.assertEqual(lang, title[1])

class TestIsSetOrPart(unittest.TestCase):

    def test_empty_or_none_title(self):
        """Should return False and empty message if title is missing or empty."""
        self.assertEqual(is_set_or_part(""), (False, ''))
        self.assertEqual(is_set_or_part(None), (False, ''))

    @patch('lazylibrarian.formatter.check_year')
    def test_dash_range_valid_year(self, mock_check_year):
        """Should accept titles where the hyphenated numbers look like a valid year."""
        mock_check_year.return_value = True
        
        rejected, msg = is_set_or_part("History 1990-2000")
        
        self.assertFalse(rejected)
        self.assertEqual(msg, '')


    @patch('lazylibrarian.formatter.check_year')
    def test_dash_range_invalid_year(self, mock_check_year):
        """Should reject titles with random hyphenated ranges (e.g. part numbers)."""
        mock_check_year.return_value = False
        rejected, msg = is_set_or_part("Issues 01-05")
        self.assertTrue(rejected)
        self.assertEqual(msg, 'Set or Part 01-05')

    def test_x_of_y_pattern(self):
        """Should reject titles explicitly stating volume/part counts (e.g., 1 of 3)."""
        rejected, msg = is_set_or_part("Book 1 of 3")
        self.assertTrue(rejected)
        self.assertEqual(msg, 'Set or Part')

    def test_fraction_pattern(self):
        """Should reject simple slash fractions (e.g., 2/4)."""
        rejected, msg = is_set_or_part("Episode 2/4")
        self.assertTrue(rejected)
        self.assertEqual(msg, 'Set or Part')

    def test_full_date_slash_pattern(self):
        """Should bypass slash fraction logic if it is a complete 3-part date."""
        rejected, msg = is_set_or_part("Event 12/25/2026")
        self.assertFalse(rejected)
        self.assertEqual(msg, '')

    def test_word_slash_word_pattern(self):
        """Should reject strings separated by slashes representing compilation pieces."""
        rejected, msg = is_set_or_part("Part A / Part B")
        self.assertTrue(rejected)
        self.assertEqual(msg, 'Set or Part')

    def test_safe_title(self):
        """Should completely clear vanilla titles without markings."""
        rejected, msg = is_set_or_part("The Great Gatsby")
        self.assertFalse(rejected)
        self.assertEqual(msg, '')


if __name__ == '__main__':
    unittest.main()
