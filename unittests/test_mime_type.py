#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test mime_type() in common.py

import unittest

from lazylibrarian.common import mime_type


class MimeTypeTest(unittest.TestCase):

    def test_bare_extension(self):
        # opds passes '.' + format for books with more than one format
        self.assertEqual(mime_type('.epub'), 'application/epub+zip')
        self.assertEqual(mime_type('.pdf'), 'application/pdf')
        self.assertEqual(mime_type('.azw3'), 'application/x-mobi8-ebook')
        self.assertEqual(mime_type('.m4b'), 'audio/mp4')

    def test_file_names(self):
        self.assertEqual(mime_type('Author/Title.EPUB'), 'application/epub+zip')
        self.assertEqual(mime_type('/books/a.b/Title.mobi'), 'application/x-mobipocket-ebook')
        self.assertEqual(mime_type('notes.md'), 'text/markdown')
        self.assertEqual(mime_type('we_send.zip'), 'application/x-zip-compressed')

    def test_unknown(self):
        for name in ('README', 'file.xyz', '/books/a.b/Title', '', '.'):
            with self.subTest(name=name):
                self.assertEqual(mime_type(name), 'application/x-download')


if __name__ == '__main__':
    unittest.main()
