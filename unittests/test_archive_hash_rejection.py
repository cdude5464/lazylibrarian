import sqlite3
from unittest import TestCase
from unittest.mock import patch

from lazylibrarian import downloadmethods


class ArchiveHashRejectionTest(TestCase):
    def test_only_rejected_archive_for_same_book_and_hash_is_blocked(self):
        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE wanted (BookID, DownloadID, AuxInfo, Source, Status, DLResult)")
        db.execute("INSERT INTO wanted VALUES (?, ?, ?, ?, ?, ?)", (
            "42", "A" * 40, "eBook", "QBITTORRENT", "Failed",
            "Rejected archive payload before LazyLibrarian import: corrupt",
        ))

        class ReadOnly:
            def match(self, query, params):
                return db.execute(query, params).fetchone()

            def close(self):
                pass

        try:
            with patch.object(downloadmethods.database, "DBConnection", ReadOnly):
                self.assertTrue(downloadmethods.previously_rejected_archive("42", "a" * 40))
                self.assertFalse(downloadmethods.previously_rejected_archive("43", "a" * 40))
                self.assertFalse(downloadmethods.previously_rejected_archive("42", "b" * 40))
                db.execute("UPDATE wanted SET DLResult='temporary network error'")
                self.assertFalse(downloadmethods.previously_rejected_archive("42", "a" * 40))
        finally:
            db.close()


    def test_audio_only_detection_does_not_guess_about_archives_or_magnets(self):
        def metadata(*names):
            return downloadmethods.bencode({"info": {"files": [{"path": [n]} for n in names]}})

        self.assertTrue(downloadmethods.torrent_contains_only_audio(metadata("book.MP3", "cover.jpg")))
        self.assertFalse(downloadmethods.torrent_contains_only_audio(metadata("book.m4b", "book.epub")))
        self.assertFalse(downloadmethods.torrent_contains_only_audio(metadata("book.m4b", "payload.rar")))
        self.assertFalse(downloadmethods.torrent_contains_only_audio(b""))
        self.assertFalse(downloadmethods.torrent_contains_only_audio(b"invalid"))
        self.assertFalse(downloadmethods.torrent_contains_only_audio(downloadmethods.bencode({"info": []})))
