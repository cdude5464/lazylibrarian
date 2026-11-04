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
#   Test the library-parameter normalization in manual_import.process_book_from_dir()

import shutil
import tempfile
from unittest import mock

from lazylibrarian.database import DBConnection
from lazylibrarian.manual_import import process_book_from_dir
from unittests.unittesthelpers import LLTestCaseWithStartup


class ProcessBookFromDirLibraryParamTest(LLTestCaseWithStartup):
    """process_book_from_dir() used to reject any library value other than the exact
    literals "eBook"/"Audio", even though "AudioBook" (the display string used
    elsewhere in the codebase) is a very natural value for a caller to pass, and
    get_directory() already treats it as equivalent to "Audio". This broke
    process_alternate()'s last-resort fallback for any caller using that spelling.
    """

    BOOK_ID = "test-book-from-dir-param"
    AUTHOR_ID = "test-book-from-dir-author"

    def setUp(self):
        super().setUp()
        self.source_dir = tempfile.mkdtemp()
        db = DBConnection()
        try:
            db.action(
                "INSERT OR REPLACE INTO authors (AuthorID, AuthorName) VALUES (?, ?)",
                (self.AUTHOR_ID, "Test Author"),
            )
            db.action(
                "INSERT OR REPLACE INTO books (BookID, AuthorID, BookName, Status, AudioStatus) "
                "VALUES (?, ?, ?, ?, ?)",
                (self.BOOK_ID, self.AUTHOR_ID, "Test Book", "Skipped", "Skipped"),
            )
        finally:
            db.close()

    def tearDown(self):
        shutil.rmtree(self.source_dir, ignore_errors=True)
        db = DBConnection()
        try:
            db.action("DELETE FROM books WHERE BookID=?", (self.BOOK_ID,))
            db.action("DELETE FROM authors WHERE AuthorID=?", (self.AUTHOR_ID,))
        finally:
            db.close()
        super().tearDown()

    def _call_and_capture_library(self, library):
        """Call process_book_from_dir with a mocked process_book() so we isolate
        the normalization/guard logic from the rest of the import pipeline, and
        return the library value process_book() was actually called with (or None
        if it was never reached)."""
        with mock.patch(
            "lazylibrarian.manual_import.process_book", return_value=True
        ) as mock_process_book:
            result = process_book_from_dir(
                source_dir=self.source_dir, library=library, bookid=self.BOOK_ID
            )
            if mock_process_book.called:
                _, kwargs = mock_process_book.call_args
                return result, kwargs.get("library")
            return result, None

    def test_canonical_audio_accepted(self):
        result, called_with = self._call_and_capture_library("Audio")
        self.assertTrue(result)
        self.assertEqual(called_with, "Audio")

    def test_canonical_ebook_accepted(self):
        result, called_with = self._call_and_capture_library("eBook")
        self.assertTrue(result)
        self.assertEqual(called_with, "eBook")

    def test_audiobook_spelling_normalized_to_audio(self):
        """Regression test: this is the exact value that used to fail with
        "book_from_dir not implemented for AudioBook"."""
        result, called_with = self._call_and_capture_library("AudioBook")
        self.assertTrue(result)
        self.assertEqual(called_with, "Audio")

    def test_audiobook_spelling_variants_normalized_to_audio(self):
        for variant in ("audiobook", "Audio Book", "audio_book", "audio-book"):
            with self.subTest(variant=variant):
                result, called_with = self._call_and_capture_library(variant)
                self.assertTrue(result)
                self.assertEqual(called_with, "Audio")

    def test_unrecognized_library_rejected(self):
        result, called_with = self._call_and_capture_library("NotARealBookType")
        self.assertFalse(result)
        self.assertIsNone(called_with)

    def test_magazine_and_comic_still_rejected(self):
        # BookType.from_string() recognizes these, but process_book_from_dir only
        # ever handled ebook/audiobook -- confirm the normalization doesn't
        # accidentally widen what this function accepts.
        for library in ("magazine", "comic"):
            with self.subTest(library=library):
                result, called_with = self._call_and_capture_library(library)
                self.assertFalse(result)
                self.assertIsNone(called_with)
