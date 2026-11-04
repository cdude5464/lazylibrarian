import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from lazylibrarian import ebook_edition_policy as policy


class EditionExceptionTest(TestCase):
    def test_exception_is_exact_and_cannot_relax_other_rejection_words(self):
        words = ["anniversary", "spanish", "mp3"]
        item = {"download_id": "a" * 40, "author": "Author", "title": "Book",
                "approved": True, "allowed_words": ["anniversary"]}
        with tempfile.TemporaryDirectory() as directory, patch.object(
                policy, "DIRS", SimpleNamespace(DATADIR=directory)):
            path = Path(directory) / "ebook-edition-exceptions.json"

            def write(entries):
                path.write_text(json.dumps({"schema": "ebook-edition-exceptions-v1", "entries": entries}))

            write([item])
            self.assertEqual(policy.filter_edition_reject_words(words, "a" * 40, "Author", "Book"),
                             ["spanish", "mp3"])
            for h, a, t in [(7, "Author", "Book"), ("a" * 40, None, "Book"),
                            ("a" * 40, "Author", []), ("b" * 40, "Author", "Book"), ("a" * 40, "Other", "Book"),
                            ("a" * 40, "Author", "Other"), ("", "Author", "Book")]:
                self.assertEqual(policy.filter_edition_reject_words(words, h, a, t), words)
            for entries in ([item, item], [dict(item, approved=False)],
                            [dict(item, allowed_words=["mp3"])], [dict(item, allowed_words="anniversary")]):
                write(entries)
                self.assertEqual(policy.filter_edition_reject_words(words, "a" * 40, "Author", "Book"), words)
            path.write_text("invalid")
            self.assertEqual(policy.filter_edition_reject_words(words, "a" * 40, "Author", "Book"), words)
