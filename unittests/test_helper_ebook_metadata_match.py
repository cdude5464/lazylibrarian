"""Exact embedded identity fallback for obfuscated ebooks in helper jobs."""
import logging
from unittest import mock

import pytest

from lazylibrarian import postprocess
from lazylibrarian.config2 import LLConfigHandler
from lazylibrarian.configdefs import BASE_DEFAULTS


@pytest.fixture
def helper_book(tmp_path):
    download_id = '17a1e02daee4128b24d18d99acf617c85fbbabd6'
    root = tmp_path / f'lazylibrarian-{download_id}'
    release = root / '__extracted' / 'Barbara.Michaels.Houses.of.Stone.2009.Retail.EPUB.eBook-NODE'
    payload = release / 'oh3pcqy' / 'oh3pcqy1.epub'
    payload.parent.mkdir(parents=True)
    payload.write_bytes(b'epub placeholder')
    state = postprocess.BookState(
        book_id='140413', download_title='Barbara.Michaels.Houses.of.Stone.2009.Retail.EPUB.eBook-NODE',
        book_title='Barbara Michaels - Houses of Stone', aux_type='eBook', download_id=download_id)
    config = LLConfigHandler(defaults=BASE_DEFAULTS)
    with mock.patch.object(postprocess, 'CONFIG', config), \
            mock.patch.object(postprocess.database, 'DBConnection') as db, \
            mock.patch.object(postprocess, '_requested_context_for_content_check',
                              return_value=('Barbara Michaels', 'Houses of Stone')), \
            mock.patch.object(postprocess, 'get_book_info') as metadata:
        db.return_value.match.return_value = {'BookLang': 'eng'}
        metadata.return_value = {'title': 'Houses of Stone', 'creator': 'Barbara Michaels', 'language': 'en-US'}
        yield state, payload, metadata


def test_exact_identity_matches_obfuscated_ebook(helper_book):
    state, payload, _ = helper_book
    assert postprocess._exact_helper_ebook_metadata_match(state, str(payload))


@pytest.mark.parametrize('key, value', [
    ('title', 'Houses of Stone 2'), ('title', 'House of Stone'),
    ('creator', 'Other Author'), ('creator', ''), ('title', ''), ('language', 'nl')])
def test_conflicting_or_missing_metadata_is_refused(helper_book, key, value):
    state, payload, metadata = helper_book
    metadata.return_value[key] = value
    assert not postprocess._exact_helper_ebook_metadata_match(state, str(payload))


def test_metadata_read_failure_is_refused(helper_book):
    state, payload, metadata = helper_book
    metadata.side_effect = ValueError('bad epub')
    assert not postprocess._exact_helper_ebook_metadata_match(state, str(payload))


def test_foreign_job_and_non_ebook_are_refused(helper_book):
    state, payload, _ = helper_book
    assert not postprocess._exact_helper_ebook_metadata_match(state, '/unrelated/oh3pcqy1.epub')
    state.download_id = 'another-job'
    assert not postprocess._exact_helper_ebook_metadata_match(state, str(payload))
    state.download_id = payload.parents[3].name.removeprefix('lazylibrarian-')
    state.aux_type = 'AudioBook'
    assert not postprocess._exact_helper_ebook_metadata_match(state, str(payload))


@pytest.mark.parametrize('extra_book', [False, True])
def test_directory_fallback_requires_single_exact_metadata_ebook(helper_book, extra_book):
    state, payload, _ = helper_book
    if extra_book:
        (payload.parent / 'other.epub').write_bytes(b'other')
    logger = logging.getLogger('test.helper-metadata')
    # Explicitly recreate the filename mismatch independent of global sanitizing.
    with mock.patch.object(postprocess, '_best_candidate_match', return_value=(84.615, 'release')), \
            mock.patch.object(postprocess, '_find_matching_subdir', return_value=('', 0)), \
            mock.patch.object(postprocess, '_find_matching_file_for_book_state', return_value=('', 0)):
        matched, percentage = postprocess._try_match_candidate_file(
            payload.parents[1].name, state, str(payload.parents[2]), 85, logger, logger)
    assert matched is (not extra_book)
    if not extra_book:
        assert percentage == 100
        assert state.candidate_ptr == str(payload)
        assert state.candidate_match_kind == 'inner_file_name'


def test_other_ebook_elsewhere_in_job_refuses_exact_fallback(helper_book):
    state, payload, _ = helper_book
    job_root = payload.parents[3]
    (job_root / 'sibling.epub').write_bytes(b'other book')
    assert not postprocess._exact_helper_ebook_metadata_match(state, str(payload))


def test_ebook_symlink_outside_job_refuses_exact_fallback(helper_book, tmp_path):
    state, payload, _ = helper_book
    outside = tmp_path / 'outside.epub'
    outside.write_bytes(b'outside book')
    payload.unlink()
    payload.symlink_to(outside)
    assert not postprocess._exact_helper_ebook_metadata_match(state, str(payload))


def test_database_connection_closes_on_metadata_error(helper_book):
    state, payload, metadata = helper_book
    metadata.side_effect = ValueError('bad epub')
    db = postprocess.database.DBConnection.return_value
    assert not postprocess._exact_helper_ebook_metadata_match(state, str(payload))
    db.close.assert_called_once()


@pytest.mark.parametrize("correct_title", [True, False])
def test_scoped_row_gate_accepts_obfuscated_archive_only_with_exact_metadata(helper_book, correct_title):
    state, payload, metadata = helper_book
    if not correct_title:
        metadata.return_value["title"] = "Different Book"
    logger = logging.getLogger("test.helper-metadata")
    with mock.patch.object(postprocess.BookState, "from_db_row", return_value=state), \
            mock.patch.object(postprocess, "_populate_local_book_title"), \
            mock.patch.object(postprocess, "_best_candidate_match", return_value=(0, "")):
        matched, _ = postprocess._row_matches_helper_startdir(
            {}, mock.Mock(), str(payload.parents[2]), logger)
    assert matched is correct_title
