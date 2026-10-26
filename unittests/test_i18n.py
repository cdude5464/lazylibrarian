#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test functions in i18n.py

import os
import tempfile
import unittest

from lazylibrarian import i18n

SAMPLE_PO = r'''# Test catalog
msgid ""
msgstr ""
"Language: sk\n"
"Plural-Forms: nplurals=3; plural=((n==1) ? 0 : (n>=2 && n<=4) ? 1 : 2);\n"

#: base.html:1
msgid "Authors"
msgstr "Autori"

msgid "Line one "
"and two"
msgstr "Riadok jeden "
"a dva"

msgid "Quote \"me\""
msgstr "Cituj \"ma\""

#, fuzzy
msgid "Fuzzy"
msgstr "Neisté"

msgid "Untranslated"
msgstr ""

msgctxt "verb"
msgid "Search"
msgstr "Hľadať"

#, python-format
msgid "%(count)s author"
msgid_plural "%(count)s authors"
msgstr[0] "%(count)s autor"
msgstr[1] "%(count)s autori"
msgstr[2] "%(count)s autorov"

msgid "Half done"
msgid_plural "Half done plural"
msgstr[0] "Napoly"
msgstr[1] ""
msgstr[2] ""
'''


TEMPLATE_POT = r"""msgid ""
msgstr ""

msgid "Authors"
msgstr ""

msgid "Fuzzy"
msgstr ""

msgctxt "verb"
msgid "Search"
msgstr ""

msgid "Untranslated"
msgstr ""

msgid "%(count)s author"
msgid_plural "%(count)s authors"
msgstr[0] ""
msgstr[1] ""
"""


