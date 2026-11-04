"""Exact embedded identity fallback for obfuscated ebooks in helper jobs."""
import logging
import json
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


def test_series_display_does_not_break_exact_metadata(helper_book):
    state, payload, _ = helper_book
    with mock.patch.object(postprocess, "_requested_context_for_content_check",
                           return_value=("Barbara Michaels", "Houses of Stone (Series, #2.5)")):
        assert postprocess._exact_helper_ebook_metadata_match(state, str(payload))


def test_work_title_retains_non_series_work_text():
    assert postprocess._work_title("Book (Part One)") == "Book (Part One)"
    assert postprocess._work_title("Book 2") == "Book 2"
    assert postprocess._work_title("Book (Series, #2.5)") == "Book"


def test_same_work_multiformat_selects_only_preferred_ebook(helper_book):
    state, payload, metadata = helper_book
    alternate = payload.with_suffix(".mobi")
    alternate.write_bytes(b"mobi placeholder")
    metadata.return_value = {"title": "Lost Metal : A Mistborn Novel (9780765391209)",
                             "creator": "Sanderson, Brandon", "language": "en-US"}
    with mock.patch.object(postprocess, "_requested_context_for_content_check",
                           return_value=("Brandon Sanderson", "The Lost Metal (Mistborn, #7)")):
        assert postprocess._exact_helper_ebook_metadata_match(state, str(payload))
        assert not postprocess._exact_helper_ebook_metadata_match(state, str(alternate))


@pytest.mark.parametrize("observed", ["Lost Metal 2", "Lost Metal: Journal", "Lost Metal: A Guide",
                                      "Lost Metal (2)", "Lost Metal: Mistborn 8"])
def test_metadata_work_normalization_preserves_distinct_work_and_volume(observed):
    assert not postprocess._same_metadata_work_title("The Lost Metal (Mistborn, #7)", observed)


def test_byte_identical_prepared_copy_is_eligible_without_path_first_bias(helper_book):
    state, payload, _ = helper_book
    job_root = payload.parents[3]
    original = job_root / payload.name
    original.write_bytes(payload.read_bytes())
    # A retry may have another fully extracted mirror under the same job.
    mirror = payload.parents[2] / "second-extraction" / payload.name
    mirror.parent.mkdir()
    mirror.write_bytes(payload.read_bytes())
    assert postprocess._exact_helper_ebook_metadata_match(state, str(payload))
    assert postprocess._exact_helper_ebook_metadata_match(state, str(mirror))


def test_same_name_different_bytes_prepared_copy_is_refused(helper_book):
    state, payload, _ = helper_book
    copy = payload.parents[3] / payload.name
    copy.write_bytes(b"other EPUB bytes")
    assert not postprocess._exact_helper_ebook_metadata_match(state, str(payload))


def test_same_size_different_bytes_prepared_copy_is_refused(helper_book):
    state, payload, _ = helper_book
    copy = payload.parents[3] / payload.name
    copy.write_bytes(b"x" * payload.stat().st_size)
    assert not postprocess._exact_helper_ebook_metadata_match(state, str(payload))


@pytest.mark.parametrize("suffix", [
    ". Tenth Anniversary Author’s Definitive Edition",
    ". 10th Anniversary Author's Definitive Edition",
])
def test_approved_anniversary_metadata_requires_exact_work_and_author(helper_book, suffix):
    state, payload, metadata = helper_book
    metadata.return_value = {"title": "Elantris" + suffix, "creator": "Brandon Sanderson", "language": "en"}
    with mock.patch.object(postprocess, "_requested_context_for_content_check",
                           return_value=("Brandon Sanderson", "Elantris (Elantris, #1)")), \
            mock.patch.object(postprocess, "filter_edition_reject_words", return_value=[]) as policy:
        assert postprocess._exact_helper_ebook_metadata_match(state, str(payload))
        policy.assert_called_once_with(["anniversary"], state.download_id, "Brandon Sanderson", "Elantris (Elantris, #1)")
        metadata.return_value["creator"] = "Other Author"
        assert not postprocess._exact_helper_ebook_metadata_match(state, str(payload))


@pytest.mark.parametrize("title", [
    "Elantris 2. Tenth Anniversary Author’s Definitive Edition",
    "Elantris. Annotated Edition",
    "Elantris. Tenth Anniversary Study Guide",
    "Elantris: Second Book. Tenth Anniversary Author’s Definitive Edition",
])
def test_anniversary_normalization_preserves_unapproved_identity(title):
    assert not postprocess._same_metadata_work_title("Elantris (Elantris, #1)", title)


def test_duplicate_symlink_to_foreign_job_remains_refused(helper_book, tmp_path):
    state, payload, _ = helper_book
    foreign = tmp_path / "lazylibrarian-ffffffffffffffffffffffffffffffffffffffff" / payload.name
    foreign.parent.mkdir()
    foreign.write_bytes(payload.read_bytes())
    copy = payload.parents[3] / payload.name
    copy.symlink_to(foreign)
    assert not postprocess._exact_helper_ebook_metadata_match(state, str(payload))


@pytest.mark.parametrize("approved_hash", [True, False])
def test_anniversary_edition_requires_exact_private_manifest(helper_book, tmp_path, approved_hash):
    state, payload, metadata = helper_book
    metadata.return_value = {"title": "Elantris. Tenth Anniversary Author’s Definitive Edition",
                             "creator": "Brandon Sanderson", "language": "en"}
    manifest = {"schema": "ebook-edition-exceptions-v1", "entries": [{
        "download_id": state.download_id if approved_hash else "f" * 40,
        "author": "Brandon Sanderson", "title": "Elantris (Elantris, #1)",
        "approved": True, "allowed_words": ["anniversary"]}]}
    (tmp_path / "ebook-edition-exceptions.json").write_text(json.dumps(manifest))
    with mock.patch.object(postprocess.DIRS, "DATADIR", str(tmp_path)), \
            mock.patch.object(postprocess, "_requested_context_for_content_check",
                              return_value=("Brandon Sanderson", "Elantris (Elantris, #1)")):
        assert postprocess._exact_helper_ebook_metadata_match(state, str(payload)) is approved_hash
    # Generic work-title normalization must never strip the private exception.
    assert not postprocess._same_metadata_work_title("Elantris (Elantris, #1)", metadata.return_value["title"])
