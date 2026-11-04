#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test where webshare downloads are written

import ntpath
import os
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree
from unittest import mock

from lazylibrarian import filesystem, webshare
from unittests.unittesthelpers import LLTestCaseWithStartup

HOSTILE_NAMES = [
    '../config/evil.epub',
    '/config/evil.epub',
    '\\Users\\Public\\evil.epub',
    '..\\..\\evil.epub',
    'C:\\Windows\\evil.epub',
    'D:evil.epub',
    'sub/dir\\evil.epub',
]


class FakeResponse:
    def __init__(self, chunks, fail_after=None):
        self.status_code = 200
        self._chunks = chunks
        self._fail_after = fail_after

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_content(self, chunk_size=0):
        for i, chunk in enumerate(self._chunks):
            if self._fail_after is not None and i >= self._fail_after:
                raise ConnectionError('connection reset')
            yield chunk


def link_response():
    return ElementTree.fromstring('<response><status>OK</status><link>https://dl.example/f</link></response>'), ''


class SafeFilenameTest(LLTestCaseWithStartup):

    def _assert_single_component(self, name):
        self.assertTrue(name)
        for bad in ('/', '\\', ':'):
            self.assertNotIn(bad, name)
        self.assertNotIn(name, ('.', '..'))

    def test_hostile_names_reduce_to_one_component(self):
        for name in HOSTILE_NAMES:
            with self.subTest(name=name):
                self._assert_single_component(webshare.safe_filename(name))

    def test_hostile_names_reduce_to_one_component_on_windows(self):
        # a name must stay inside the folder when joined as a Windows path
        for name in HOSTILE_NAMES:
            with self.subTest(name=name):
                safe = webshare.safe_filename(name)
                self._assert_single_component(safe)
                self.assertEqual(ntpath.dirname(ntpath.join('C:\\dl\\Book', safe)), 'C:\\dl\\Book')

    def test_ordinary_names_are_kept(self):
        self.assertEqual(webshare.safe_filename('Dune Messiah.epub'), 'Dune Messiah.epub')
        self.assertEqual(webshare.safe_filename('Dune: Messiah.epub'), 'Dune Messiah.epub')

    def test_names_that_reduce_to_nothing(self):
        for name in (None, '', '..', '../', '...', '\\'):
            with self.subTest(name=name):
                self.assertEqual(webshare.safe_filename(name), '')


class InsideTest(LLTestCaseWithStartup):

    def test_inside(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertTrue(webshare._inside(os.path.join(root, 'Book', 'a.epub'), root))
            self.assertFalse(webshare._inside(os.path.join(root, '..', 'a.epub'), root))
            self.assertFalse(webshare._inside(root + '-other/a.epub', root))

    def test_symlink_out_of_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            try:
                os.symlink(outside, os.path.join(root, 'Book'))
            except OSError as e:
                # Windows only lets admins, or users in Developer Mode, create symlinks
                self.skipTest(f"can't create a symlink here: {e}")
            self.assertFalse(webshare._inside(os.path.join(root, 'Book', 'a.epub'), root))


class WebshareDownloadTest(LLTestCaseWithStartup):

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, 'Download')
        os.makedirs(self.root)
        patches = [
            mock.patch.object(webshare, 'get_directory', return_value=self.root),
            mock.patch.object(webshare, '_api', side_effect=lambda *a: link_response()),
            mock.patch.object(webshare, 'webshare_login', return_value=''),
            mock.patch.object(webshare, 'setperm'),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def _all_files(self):
        found = []
        for dirpath, _, files in os.walk(self.tmp.name):
            found += [os.path.join(dirpath, f) for f in files]
        return found

    def test_hostile_name_is_saved_inside_the_book_folder(self):
        for name in HOSTILE_NAMES:
            with self.subTest(name=name), \
                    mock.patch.object(webshare.requests, 'get', return_value=FakeResponse([b'x' * 200])):
                ok, dest = webshare.webshare_download('abc123', 'Book', name)
                self.assertTrue(ok, dest)
                self.assertEqual(os.path.dirname(dest), os.path.join(self.root, 'Book'))
        for path in self._all_files():
            self.assertTrue(path.startswith(os.path.join(self.root, 'Book') + os.sep), path)

    def test_name_that_reduces_to_nothing_is_refused(self):
        with mock.patch.object(webshare.requests, 'get') as get:
            ok, msg = webshare.webshare_download('abc123', 'Book', '..')
        self.assertFalse(ok)
        self.assertIn('outside the download directory', msg)
        get.assert_not_called()

    def test_folder_escaping_the_download_root_is_refused(self):
        with mock.patch.object(webshare.requests, 'get') as get:
            ok, _ = webshare.webshare_download('abc123', os.path.join('..', 'elsewhere'), 'a.epub')
        self.assertFalse(ok)
        get.assert_not_called()
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, 'elsewhere')))

    def test_partial_download_is_removed(self):
        resp = FakeResponse([b'x' * 200, b'y' * 200], fail_after=1)
        with mock.patch.object(webshare.requests, 'get', return_value=resp):
            ok, msg = webshare.webshare_download('abc123', 'Book', 'a.epub')
        self.assertFalse(ok)
        self.assertIn('ConnectionError', msg)
        self.assertEqual(self._all_files(), [])

    def test_failed_download_keeps_existing_file(self):
        existing = os.path.join(self.root, 'Book', 'a.epub')
        os.makedirs(os.path.dirname(existing))
        with open(existing, 'wb') as f:
            f.write(b'good copy')
        for resp in (FakeResponse([b'x' * 200, b'y' * 200], fail_after=1), FakeResponse([b'tiny'])):
            with self.subTest(resp=resp), mock.patch.object(webshare.requests, 'get', return_value=resp):
                ok, _ = webshare.webshare_download('abc123', 'Book', 'a.epub')
                self.assertFalse(ok)
                with open(existing, 'rb') as f:
                    self.assertEqual(f.read(), b'good copy')
        with mock.patch.object(webshare.requests, 'get', side_effect=ConnectionError('refused')):
            ok, _ = webshare.webshare_download('abc123', 'Book', 'a.epub')
        self.assertFalse(ok)
        self.assertEqual(self._all_files(), [existing])

    @unittest.skipIf(os.name == 'nt', "Windows has no unix permissions, chmod only sets the read-only flag")
    def test_saved_file_gets_configured_permissions(self):
        # the temporary file is created 0600, setperm must widen it
        with mock.patch.object(webshare, 'setperm', side_effect=filesystem.setperm), \
                mock.patch.object(webshare.requests, 'get', return_value=FakeResponse([b'x' * 200])):
            ok, dest = webshare.webshare_download('abc123', 'Book', 'a.epub')
        self.assertTrue(ok)
        self.assertEqual(os.stat(dest).st_mode & 0o777, 0o644)

    def test_successful_download_leaves_no_part_file(self):
        with mock.patch.object(webshare.requests, 'get', return_value=FakeResponse([b'x' * 200])):
            ok, dest = webshare.webshare_download('abc123', 'Book', 'a.epub')
        self.assertTrue(ok)
        self.assertEqual(self._all_files(), [dest])
