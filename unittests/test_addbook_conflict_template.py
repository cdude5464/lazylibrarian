"""Expected add refusals remain actionable and never render metadata as HTML."""
from pathlib import Path
import re
import unittest
from mako.template import Template


class AddConflictTemplateTest(unittest.TestCase):
    def test_both_skins_escape_metadata_and_link_canonical_author(self):
        for skin in ('modern', 'bookstrap'):
            with self.subTest(skin=skin):
                path = Path(__file__).parents[1] / 'data/interfaces' / skin / 'addbook_conflict.html'
                source = re.sub(r'<%inherit[^>]+/>', '', path.read_text())
                html = Template(source).get_def('body').render(
                    title='Review existing library entry', requested_title='<script>bad()</script>',
                    conflict={'AuthorID': 'OL221009A', 'BookName': '<img src=x onerror=bad()>',
                              'Status': 'Have', 'AudioStatus': 'Ignored'}, _=lambda s: s)
                self.assertNotIn('<script>', html)
                self.assertNotIn('<img ', html)
                self.assertIn('&lt;script&gt;', html)
                self.assertIn('author_page?authorid=OL221009A', html)
                self.assertIn('No book was added or changed.', html)
