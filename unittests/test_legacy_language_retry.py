import sqlite3
from unittest import TestCase
from unittest.mock import patch

from lazylibrarian import resultlist


class LegacyLanguageRetryTest(TestCase):
    reason = 'Embedded ebook metadata declares an unexpected language: en-US (expected Unknown)'

    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.db.execute('CREATE TABLE books (BookID, BookLang)')
        self.db.execute("INSERT INTO books VALUES ('42', 'Unknown')")
        self.closed = False
        test = self

        class ReadOnly:
            def match(self, query, params):
                return test.db.execute(query, params).fetchone()

            def close(self):
                test.closed = True

        self.patcher = patch.object(resultlist.database, 'DBConnection', ReadOnly)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.addCleanup(self.db.close)
        self.cfg = patch.object(resultlist, 'CONFIG', {'ANNA_SEARCH_LANG': 'ANY'})
        self.cfg.start()
        self.addCleanup(self.cfg.stop)

    def retry(self, reason=None, media='eBook', **row):
        return resultlist._failed_source_retryable({
            'Status': 'Failed', 'BookID': '42', 'NZBprov': 'annas',
            'DLResult': self.reason if reason is None else reason, **row,
        }, media)

    def test_unknown_language_bug_retries_after_current_unknown_semantics_fix(self):
        self.assertTrue(self.retry())
        self.assertTrue(self.closed)

    def test_current_explicit_language_must_agree_with_source(self):
        self.db.execute("UPDATE books SET BookLang='eng'")
        self.assertTrue(self.retry())
        self.db.execute("UPDATE books SET BookLang='es'")
        self.assertFalse(self.retry())

    def test_missing_language_uses_configured_search_default(self):
        self.db.execute('UPDATE books SET BookLang=NULL')
        with patch.object(resultlist, 'CONFIG', {'ANNA_SEARCH_LANG': 'es'}):
            self.assertFalse(self.retry())
        with patch.object(resultlist, 'CONFIG', {'ANNA_SEARCH_LANG': 'en'}):
            self.assertTrue(self.retry())

    def test_missing_current_row_or_book_id_fails_closed(self):
        self.assertFalse(self.retry(BookID=None))
        self.db.execute('DELETE FROM books')
        self.assertFalse(self.retry())
        self.assertTrue(self.closed)

    def test_exact_failure_only_and_ebook_media_only(self):
        for reason in (
            self.reason + '; source is wrong',
            self.reason.replace('Unknown', 'es'),
            self.reason.replace('en-US', ''),
            self.reason.replace('en-US', 'Unknown'),
            self.reason.replace('metadata declares', 'source claims'),
        ):
            with self.subTest(reason=reason):
                self.assertFalse(self.retry(reason))
        self.assertFalse(self.retry(media='AudioBook'))
        self.assertFalse(self.retry(Status='Processed'))

    def test_database_read_failure_fails_closed_and_closes(self):
        self.db.execute('DROP TABLE books')
        self.assertFalse(self.retry())
        self.assertTrue(self.closed)
