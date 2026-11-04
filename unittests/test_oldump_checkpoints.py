#  This file is part of Lazylibrarian.
#
# Purpose:
#   philborman, Raspberry Pi 4 (!1847/!1900, 2026-09): a 35-minute OpenLibrary dump import on
#   a laptop SSD took over 24 hours on a Pi. SQLite's default wal_autocheckpoint (~4MB) auto-
#   fires a checkpoint - a scattered, random-write merge into the main db file, not a
#   sequential one - roughly every 4MB written, thousands of times over a 15M+ row import;
#   random writes are exactly what SD-card/eMMC storage handles far worse than an SSD.
#   Covers: the raised auto-checkpoint threshold, the explicit PASSIVE checkpoints replacing
#   it at our own commit boundary, the final TRUNCATE, and that a checkpoint failure never
#   aborts the import.

import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

from lazylibrarian import oldump


class WalAutocheckpointTest(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = os.path.join(self.dir, 'ol_catalog.sqlite3')

    def test_auto_checkpoint_threshold_is_raised_well_above_sqlites_tiny_default(self):
        conn = oldump.init_dump_db(self.path)
        try:
            threshold = conn.execute("PRAGMA wal_autocheckpoint;").fetchone()[0]
            # sqlite's own default is 1000 pages (~4MB) - anything close to that would still
            # auto-fire constantly over a multi-million-row import
            self.assertGreater(threshold, 10000)
        finally:
            conn.close()

    def test_still_in_wal_mode(self):
        conn = oldump.init_dump_db(self.path)
        try:
            mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            self.assertEqual(mode.lower(), 'wal')
        finally:
            conn.close()


class CheckpointTest(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = os.path.join(self.dir, 'ol_catalog.sqlite3')
        self.conn = oldump.init_dump_db(self.path)
        self.addCleanup(self.conn.close)

    def _wal_size(self):
        wal_path = self.path + '-wal'
        return os.path.getsize(wal_path) if os.path.exists(wal_path) else 0

    def test_passive_checkpoint_runs_without_error_on_a_real_connection(self):
        self.conn.executemany("INSERT INTO ol_authors (author_id, author_name) VALUES (?, ?)",
                              [(f'OL{i}A', f'Author {i}') for i in range(100)])
        self.conn.commit()
        oldump._checkpoint(self.conn)  # must not raise

    def test_truncate_checkpoint_shrinks_the_wal_file(self):
        self.conn.executemany("INSERT INTO ol_authors (author_id, author_name) VALUES (?, ?)",
                              [(f'OL{i}A', f'Author {i}' * 50) for i in range(5000)])
        self.conn.commit()
        self.assertGreater(self._wal_size(), 0)
        oldump._checkpoint(self.conn, mode='TRUNCATE')
        self.assertEqual(self._wal_size(), 0)

    def test_a_checkpoint_failure_is_logged_and_swallowed_not_raised(self):
        fake_conn = mock.Mock()
        fake_conn.execute.side_effect = sqlite3.OperationalError('database is locked')
        oldump._checkpoint(fake_conn)  # must not raise
