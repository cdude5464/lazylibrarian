#  This file is part of Lazylibrarian.
#
#  Lazylibrarian is free software, you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Lazylibrarian is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Lazylibrarian.  If not, see <http://www.gnu.org/licenses/>.

# Purpose:
#   Test normalize_library_param() in api.py

import unittest

from lazylibrarian.api import normalize_library_param


class NormalizeLibraryParamTest(unittest.TestCase):
    """_importalternate/_importbook used to pass their raw 'library' kwarg straight
    through with no validation, so any caller using "AudioBook" (a natural value --
    it's the display string used elsewhere in the codebase) instead of the
    undocumented internal literal "Audio" would silently fail deeper in the import
    pipeline. normalize_library_param() closes that gap at the API boundary."""

    def test_canonical_values_pass_through_unchanged(self):
        self.assertEqual(normalize_library_param("eBook"), "eBook")
        self.assertEqual(normalize_library_param("Audio"), "Audio")

    def test_audiobook_variants_normalized_to_audio(self):
        for variant in ("AudioBook", "audiobook", "Audio Book", "audio_book", "audio-book"):
            with self.subTest(variant=variant):
                self.assertEqual(normalize_library_param(variant), "Audio")

    def test_ebook_variants_normalized_to_ebook(self):
        for variant in ("ebook", "e Book", "e-book", "e_book"):
            with self.subTest(variant=variant):
                self.assertEqual(normalize_library_param(variant), "eBook")

    def test_unrecognized_value_passed_through_unchanged(self):
        # Not this function's job to error -- callers (process_book_from_dir,
        # process_alternate) already have their own handling for a value they
        # don't recognize; we just shouldn't mangle it into something else.
        self.assertEqual(normalize_library_param("NotARealBookType"), "NotARealBookType")

    def test_magazine_and_comic_passed_through_unchanged(self):
        # Recognized by BookType, but not eBook/Audio -- normalize_library_param
        # only ever maps to "Audio"/"eBook", so anything else (including other
        # valid BookType values) is left as-is rather than incorrectly coerced.
        self.assertEqual(normalize_library_param("magazine"), "magazine")
        self.assertEqual(normalize_library_param("comic"), "comic")


if __name__ == "__main__":
    unittest.main()
