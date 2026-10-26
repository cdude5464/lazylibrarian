#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test the language picker table in booklanguages.py

import unittest
from unittest import mock

from lazylibrarian.annas import Language, anna_languages
from lazylibrarian.booklanguages import (
    BOOK_LANGUAGES,
    GB_COUNTRIES,
    anna_search_languages,
    country_picker,
    language_picker,
    magazine_language_picker,
    zlib_search_languages,
)


class BookLanguagesTest(unittest.TestCase):

    def test_codes_are_unique(self):
        seen = {}
        for name, codes in BOOK_LANGUAGES:
            for code in codes:
                self.assertNotIn(code.lower(), seen, f'{code} is in both {seen.get(code.lower())} and {name}')
                seen[code.lower()] = name

    def test_names_are_codes(self):
        # The English name is what some sources report, so it must match too
        for name, codes in BOOK_LANGUAGES:
            self.assertIn(name, codes)

    def test_default_value(self):
        picker = language_picker('en, eng, en-US, en-GB, English')
        selected = [lang['name'] for lang in picker['languages'] if lang['selected']]
        self.assertEqual(selected, ['English'])
        # and All and Unknown
        self.assertEqual(len(picker['languages']), len(BOOK_LANGUAGES) + 2)

    def test_any_code_selects_language(self):
        picker = language_picker('CZE, sk')
        selected = [lang['name'] for lang in picker['languages'] if lang['selected']]
        self.assertEqual(selected, ['Czech', 'Slovak'])

    def test_unknown_entries_are_kept(self):
        # All, Unknown and codes the picker doesn't know are entries of their own, in their order
        picker = language_picker('en, Unknown, All, xx-YY')
        selected = [lang for lang in picker['languages'] if lang['selected']]
        self.assertEqual([lang['name'] for lang in selected], ['English', 'Unknown', 'All', 'xx-YY'])
        self.assertEqual([lang['codes'] for lang in selected[1:]], ['Unknown', 'All', 'xx-YY'])
        self.assertEqual(len(picker['languages']), len(BOOK_LANGUAGES) + 3)

    def test_empty_value(self):
        picker = language_picker('')
        self.assertFalse(any(lang['selected'] for lang in picker['languages']))

    def test_selected_keep_their_order(self):
        picker = language_picker('sk, slo, slk, Slovak, cs, cze, ces, Czech, Unknown')
        selected = [lang for lang in picker['languages'] if lang['selected']]
        self.assertEqual([lang['name'] for lang in selected], ['Slovak', 'Czech', 'Unknown'])
        self.assertEqual([lang['anna'] for lang in selected], ['SK', 'CS', ''])
        self.assertEqual([lang['zlib'] for lang in selected], ['slovak', 'czech', ''])

    def test_anna_unsupported(self):
        picker = language_picker('Welsh')
        self.assertEqual(picker['languages'][0]['anna'], '')

    def test_anna_languages(self):
        # the picker fills in several languages, older configs have a single one
        self.assertEqual(anna_languages('SK, CS'), [Language.SK, Language.CS])
        self.assertEqual(anna_languages('de'), [Language.DE])
        self.assertEqual(anna_languages('EN, XX, en'), [Language.EN])
        self.assertEqual(anna_languages('ANY'), [])
        self.assertEqual(anna_languages('EN, ANY'), [])
        self.assertEqual(anna_languages(''), [])

    def test_order(self):
        # selected first in their order, then All and Unknown, then the browser languages, then the rest, by name
        picker = language_picker('Yiddish, Welsh', ['cs', 'nb_no', 'sk', 'welsh'])
        shown = [lang['name'] for lang in picker['languages'] if lang['shown']]
        self.assertEqual(shown, ['Yiddish', 'Welsh', 'All', 'Unknown', 'Czech', 'Norwegian', 'Slovak'])
        names = [lang['name'] for lang in picker['languages']]
        self.assertEqual(names[:len(shown)], shown)
        rest = [lang['label'].lower() for lang in picker['languages'][len(shown):]]
        self.assertEqual(rest, sorted(rest))
        self.assertEqual(len(picker['languages']), len(BOOK_LANGUAGES) + 2)

    @mock.patch('lazylibrarian.i18n.available_languages', return_value=['de', 'en', 'sk'])
    def test_interface_languages_not_shown(self, _):
        # the interface languages will grow, only selected and browser languages come before "Show all"
        picker = language_picker('en, eng', ['fr'])
        self.assertEqual([lang['name'] for lang in picker['languages'] if lang['shown']],
                         ['English', 'All', 'Unknown', 'French'])
        self.assertEqual([lang['name'] for lang in language_picker('', [])['languages'] if lang['shown']],
                         ['All', 'Unknown'])

    def test_countries(self):
        self.assertEqual(len(GB_COUNTRIES), 249)
        self.assertEqual(len(set(GB_COUNTRIES)), 249)
        self.assertEqual(list(GB_COUNTRIES), sorted(GB_COUNTRIES))
        self.assertTrue(all(len(code) == 2 and code.isupper() for code in GB_COUNTRIES))

    def test_country_picker(self):
        self.assertEqual(country_picker('sk ')['selected'], 'SK')
        self.assertEqual(country_picker('')['selected'], '')
        # GoogleBooks ignored anything but one country, so these stay automatic
        self.assertEqual(country_picker('SK CZ')['selected'], '')
        self.assertEqual(country_picker('XX')['selected'], '')

    def test_magazine_language_picker(self):
        picker = magazine_language_picker('SK')
        self.assertEqual(picker['selected'], 'sk')
        self.assertIsNone(picker['other'])
        self.assertEqual(len(picker['languages']), len(BOOK_LANGUAGES))
        labels = [lang['label'].lower() for lang in picker['languages']]
        self.assertEqual(labels, sorted(labels))

    def test_magazine_language_keeps_unknown_value(self):
        # a value the list doesn't have stays selected, so saving doesn't change it
        picker = magazine_language_picker('sk cz de en')
        self.assertEqual(picker['selected'], 'sk cz de en')
        self.assertEqual(picker['other'], 'sk cz de en')
        self.assertEqual(magazine_language_picker('')['other'], '')

    def test_anna_automatic(self):
        # empty means automatic, from the import languages in their order
        self.assertEqual(anna_search_languages('', 'sk, slo, Slovak, cs, cze, Czech, Unknown'), 'SK, CS')
        self.assertEqual(anna_search_languages(' ', 'cs, sk'), 'CS, SK')
        # a language Anna's Archive doesn't have searches all languages, it isn't dropped
        self.assertEqual(anna_search_languages('', 'cy, de'), 'ANY')
        self.assertEqual(anna_search_languages('', 'da, dan, Danish, en, eng, English'), 'ANY')
        self.assertEqual(anna_search_languages('', 'Welsh, Unknown'), 'ANY')
        # import languages that don't limit the language
        self.assertEqual(anna_search_languages('', 'All, sk'), 'ANY')
        self.assertEqual(anna_search_languages('', ''), 'ANY')

    def test_anna_override(self):
        # anything entered replaces the import languages
        self.assertEqual(anna_search_languages('DE', 'sk, cs'), 'DE')
        self.assertEqual(anna_search_languages('ANY', 'sk, cs'), 'ANY')

    def test_zlib_automatic(self):
        self.assertEqual(zlib_search_languages('', 'sk, slo, Slovak, cs, cze, Czech, Unknown'), 'slovak, czech')
        self.assertEqual(zlib_search_languages('', 'Unknown'), 'ANY')
        self.assertEqual(zlib_search_languages('', 'all'), 'ANY')

    def test_magazines_search_all_languages(self):
        # magazines and comics have their own language, automatic doesn't limit them to the import languages
        for searchtype in ('mag', 'comic'):
            self.assertEqual(anna_search_languages('', 'en, eng, English', searchtype), 'ANY')
            self.assertEqual(zlib_search_languages('', 'en, eng, English', searchtype), 'ANY')
        # books still search the import languages
        self.assertEqual(anna_search_languages('', 'en, eng, English', 'book'), 'EN')
        self.assertEqual(zlib_search_languages('', 'en, eng, English', 'book'), 'english')
        # an entered value is used for magazines too
        self.assertEqual(anna_search_languages('DE', 'en', 'mag'), 'DE')
        self.assertEqual(zlib_search_languages('german', 'en', 'mag'), 'german')

    def test_zlib_override(self):
        self.assertEqual(zlib_search_languages('english', 'sk, cs'), 'english')
        self.assertEqual(zlib_search_languages('ANY', 'sk, cs'), 'ANY')
