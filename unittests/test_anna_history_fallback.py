import sqlite3
from unittest import TestCase
from unittest.mock import patch
from lazylibrarian import searchbook


class AnnaHistoryFallbackTest(TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE books (BookID, Status);
            INSERT INTO books VALUES ('42','Wanted');
            CREATE TABLE wanted (BookID,NZBprov,NZBmode,AuxInfo,Status,NZBurl,NZBtitle,NZBsize,DLResult);
        """)
        connection = self.db

        class Reader:
            def match(self, query, args): return connection.execute(query, args).fetchone()
            def select(self, query, args): return connection.execute(query, args).fetchall()
            def close(self): pass

        self.reader = Reader
        self.book = {"bookid": "42", "library": "eBook"}
        self.config = {"EBOOK_TYPE": "epub,mobi", "ANNA_DLPRIORITY": 5}

    def add(self, reason="retryable", status="Failed", book="42", identifier="a"*32):
        self.db.execute("INSERT INTO wanted VALUES (?,'annas','direct','eBook',?,?,?,2.5,?)",
                        (book, status, identifier, "Author Book.epub", reason))

    def candidates(self, book=None):
        with patch.object(searchbook.database, "DBConnection", self.reader),                 patch.object(searchbook, "CONFIG", self.config),                 patch.object(searchbook, "_failed_source_retryable",
                             side_effect=lambda row, media: row["DLResult"] == "retryable"):
            return searchbook.retryable_anna_history_candidates(book or self.book)

    def test_known_retryable_source_does_not_require_network_search(self):
        self.add()
        results = self.candidates()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["tor_url"], "a"*32)
        self.assertEqual(results[0]["tor_size"], 2621440)

    def test_manual_block_or_wrong_content_cannot_be_revived(self):
        self.add()
        self.add("blocked by user")
        self.assertEqual(self.candidates(), [])

    def test_newer_processed_source_does_not_revive_old_failure(self):
        self.add()
        self.add(status="Processed")
        self.assertEqual(self.candidates(), [])

    def test_skipped_have_and_other_books_are_not_requeued(self):
        self.add()
        self.assertEqual(self.candidates({"bookid":"other","library":"eBook"}), [])
        for status in ("Skipped","Ignored","Have","Snatched"):
            self.db.execute("UPDATE books SET Status=?", (status,))
            self.assertEqual(self.candidates(), [])

    def test_invalid_source_identity_and_media_are_refused(self):
        self.add(identifier="https://unverified.invalid/file")
        self.assertEqual(self.candidates(), [])
        self.assertEqual(self.candidates({"bookid":"42","library":"AudioBook"}), [])

    def test_cross_book_mixed_case_manual_block_is_preserved(self):
        self.add()
        self.add("blocked by user", book="other", identifier="A"*32)
        self.assertEqual(self.candidates(), [])
