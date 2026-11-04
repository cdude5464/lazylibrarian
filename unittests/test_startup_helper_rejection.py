import os
import sqlite3
from unittest import TestCase
from unittest.mock import Mock, patch

from lazylibrarian import dbupgrade
from lazylibrarian.box_helper_handoff import BOX_HELPER_HANDOFF_PROTOCOL


class ReadOnlyDatabase:
    def __init__(self, conn):
        self.conn = conn

    def match(self, query, params):
        return self.conn.execute(query, params).fetchone()

    def select(self, query, params):
        return self.conn.execute(query, params).fetchall()

    def action(self, query, params):
        return self.conn.execute(query, params)


class StartupHelperRejectionTest(TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("CREATE TABLE wanted (BookID,AuxInfo,Source,Status,DownloadID,DLResult,Completed)")
        self.conn.execute("CREATE TABLE books (BookID,AudioStatus,Status DEFAULT 'Have')")
        self.db = ReadOnlyDatabase(self.conn)
        self.env = patch.dict(os.environ, {
            "BOX_LL_HANDOFF_PROTOCOL": BOX_HELPER_HANDOFF_PROTOCOL,
            "BOX_LL_QBIT_LIFECYCLE_OWNER": "helper",
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.conn.close()

    def add(self, **kwargs):
        values = dict(BookID="42", AuxInfo="AudioBook", Source="QBITTORRENT",
                      Status="Failed", DownloadID="a" * 40,
                      DLResult="Rejected single-file MP3 audiobook source before transfer",
                      Completed=0)
        values.update(kwargs)
        self.conn.execute("INSERT INTO wanted VALUES (:BookID,:AuxInfo,:Source,:Status,:DownloadID,:DLResult,:Completed)", values)

    def test_latest_failed_audio_handoff_defers_skip_without_mutation(self):
        self.add()
        self.assertTrue(dbupgrade._defer_helper_rejection(self.db, "42"))
        self.assertEqual(self.conn.execute("SELECT Status FROM wanted").fetchone()[0], "Failed")
        self.assertFalse(dbupgrade._defer_helper_rejection(self.db, "43"))

    def test_no_expiry_for_pending_ownership_even_with_zero_completion_time(self):
        for completed in (0, 1, None):
            self.conn.execute("DELETE FROM wanted")
            self.add(Completed=completed)
            self.assertTrue(dbupgrade._defer_helper_rejection(self.db, "42"))

    def test_requires_exact_paired_protocol_and_owner(self):
        self.add()
        for key, value in (("BOX_LL_HANDOFF_PROTOCOL", ""), ("BOX_LL_HANDOFF_PROTOCOL", "wrong"),
                           ("BOX_LL_QBIT_LIFECYCLE_OWNER", "legacy"), ("BOX_LL_QBIT_LIFECYCLE_OWNER", "")):
            with patch.dict(os.environ, {key: value}):
                self.assertFalse(dbupgrade._defer_helper_rejection(self.db, "42"))

    def test_rejects_invalid_hash_and_unrecognized_failure(self):
        for changes in ({"DownloadID": ""}, {"DownloadID": "a" * 39},
                        {"DownloadID": "g" * 40}, {"Source": "DIRECT"},
                        {"Status": "Ignored"}, {"DLResult": "Connection timed out"},
                        {"DLResult": "text mentioning Rejected later"}):
            self.conn.execute("DELETE FROM wanted")
            self.add(**changes)
            self.assertFalse(dbupgrade._defer_helper_rejection(self.db, "42"), changes)

    def test_newer_other_source_row_prevents_trusting_historical_rejection(self):
        self.add()
        self.add(Source="DIRECT", DLResult="Connection timed out")
        self.assertFalse(dbupgrade._defer_helper_rejection(self.db, "42"))

    def test_latest_audio_row_ignores_unrelated_ebook_history(self):
        self.add()
        self.add(AuxInfo="eBook", Source="DIRECT")
        self.assertTrue(dbupgrade._defer_helper_rejection(self.db, "42"))

    def test_supported_hash_and_rejection_variants(self):
        for reason in ("Rejected repeated previously failed audiobook source before transfer",
                       "Audiobook validation failed: Rejected wrong metadata",
                       "LazyLibrarian rejected source after qBittorrent add: invalid payload"):
            self.conn.execute("DELETE FROM wanted")
            self.add(DownloadID="A" * 64, DLResult=reason)
            self.assertTrue(dbupgrade._defer_helper_rejection(self.db, "42"))


    def test_startup_preserves_helper_handoff_and_existing_user_skips(self):
        self.conn.executemany("INSERT INTO books (BookID,AudioStatus) VALUES (?,?)", [
            ("42", "Snatched"), ("skip", "Skipped"), ("legacy", "Snatched")])
        self.add()
        dbupgrade._reconcile_orphan_status(self.db, Mock())
        states = dict(self.conn.execute("SELECT BookID,AudioStatus FROM books").fetchall())
        self.assertEqual(states, {"42": "Snatched", "skip": "Skipped", "legacy": "Skipped"})

    def test_startup_does_not_clobber_concurrent_user_state_change(self):
        self.conn.execute("INSERT INTO books (BookID,AudioStatus) VALUES ('42','Snatched')")
        original = self.db.action

        def change_before_write(query, params):
            self.conn.execute("UPDATE books SET AudioStatus='Wanted' WHERE BookID='42'")
            return original(query, params)

        with patch.object(self.db, "action", side_effect=change_before_write):
            dbupgrade._reconcile_orphan_status(self.db, Mock())
        self.assertEqual(self.conn.execute("SELECT AudioStatus FROM books").fetchone()[0], "Wanted")


    def test_ebook_symmetry_preserves_only_ebook_rejection_and_audio_state(self):
        self.conn.execute("INSERT INTO books VALUES ('42','Have','Snatched')")
        self.add(AuxInfo="eBook", DLResult="Rejected archive payload before LazyLibrarian import: corrupt")
        dbupgrade._reconcile_orphan_status(self.db, Mock(), "eBook")
        row = self.conn.execute("SELECT Status,AudioStatus FROM books").fetchone()
        self.assertEqual(tuple(row), ("Snatched", "Have"))

    def test_ebook_timeout_defers_but_different_media_failure_does_not(self):
        self.add(AuxInfo="eBook", DLResult="LazyLibrarian ebook import verification timed out: missing file")
        self.assertTrue(dbupgrade._defer_helper_rejection(self.db, "42", "eBook"))
        self.assertFalse(dbupgrade._defer_helper_rejection(self.db, "42", "AudioBook"))

    def test_fixed_column_and_media_whitelist(self):
        with self.assertRaises(ValueError):
            dbupgrade._reconcile_orphan_status(self.db, Mock(), "Status; DELETE FROM books")
        with self.assertRaises(ValueError):
            dbupgrade._defer_helper_rejection(self.db, "42", "unknown")


    def test_concurrent_new_wanted_row_prevents_skip(self):
        self.conn.execute("INSERT INTO books (BookID,AudioStatus) VALUES ('42','Snatched')")
        original = self.db.action

        def add_before_write(query, params):
            self.add(Status="Snatched")
            return original(query, params)

        with patch.object(self.db, "action", side_effect=add_before_write):
            dbupgrade._reconcile_orphan_status(self.db, Mock())
        self.assertEqual(self.conn.execute("SELECT AudioStatus FROM books").fetchone()[0], "Snatched")

    def test_concurrent_in_place_rejection_transition_prevents_skip(self):
        self.conn.execute("INSERT INTO books (BookID,AudioStatus) VALUES ('42','Snatched')")
        self.add(DLResult="temporary download error")
        original = self.db.action

        def reject_before_write(query, params):
            self.conn.execute("UPDATE wanted SET DLResult='Rejected single-file MP3 audiobook source before transfer'")
            return original(query, params)

        with patch.object(self.db, "action", side_effect=reject_before_write):
            dbupgrade._reconcile_orphan_status(self.db, Mock())
        self.assertEqual(self.conn.execute("SELECT AudioStatus FROM books").fetchone()[0], "Snatched")
