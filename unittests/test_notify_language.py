#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test the choice of language for notifications in i18n.py

import unittest

from lazylibrarian import i18n


class NotifyLanguageTest(unittest.TestCase):
    def setUp(self):
        self.saved = i18n._last_ui_language
        i18n._last_ui_language = ''
        self.lang = next((lang for lang in i18n.available_languages() if lang != i18n.DEFAULT_LANGUAGE), '')
        if not self.lang:
            self.skipTest('no translations available')

    def tearDown(self):
        i18n._last_ui_language = self.saved

    def test_setting_wins(self):
        self.assertEqual(i18n.resolve_notify_language(self.lang, i18n.AUTO, 'en'), self.lang)

    def test_fixed_ui_language_wins_over_last_shown(self):
        self.assertEqual(i18n.resolve_notify_language('', self.lang, 'en'), self.lang)

    def test_auto_follows_last_shown(self):
        self.assertEqual(i18n.resolve_notify_language('', i18n.AUTO, self.lang), self.lang)

    def test_auto_without_last_shown_is_english(self):
        self.assertEqual(i18n.resolve_notify_language('', i18n.AUTO, ''), i18n.DEFAULT_LANGUAGE)

    def test_unknown_last_shown_is_english(self):
        self.assertEqual(i18n.resolve_notify_language('', i18n.AUTO, 'xx_YY'), i18n.DEFAULT_LANGUAGE)

    def test_remember_ui_language(self):
        i18n.remember_ui_language(self.lang)
        self.assertEqual(i18n.last_ui_language(), self.lang)
        i18n.remember_ui_language('xx_YY')
        self.assertEqual(i18n.last_ui_language(), self.lang)


if __name__ == '__main__':
    unittest.main()
