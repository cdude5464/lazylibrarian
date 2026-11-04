"""A duplicate acknowledgement is success only with attached file evidence."""
import logging
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from lazylibrarian import calibre_integration, postprocess


class DuplicateConfig(dict):
    def get_bool(self, name):
        return name == 'DEL_DOWNLOADFAILED'

    def is_valid_booktype(self, filename, booktype):
        return filename.endswith('.epub')


class CalibreDuplicateProofTest(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / 'source'
        self.source.mkdir()
        (self.source / 'payload.epub').write_bytes(b'valid source retained as evidence')
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            CREATE TABLE books (BookID, Status, AudioStatus, BookFile, BookLibrary);
            CREATE TABLE wanted (BookID,DownloadID,Source,AuxInfo,NZBurl,Status,DLResult,NZBDate);
            INSERT INTO books VALUES ('42','Snatched','Ignored',NULL,NULL);
            INSERT INTO wanted VALUES ('42','a','DIRECT','eBook','md5','Snatched',NULL,NULL);
        ''')
        self.reader = SimpleNamespace(
            match=lambda query, args: self.db.execute(query, args).fetchone(),
            action=lambda query, args: self.db.execute(query, args), close=lambda: None,
        )
        self.config = DuplicateConfig(FOUND_STATUS='Have')
        self.data = {'BookID':'42','AuthorName':'Writer','BookName':'Book'}

    def send(self):
        with (patch.object(calibre_integration, 'CONFIG', self.config),
              patch.object(calibre_integration.database, 'DBConnection', return_value=self.reader),
              patch.object(calibre_integration, '_refresh_author_totals_for_book'),
              patch.object(calibre_integration, 'calibredb', return_value=('Use --duplicates','',0))):
            return calibre_integration.send_to_calibre('ebook','Imported',str(self.source),self.data)

    def test_duplicate_without_existing_file_is_failed_not_empty_success(self):
        success, result, folder = self.send()
        self.assertFalse(success)
        self.assertTrue(result.startswith(calibre_integration.CALIBRE_DUPLICATE_UNVERIFIED))
        self.assertEqual(folder,str(self.source))
        self.assertTrue((self.source/'Imported.epub').exists())
        self.assertEqual(self.db.execute('SELECT Status,BookFile FROM books').fetchone()['Status'],'Snatched')

    def test_duplicate_with_missing_file_pointer_is_not_verified(self):
        self.db.execute('UPDATE books SET BookFile=?',(str(Path(self.temp.name)/'gone.epub'),))
        success, result, _ = self.send()
        self.assertFalse(success)
        self.assertTrue(result.startswith(calibre_integration.CALIBRE_DUPLICATE_UNVERIFIED))

    def test_verified_duplicate_returns_actual_existing_destination(self):
        existing = Path(self.temp.name)/'canonical.epub'
        existing.write_bytes(b'verified existing file')
        self.db.execute('UPDATE books SET BookFile=?',(str(existing),))
        success, result, _ = self.send()
        self.assertTrue(success)
        self.assertEqual(result,str(existing))
        self.assertEqual(self.db.execute('SELECT Status FROM books').fetchone()['Status'],'Have')

    def test_unverified_duplicate_never_processed_and_preserves_source_even_if_delete_configured(self):
        state = postprocess.BookState(book_id='42',download_title='Book',aux_type='eBook',
                                      aux_info='eBook',download_id='a',source='DIRECT',download_url='md5',
                                      candidate_ptr=str(self.source))
        metadata = postprocess.EbookMetadata(book_id='42',book_type_enum=postprocess.BookType.EBOOK,
                                            dest_path='/not-used',global_name='Imported',
                                            author_name='Writer',book_name='Book')
        with (patch.object(postprocess,'prepare_book_metadata',return_value=metadata),
              patch.object(postprocess,'_process_destination',side_effect=lambda **kwargs:self.send()),
              patch.object(state,'get_display_name',return_value='Anna'),
              patch.object(postprocess,'custom_notify_snatch'),
              patch.object(postprocess,'notify_snatch'),
              patch.object(postprocess,'CONFIG',self.config)):
            count=postprocess._process_book_after_matching(state,str(self.source.parent),True,self.reader,
                                                          logging.getLogger(__name__))
        self.assertEqual(count,0)
        row=self.db.execute('SELECT Status,DLResult FROM wanted').fetchone()
        self.assertEqual(row['Status'],'Failed')
        self.assertTrue(row['DLResult'].startswith(calibre_integration.CALIBRE_DUPLICATE_UNVERIFIED))
        self.assertTrue((self.source/'Imported.epub').exists())
        self.assertFalse(Path(str(self.source)+'.fail').exists())
        book = self.db.execute('SELECT Status,BookFile FROM books').fetchone()
        self.assertIsNone(book['BookFile'])
        self.assertEqual(book['Status'],'Snatched')
