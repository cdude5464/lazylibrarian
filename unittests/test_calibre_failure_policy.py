"""A command crash must preserve validated direct bytes, not blacklist content."""
import logging
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from lazylibrarian import postprocess, resultlist
from lazylibrarian.calibre_failure_policy import calibre_command_crashed


CRASH = 'calibredb rc -11 from /usr/bin/calibredb'


class CalibreFailurePolicyTest(TestCase):
    def test_only_exact_witnessed_command_crash_is_retryable(self):
        self.assertTrue(calibre_command_crashed(CRASH))
        self.assertTrue(calibre_command_crashed('destination: ' + CRASH))
        for reason in ['calibredb rc 1 from /usr/bin/calibredb', CRASH + ' wrong author',
                       'Rejected ' + CRASH, CRASH + '\ntrailing',
                       'Embedded ebook metadata declares a different volume',
                       'Blocked by user', 'calibredb rc -11 from https://host/calibredb']:
            with self.subTest(reason=reason):
                self.assertFalse(calibre_command_crashed(reason))

    def test_retry_is_only_direct_ebook_not_manual_or_content_failure(self):
        row = {'NZBprov': 'annas', 'Status': 'Failed', 'Source': 'DIRECT',
               'NZBmode': 'direct', 'DLResult': CRASH}
        self.assertTrue(resultlist._failed_source_retryable(row, 'eBook'))
        self.assertFalse(resultlist._failed_source_retryable(row, 'AudioBook'))
        for field, value in [('Source', 'QBITTORRENT'), ('NZBmode', 'torrent'),
                             ('Status', 'Ignored'), ('DLResult', 'Blocked by user'),
                             ('DLResult', 'Embedded ebook metadata declares a different volume')]:
            with self.subTest(field=field, value=value):
                self.assertFalse(resultlist._failed_source_retryable({**row, field: value}, 'eBook'))

    def test_direct_crash_retains_bytes_even_when_failed_cleanup_enabled(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / 'retained'
            folder.mkdir()
            payload = folder / 'book.epub'
            payload.write_bytes(b'validated bytes')
            state = postprocess.BookState(book_id='42', download_title='Book', source='DIRECT',
                                          aux_info='eBook', download_id='a' * 32, download_url='a' * 32)
            metadata = SimpleNamespace(global_name='Author Book', book_type_enum=postprocess.BookType.EBOOK,
                                       book_type='ebook')
            db = Mock()
            with (patch.object(postprocess, 'CONFIG', Mock()),
                  patch.object(state, 'get_display_name', return_value='annas'),
                  patch.object(postprocess, 'custom_notify_snatch'), patch.object(postprocess, 'notify_snatch'),
                  patch.object(postprocess, 'notify_text'),
                  patch.object(postprocess, '_cleanup_failed_download') as cleanup):
                postprocess._handle_failed_processing(state, str(folder), metadata, CRASH, db,
                                                     logging.getLogger(__name__))
            cleanup.assert_not_called()
            self.assertEqual(payload.read_bytes(), b'validated bytes')
            self.assertTrue(any("status='Wanted'" in call.args[0] for call in db.action.call_args_list))

    def test_content_failure_still_uses_normal_failed_cleanup(self):
        state = postprocess.BookState(book_id='42', download_title='Book', source='DIRECT')
        metadata = SimpleNamespace(global_name='Author Book', book_type_enum=postprocess.BookType.EBOOK,
                                   book_type='ebook')
        with (patch.object(postprocess, 'CONFIG', Mock()),
              patch.object(state, 'get_display_name', return_value='annas'),
              patch.object(postprocess, 'custom_notify_snatch'), patch.object(postprocess, 'notify_snatch'),
              patch.object(postprocess, 'notify_text'),
              patch.object(postprocess, '_cleanup_failed_download') as cleanup):
            postprocess._handle_failed_processing(state, '/source', metadata,
                'Embedded ebook metadata declares a different volume', Mock(), logging.getLogger(__name__))
        cleanup.assert_called_once()

    def test_same_md5_manual_or_content_failure_shadows_retryable_crash(self):
        for reverse in (False, True):
            for reason in ('Blocked by user', 'Embedded ebook metadata declares a different volume'):
                with self.subTest(reverse=reverse, reason=reason):
                    db = sqlite3.connect(':memory:')
                    db.row_factory = sqlite3.Row
                    self.addCleanup(db.close)
                    db.execute('CREATE TABLE wanted (BookID,NZBurl,NZBprov,Source,NZBmode,Status,DLResult)')
                    rows = [('42', 'a' * 32, 'annas', 'DIRECT', 'direct', 'Failed', CRASH),
                            ('other-book', 'A' * 32, 'annas', 'DIRECT', 'direct', 'Failed', reason)]
                    db.executemany('INSERT INTO wanted VALUES (?,?,?,?,?,?,?)', list(reversed(rows)) if reverse else rows)
                    reader = Mock()
                    reader.select.side_effect = lambda query, args: db.execute(query, args).fetchall()
                    crash_row = db.execute('SELECT * FROM wanted WHERE BookID=?', ('42',)).fetchone()
                    self.assertTrue(resultlist._failed_source_retryable(crash_row, 'eBook'))
                    self.assertTrue(resultlist._anna_failure_blocks(reader, 'a' * 32, 'eBook'))
