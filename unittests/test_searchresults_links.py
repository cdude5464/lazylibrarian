"""Test the actual search-result buttons and their parsed HTTP parameters."""
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import cherrypy
from bs4 import BeautifulSoup
from mako.lookup import TemplateLookup

import lazylibrarian
from lazylibrarian import webServe
from lazylibrarian.config2 import CONFIG


class SearchResultLinksTest(TestCase):
    def test_rendered_add_links_have_one_value_per_parameter(self):
        lookup = TemplateLookup(directories=[str(Path(__file__).resolve().parents[1] / 'data/interfaces/bookstrap')])
        result = dict(bookid='ID+123', authorid='author-1', authorname='Blake & Crouch',
                      bookname='Recursion + Test', source='GoodReads', bookimg='images/nocover.png',
                      booklink='https://example.invalid/', bookdate='2019', bookrate=4.1, highest_fuzz=100)
        cfg = Mock()
        cfg.get_int.return_value = 1
        for existing in (False, True):
            with self.subTest(existing=existing), patch.dict(lookup.get_template('searchresults.html').module.__dict__, CONFIG=cfg):
                html = lookup.get_template('searchresults.html').get_def('body').render(
                    title='Search', searchresults=[result], authorlist=['author-1'], loadlist=[],
                    booklist=['ID+123'] if existing else [],
                    booksearch=[dict(BookID='ID+123', Status='Skipped', AudioStatus='Skipped')], _=lambda x:x)
            links = [a['href'] for a in BeautifulSoup(html, 'html.parser').find_all('a', href=True)
                     if a['href'].startswith('add_book?')]
            self.assertEqual(len(links), 2)
            libraries = set()
            for link in links:
                values = parse_qs(urlsplit(link).query, keep_blank_values=True)
                self.assertTrue(all(len(v) == 1 for v in values.values()), values)
                self.assertEqual(values['source'], ['GoodReads'])
                self.assertEqual(values['title'], [result['bookname']])
                self.assertEqual(values['authorname'], [result['authorname']])
                self.assertEqual(values['bookid'], [result['bookid']])
                libraries.add(values['library'][0])
            self.assertEqual(libraries, {'eBook', 'AudioBook'})

    def test_ambiguous_source_rejected_before_any_book_mutation(self):
        interface = webServe.WebInterface()
        for source in (['GoodReads', 'GoogleBooks'], [], {'source':'GoodReads'}, [None]):
            with self.subTest(source=source), patch.object(interface, 'check_permitted'), \
                 patch.object(webServe, 'update_existing_book_status') as update, \
                 patch.object(webServe, '_add_search_result_book_to_db') as add:
                with self.assertRaises(cherrypy.HTTPError) as error:
                    interface.add_book(bookid='123', library='eBook', source=source)
                self.assertEqual(error.exception.status, 400)
                update.assert_not_called()
                add.assert_not_called()

    def test_source_validator_handles_non_scalar_values_without_crashing(self):
        for value in ([], ['GoodReads'], {}, 12):
            self.assertIsNone(webServe.valid_search_result_source(value))
