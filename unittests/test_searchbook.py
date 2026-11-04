#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test functions in searchbook.py

from unittest import mock

from lazylibrarian.config2 import CONFIG
from lazylibrarian.searchbook import _has_comic_genre
from unittests.unittesthelpers import LLTestCaseWithStartup


class HasComicGenreTest(LLTestCaseWithStartup):

    def _with_genres(self, genres_csv):
        return mock.patch.object(
            type(CONFIG), '__getitem__',
            lambda self_, key: genres_csv if key == 'COMIC_GENRES'
            else CONFIG.__class__.__getitem__(self_, key)
        )

    def test_graphic_novel_genre_matches(self):
        with self._with_genres('graphic novel, comics, manga'):
            self.assertTrue(_has_comic_genre({'genre': 'Graphic Novel'}))

    def test_comics_genre_matches(self):
        with self._with_genres('graphic novel, comics, manga'):
            self.assertTrue(_has_comic_genre({'genre': 'Comics'}))

    def test_manga_genre_matches(self):
        with self._with_genres('graphic novel, comics, manga'):
            self.assertTrue(_has_comic_genre({'genre': 'Manga'}))

    def test_mixed_genre_with_comic_matches(self):
        with self._with_genres('graphic novel, comics, manga'):
            self.assertTrue(_has_comic_genre({'genre': 'Fiction, Graphic Novel, Fantasy'}))

    def test_fiction_genre_does_not_match(self):
        with self._with_genres('graphic novel, comics, manga'):
            self.assertFalse(_has_comic_genre({'genre': 'Fiction'}))

    def test_empty_genre_does_not_match(self):
        with self._with_genres('graphic novel, comics, manga'):
            self.assertFalse(_has_comic_genre({'genre': ''}))

    def test_missing_genre_does_not_match(self):
        with self._with_genres('graphic novel, comics, manga'):
            self.assertFalse(_has_comic_genre({}))

    def test_empty_config_disables_matching(self):
        with self._with_genres(''):
            self.assertFalse(_has_comic_genre({'genre': 'Graphic Novel'}))

    def test_case_insensitive(self):
        with self._with_genres('GRAPHIC NOVEL'):
            self.assertTrue(_has_comic_genre({'genre': 'graphic novel'}))

    def test_partial_match_within_genre_token(self):
        with self._with_genres('comic'):
            self.assertTrue(_has_comic_genre({'genre': 'Sequential Art, Comic Book'}))

    def test_comic_does_not_match_economics(self):
        with self._with_genres('comic'):
            self.assertFalse(_has_comic_genre({'genre': 'Economics'}))

    def test_comic_does_not_match_macroeconomics(self):
        with self._with_genres('comic'):
            self.assertFalse(_has_comic_genre({'genre': 'Nonfiction, Macroeconomics'}))
