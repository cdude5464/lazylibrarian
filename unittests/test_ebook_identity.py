"""Explicit embedded identity evidence, independent of fuzzy author scores."""
import logging
import unittest
from unittest.mock import patch

from lazylibrarian.ebook_identity import (
    ebook_audio_edition_conflict,
    ebook_collection_unverified,
    ebook_title_count_conflict,
)
from lazylibrarian.postprocess import _ebook_metadata_conflict, _validate_ebook_embedded_metadata
from lazylibrarian.postprocess_metadata import EbookMetadata


class EmbeddedEditionIdentityTest(unittest.TestCase):
    def validate(self, author, expected, observed, language="en"):
        metadata = EbookMetadata(book_id="audit", author_name=author,
                                 book_name=expected, book_lang="eng")
        with patch("lazylibrarian.postprocess._find_ebook_metadata_file", return_value="audit.epub"), \
                patch("lazylibrarian.postprocess.get_book_info", return_value={
                    "title": observed, "creator": author, "language": language}):
            return _validate_ebook_embedded_metadata("audit", "epub", metadata,
                                                     logging.getLogger("test.identity"))

    def test_historical_mismatches_rejected_before_calibre_metadata_rewrite(self):
        cases = [
            ("Jordan B. Peterson", "24 Rules For Life", "12 Rules For Life", "de", "different title count"),
            ("Jordan B. Peterson", "Beyond Order & 12 Rules Box Set", "Beyond Order: 12 More Rules for Life", "en", "requested collection"),
            ("J.K. Rowling", "Harry Potter 1- 7 Audio Collection", "Harry Potter: The Complete Collection", "en-ca", "audio edition"),
            ("J.K. Rowling", "Harry Potter Boxed Set", "Rowling J K. - 1997 - Harry Potter Set completo", "it", "requested collection"),
            ("Kristin Hannah", "Kristin Hannah Collection - Distant Shores & On Mystic Lake", "On Mystic Lake", "en", "requested collection"),
            ("Kristin Hannah", "The Kristin Hannah Collection Volume 2", "The Kristin Hannah Collection: Volume 1", "en", "different volume"),
            ("Kristin Hannah", "The Kristin Hannah Collection. Volume 1 - Firefly Lane, True Colors, Fly Away", "Firefly Lane", "en", "requested collection"),
            ("J.K. Rowling", "Harry Potter and the Half-Blood Prince", "Harry Potter and the Deathly Hallows", "en", "different named sequel"),
        ]
        for author, expected, observed, language, diagnostic in cases:
            with self.subTest(expected=expected):
                valid, reason = self.validate(author, expected, observed, language)
                self.assertFalse(valid)
                self.assertIn(diagnostic, reason)

    def test_correct_collection_synonyms_counts_and_editions_still_pass(self):
        cases = [
            ("Kristin Hannah", "The Kristin Hannah Collection Volume 2", "The Kristin Hannah Omnibus Volume II"),
            ("Jordan B. Peterson", "Beyond Order & 12 Rules Box Set", "Beyond Order & 12 Rules Boxed Set"),
            ("Jordan B. Peterson", "12 Rules For Life", "12 Rules For Life: An Antidote to Chaos"),
            ("Brandon Sanderson", "Elantris", "Elantris: Tenth Anniversary Author's Definitive Edition"),
            ("Matt Dinniman", "Dungeon Crawler Carl, Vol. 3 (Graphic Novel)", "Dungeon Crawler Carl, Vol. 3 (Graphic Novel)"),
            ("Kristin Hannah", "On Mystic Lake", "On Mystic Lake"),
        ]
        for author, expected, observed in cases:
            with self.subTest(expected=expected):
                self.assertEqual((True, ""), self.validate(author, expected, observed))

    def test_title_count_only_compares_explicit_same_leading_noun(self):
        self.assertTrue(ebook_title_count_conflict("24 Rules For Life", "12 rules for life"))
        for expected, observed in [("1984", "1984"), ("Volume 2", "Volume 1"),
                                   ("12 Rules", "101 Essays"), ("12 Rules", "Rules"),
                                   ("1984 Diaries", "1985 Diaries"),
                                   ("Book 12", "Book 24"), ("12 Rules", "12 Rules: Expanded")]:
            with self.subTest(expected=expected, observed=observed):
                self.assertFalse(ebook_title_count_conflict(expected, observed))

    def test_collection_missing_identity_is_not_a_constituent_work_proof(self):
        self.assertTrue(ebook_collection_unverified("An Omnibus", ""))
        self.assertTrue(ebook_collection_unverified("Box-set", "Single Novel"))
        self.assertFalse(ebook_collection_unverified("Single Novel", "A Collection"))
        self.assertFalse(ebook_collection_unverified("Collection", "Omnibus"))
        self.assertFalse(ebook_collection_unverified("Boxset", "The Complete Series"))
        self.assertFalse(ebook_collection_unverified("Collection", "Collected Works"))

    def test_only_explicit_audio_editions_are_media_conflicts(self):
        for title in ("Audio Collection", "Audio-book Edition", "Audiobook Edition", "Novel (Audiobook)"):
            self.assertTrue(ebook_audio_edition_conflict(title))
        for title in ("Audio Engineering", "The Audiobook Handbook", "Audiobook Narration", "The Book of Sound", "Collection", ""):
            self.assertFalse(ebook_audio_edition_conflict(title))

    def test_explicit_language_guard_still_rejects_valid_collection_identity(self):
        valid, reason = self.validate("J.K. Rowling", "Harry Potter Boxed Set",
                                      "Harry Potter Complete Collection", "it")
        self.assertFalse(valid)
        self.assertIn("unexpected language", reason)

    def test_named_sequel_guard_preserves_alias_subtitles_and_standalone_conjunctions(self):
        cases = [
            ("Harry Potter and the Philosopher's Stone", "Harry Potter and the Sorcerer's Stone"),
            ("Harry Potter and the Half-Blood Prince", "Harry Potter and the Half-Blood Prince: Illustrated Edition"),
            ("Harry Potter and the Half-Blood Prince (Harry Potter #6)", "Harry Potter and the Half Blood Prince"),
            ("The Old Man and the Sea", "The Old Man and the Sea: A Novel"),
            ("Good Omens and Other Stories", "Good Omens and Other Stories: Special Edition"),
            ("The Audiobook Handbook", "The Audiobook Handbook"),
            ("Elantris", "Elantris: Tenth Anniversary Author's Definitive Edition"),
        ]
        for expected, observed in cases:
            with self.subTest(expected=expected):
                self.assertEqual((True, ""), self.validate("Author Name", expected, observed))

    def test_named_sequel_rule_requires_complete_named_metadata(self):
        for creator, title in [("", "Harry Potter and the Deathly Hallows"),
                               ("J.K. Rowling", ""), ("J.K. Rowling", "Unknown"),
                               ("J.K. Rowling", "Harry Potter and a Novel")]:
            with self.subTest(creator=creator, title=title):
                self.assertEqual((False, ""), _ebook_metadata_conflict(
                    "J.K. Rowling", "Harry Potter and the Half Blood Prince", title, creator))
        # Generic creator handling remains with the existing weak-author guard.
        _conflict, reason = _ebook_metadata_conflict(
            "J.K. Rowling", "Harry Potter and the Half Blood Prince",
            "Harry Potter and the Deathly Hallows", "Unknown")
        self.assertNotIn("different named sequel", reason)