class I18nTest(unittest.TestCase):

    def setUp(self):
        fd, self.po_file = tempfile.mkstemp(suffix='.po')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(SAMPLE_PO)
        self.trans = i18n.POTranslations(self.po_file)

    def tearDown(self):
        os.remove(self.po_file)
        i18n.set_language(i18n.DEFAULT_LANGUAGE)

    def test_gettext(self):
        self.assertEqual(self.trans.gettext('Authors'), 'Autori')
        self.assertEqual(self.trans.gettext('Line one and two'), 'Riadok jeden a dva')
        self.assertEqual(self.trans.gettext('Quote "me"'), 'Cituj "ma"')
        self.assertEqual(self.trans.gettext('Untranslated'), 'Untranslated')
        self.assertEqual(self.trans.gettext('Not in catalog'), 'Not in catalog')

    def test_mark_only(self):
        # N_() returns the English text, gettext() translates it later
        self.assertEqual(i18n.N_('Authors'), 'Authors')

    def test_fuzzy_is_ignored(self):
        self.assertEqual(self.trans.gettext('Fuzzy'), 'Fuzzy')

    def test_context(self):
        self.assertEqual(self.trans.pgettext('verb', 'Search'), 'Hľadať')
        self.assertEqual(self.trans.gettext('Search'), 'Search')

    def test_plurals(self):
        expected = {1: 'autor', 2: 'autori', 4: 'autori', 5: 'autorov', 0: 'autorov', 22: 'autorov'}
        for n, word in expected.items():
            msg = self.trans.ngettext('%(count)s author', '%(count)s authors', n) % {'count': n}
            self.assertEqual(msg, f'{n} {word}')
        self.assertEqual(self.trans.nplurals, 3)

    def test_partial_plurals_fall_back(self):
        self.assertEqual(self.trans.ngettext('Half done', 'Half done plural', 1), 'Napoly')
        self.assertEqual(self.trans.ngettext('Half done', 'Half done plural', 5), 'Half done plural')
        self.assertIsNone(self.trans.plural_forms('Half done'))
        self.assertEqual(self.trans.plural_forms('%(count)s author'),
                         ['%(count)s autor', '%(count)s autori', '%(count)s autorov'])

    def test_match_accept_language(self):
        langs = ['en', 'sk', 'pt_BR']
        data = [
            ('', 'en'),
            ('sk', 'sk'),
            ('sk-SK,sk;q=0.9,en;q=0.8', 'sk'),
            ('de-DE,de;q=0.9,sk;q=0.5', 'sk'),
            ('en-US,en;q=0.9,sk;q=0.8', 'en'),
            ('fr;q=1.0,sk;q=0', 'en'),
            ('pt-BR', 'pt_BR'),
            ('sk;q=0.5,en;q=0.9', 'en'),
            ('garbage;q=abc', 'en'),
        ]
        for header, expected in data:
            self.assertEqual(i18n.match_accept_language(header, langs), expected, header)

    def test_translation_invite(self):
        langs = ['en', 'sk']
        progress = {'sk': 100}
        original = i18n.translation_progress
        i18n.translation_progress = lambda lang: progress.get(lang, 100)
        try:
            data = [
                ('', 'auto', 'de-DE,de;q=0.9,en;q=0.8', ('de', 0)),  # German wanted, no translation
                ('', '', 'fr', ('fr', 0)),  # empty setting also follows the browser
                ('', 'auto', 'sk-SK,sk;q=0.9', ('', 100)),  # complete translation
                ('', 'auto', 'en-US,en;q=0.9,de;q=0.5', ('', 100)),  # never ask in English
                ('', 'en', 'de-DE', ('', 100)),
                ('', 'auto', '', ('', 100)),
                ('', 'auto', '*', ('', 100)),
                ('', 'sk', 'en', ('', 100)),  # set language, complete
                ('en', 'sk', 'de', ('', 100)),  # the user's own choice wins
                ('auto', 'auto', 'de', ('de', 0)),
            ]
            for user_lang, setting, header, expected in data:
                self.assertEqual(i18n.translation_invite(user_lang, setting, header, langs), expected,
                                 (user_lang, setting, header))
            progress['sk'] = 85
            self.assertEqual(i18n.translation_invite('', 'sk', 'en', langs), ('sk', 85))  # set, partly done
            self.assertEqual(i18n.translation_invite('', 'auto', 'sk-SK', langs), ('sk', 85))
            self.assertEqual(i18n.translation_invite('sk', 'en', 'en', langs), ('sk', 85))
        finally:
            i18n.translation_progress = original

    def test_translation_progress(self):
        fd, pot = tempfile.mkstemp(suffix='.pot')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(TEMPLATE_POT)
        template = i18n.POTranslations(pot).msgids
        os.remove(pot)
        self.assertEqual(len(template), 5)
        # Authors, Search (with context) and the plural are translated, Fuzzy and Untranslated are not
        self.assertEqual(template & self.trans.translated, {'Authors', 'verb\x04Search', '%(count)s author'})
        self.assertNotIn('Half done', self.trans.translated)  # plural with missing forms
        self.assertEqual(i18n.translation_progress('en'), 100)

    def test_parse_accept_language(self):
        self.assertEqual(i18n.parse_accept_language('de;q=0.5,sk-SK,en;q=0.8,fr;q=0'), ['sk_sk', 'en', 'de'])
        self.assertEqual(i18n.parse_accept_language(''), [])

    def test_default_is_automatic(self):
        from lazylibrarian.configdefs import BASE_DEFAULTS
        item = next(i for i in BASE_DEFAULTS if i.key == 'UI_LANGUAGE')
        self.assertEqual(item.default, i18n.AUTO)
        self.assertEqual(i18n.resolve_language(item.default, 'sk-SK,sk;q=0.9'), 'sk')
        self.assertEqual(i18n.resolve_language(item.default, 'zh-CN'), 'en')

    def test_resolve_language(self):
        self.assertEqual(i18n.resolve_language('en'), 'en')
        self.assertEqual(i18n.resolve_language('xx'), 'en')
        self.assertEqual(i18n.resolve_language('auto', 'zz'), 'en')
        self.assertIn('sk', i18n.available_languages())
        self.assertEqual(i18n.resolve_language('sk'), 'sk')
        self.assertEqual(i18n.resolve_language('auto', 'sk-SK,en;q=0.5'), 'sk')

    def test_resolve_browser_languages(self):
        # navigator.languages from the browser cookie wins over the Accept-Language header
        self.assertEqual(i18n.resolve_language('auto', 'en-US,en;q=0.5', 'sk-SK,sk'), 'sk')
        self.assertEqual(i18n.resolve_language('auto', '', 'sk'), 'sk')
        self.assertEqual(i18n.resolve_language('auto', 'sk', 'en-US'), 'en')
        # nothing we have a translation for in the cookie, so use the header
        self.assertEqual(i18n.resolve_language('auto', 'sk-SK', 'zh-CN,ru'), 'sk')
        self.assertEqual(i18n.resolve_language('auto', '', ''), 'en')
        # an explicit language setting ignores the browser
        self.assertEqual(i18n.resolve_language('en', 'sk', 'sk'), 'en')

    def test_thread_language(self):
        i18n.set_language('en')
        self.assertEqual(i18n.gettext('Authors'), 'Authors')
        self.assertEqual(i18n.plural_expression(), 'n != 1')
        i18n.set_language('sk')
        self.assertEqual(i18n.get_language(), 'sk')
        self.assertEqual(i18n.gettext('Authors'), 'Autori')
        self.assertIn('n>=2', i18n.plural_expression())

    def test_status_label(self):
        i18n.set_language('sk')
        # compare with the catalog, so the test doesn't depend on the exact wording on Weblate
        self.assertEqual(i18n.status_label('Wanted'), i18n.gettext('Wanted'))
        self.assertNotEqual(i18n.status_label('Wanted'), 'Wanted')
        self.assertEqual(i18n.status_label('SomethingNew'), 'SomethingNew')
        i18n.set_language('en')
        self.assertEqual(i18n.status_label('Wanted'), 'Wanted')

    def test_js_helpers(self):
        i18n.set_language('en')
        self.assertEqual(i18n.js_string('a "b" </script>'), '"a \\"b\\" <\\/script>"')
        self.assertEqual(i18n.ngettext_js('one', 'many'), '{"f": ["one", "many"], "t": false}')


if __name__ == '__main__':
    unittest.main()
