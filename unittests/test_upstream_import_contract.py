"""Pure regressions for helper ownership across upstream postprocess updates."""
from unittest import TestCase
from unittest.mock import Mock, patch
import logging

from lazylibrarian import postprocess


class UpstreamImportOwnershipTest(TestCase):
    def test_failed_zero_progress_qbit_is_not_native_orphan_cleanup_authority(self):
        for reason in (None, 'BOX_HELPER_PRE_REJECTED: unsupported source'):
            with self.subTest(reason=reason):
                db = Mock()
                db.select.return_value = [{
                    'Source': 'QBITTORRENT', 'DownloadID': 'a' * 40,
                    'Origin': 'new', 'Status': 'Failed', 'DLResult': reason,
                    'NZBDate': '2020-01-01 00:00:00',
                }]
                with (patch.object(postprocess.CONFIG, 'get_bool', return_value=True),
                      patch.object(postprocess.CONFIG, 'get_int', return_value=1),
                      patch.object(postprocess, 'get_download_progress') as progress,
                      patch.object(postprocess, 'delete_task') as delete):
                    postprocess._cleanup_orphaned_failed_downloads(db, logging.getLogger(__name__))
                progress.assert_not_called()
                delete.assert_not_called()
                db.action.assert_not_called()

    def test_failed_qbit_task_without_active_sibling_still_belongs_to_helper(self):
        db = Mock()
        state = postprocess.BookState(book_id='42', download_title='Book',
                                      source='QBITTORRENT', download_id='a' * 40)
        with patch.object(postprocess, 'delete_task') as delete:
            result = postprocess._delete_failed_task_if_unused(db, state, logging.getLogger(__name__))
        self.assertFalse(result)
        delete.assert_not_called()
        db.match.assert_not_called()

    def test_non_helper_orphan_still_uses_upstream_stall_age_and_readback(self):
        db = Mock()
        db.select.return_value = [{
            'Source': 'TRANSMISSION', 'DownloadID': 'b' * 40,
            'Origin': 'new', 'Status': 'Failed', 'DLResult': 'failed',
            'NZBDate': '2020-01-01 00:00:00',
        }]
        db.match.return_value = None
        with (patch.object(postprocess.CONFIG, 'get_bool', return_value=True),
              patch.object(postprocess.CONFIG, 'get_int', return_value=1),
              patch.object(postprocess, 'get_download_progress', return_value=(0, False)),
              patch.object(postprocess, '_calculate_download_age', return_value=(3, 180, 0)),
              patch.object(postprocess, 'delete_task', return_value=True) as delete):
            postprocess._cleanup_orphaned_failed_downloads(db, logging.getLogger(__name__))
        delete.assert_called_once_with('TRANSMISSION', 'b' * 40, False, abandoned=True)
        db.action.assert_called_once()


class UpstreamAuthorImageQualityTest(TestCase):
    def test_rejected_book_cover_does_not_count_as_success_and_stop_fallback(self):
        import tempfile
        from pathlib import Path
        from PIL import Image
        from lazylibrarian import images
        with tempfile.TemporaryDirectory() as directory:
            cover = Path(directory) / 'provider.jpg'
            Image.new('RGB', (100, 250)).save(cover)
            self.assertEqual(images._author_candidate_count(directory, 1), 0)
            self.assertFalse(cover.exists())
            portrait = Path(directory) / 'fallback.jpg'
            Image.new('RGB', (200, 220)).save(portrait)
            self.assertEqual(images._author_candidate_count(directory, 1), 1)
            self.assertTrue(portrait.exists())

    def test_multi_image_preview_does_not_apply_automatic_portrait_gate(self):
        import tempfile
        from pathlib import Path
        from PIL import Image
        from lazylibrarian import images
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / 'book-cover.jpg'
            Image.new('RGB', (100, 250)).save(candidate)
            self.assertEqual(images._author_candidate_count(directory, 5), 1)
            self.assertTrue(candidate.exists())


class UpstreamImportFailureIdentityTest(TestCase):
    def test_failed_attempt_preserves_shared_url_siblings_and_owned_book(self):
        import sqlite3
        from types import SimpleNamespace
        for current, expected in [('Snatched', 'Wanted'), ('Have', 'Have'), ('Ignored', 'Ignored')]:
            with self.subTest(current=current), sqlite3.connect(':memory:') as connection:
                connection.executescript('''
                    CREATE TABLE books (BookID, Status, AudioStatus);
                    CREATE TABLE wanted (BookID, DownloadID, Source, AuxInfo, NZBurl, Status, DLResult, NZBDate);
                ''')
                connection.execute('INSERT INTO books VALUES (?,?,?)', ('target', current, 'Have'))
                values = [
                    ('target', 'hash-a', 'QBITTORRENT', 'eBook', 'same-url', 'Snatched'),
                    ('sibling', 'hash-a', 'QBITTORRENT', 'eBook', 'same-url', 'Snatched'),
                    ('target', 'hash-a', 'QBITTORRENT', 'AudioBook', 'same-url', 'Snatched'),
                    ('target', 'hash-b', 'QBITTORRENT', 'eBook', 'same-url', 'Snatched'),
                    ('target', 'hash-a', 'QBITTORRENT', 'eBook', 'same-url', 'Processed'),
                ]
                connection.executemany('INSERT INTO wanted VALUES (?,?,?,?,?,?,NULL,NULL)', values)
                db = SimpleNamespace(action=lambda sql, args: connection.execute(sql, args))
                state = postprocess.BookState(
                    book_id='target', download_title='Book', source='QBITTORRENT',
                    download_id='hash-a', download_url='same-url', aux_info='eBook', aux_type='eBook',
                )
                metadata = SimpleNamespace(global_name='Book', book_type_enum=postprocess.BookType.EBOOK,
                                           book_type='eBook')
                with (patch.object(state, 'get_display_name', return_value='Provider'),
                      patch.object(postprocess, 'custom_notify_snatch'),
                      patch.object(postprocess, 'notify_snatch'),
                      patch.object(postprocess, '_cleanup_failed_download')):
                    postprocess._handle_failed_processing(state, '/isolated/job', metadata, 'failed', db,
                                                          logging.getLogger(__name__))
                self.assertEqual([r[0] for r in connection.execute('SELECT Status FROM wanted ORDER BY rowid')],
                                 ['Failed', 'Snatched', 'Snatched', 'Snatched', 'Processed'])
                self.assertEqual(connection.execute('SELECT Status,AudioStatus FROM books').fetchone(),
                                 (expected, 'Have'))
