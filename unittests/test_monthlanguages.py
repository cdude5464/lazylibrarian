#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test the built-in month names in monthlanguages.py

import unittest

from lazylibrarian.common import validate_monthtable
from lazylibrarian.formatter import sort_definite, surname_first, unaccented, word_key
from lazylibrarian.monthlanguages import (
    LANGUAGE_WORDS,
    MONTH_LANGUAGES,
    SEASON_NAMES,
    month_language_picker,
)

ENGLISH_TABLE = [
    ['en_GB.UTF-8', 'en_GB.UTF-8'],
    ['January', 'Jan'], ['February', 'Feb'], ['March', 'Mar'], ['April', 'Apr'],
    ['May', 'May'], ['June', 'Jun'], ['July', 'Jul'], ['August', 'Aug'],
    ['September', 'Sep'], ['October', 'Oct'], ['November', 'Nov'], ['December', 'Dec'],
]


def add_language(table, lang):
    """ What switching a language on in initMonthLanguagePicker() in config_functions.js does to the month fields """
    table = [list(row) for row in table]
    table[0] += [lang['locale'], lang['locale']]
    for month, names in enumerate(lang['months'], start=1):
        table[month] += names
    return table


def remove_language(table, locale):
    """ What switching a language off does to the month fields """
    keep = [idx for idx, item in enumerate(table[0]) if item.lower() != locale.lower()]
    return [[row[idx] for idx in keep] for row in table]


def selected(picker):
    return [lang['locale'] for lang in picker if lang['selected']]


class MonthLanguagesTest(unittest.TestCase):

    def test_locales_are_unique(self):
        locales = [locale.lower() for locale, _, _ in MONTH_LANGUAGES]
        self.assertEqual(len(locales), len(set(locales)))

    def test_twelve_months(self):
        for locale, _, months in MONTH_LANGUAGES:
            self.assertEqual(len(months), 12, locale)
            for long, short in months:
                self.assertTrue(long and short, locale)
                # the config page keeps each month as a comma separated list
                self.assertNotIn(',', long + short, locale)

    def test_default_table_is_builtin_english(self):
        english = next(months for locale, _, months in MONTH_LANGUAGES if locale == 'en_GB.UTF-8')
        self.assertEqual([list(pair) for pair in english], ENGLISH_TABLE[1:])

    def test_picker_all_languages(self):
        picker = month_language_picker(ENGLISH_TABLE)
        self.assertEqual(len(picker), len(MONTH_LANGUAGES))
        self.assertEqual(selected(picker), ['en_GB.UTF-8'])
        self.assertEqual(picker[0]['locale'], 'en_GB.UTF-8')

    def test_picker_table_order(self):
        slovak = next(lang for lang in month_language_picker(ENGLISH_TABLE) if lang['locale'] == 'sk_SK.UTF-8')
        table = add_language(ENGLISH_TABLE, slovak)
        table = remove_language(table, 'en_GB.UTF-8')
        english = next(lang for lang in month_language_picker(table) if lang['locale'] == 'en_GB.UTF-8')
        table = add_language(table, english)
        picker = month_language_picker(table)
        self.assertEqual(selected(picker), ['sk_SK.UTF-8', 'en_GB.UTF-8'])
        self.assertEqual(len(picker), len(MONTH_LANGUAGES))
        self.assertEqual(picker[1]['months'], ENGLISH_TABLE[1:])

    def test_picker_uses_table_names(self):
        # hand edited names and languages not built in keep their names from the table
        table = [list(row) for row in ENGLISH_TABLE]
        table[0] += ['xx_XX', 'xx_XX']
        for month in range(1, 13):
            table[month] += [f'long{month}', f'short{month}']
        table[5][0] = 'Maytime'
        picker = month_language_picker(table)
        self.assertEqual(selected(picker), ['en_GB.UTF-8', 'xx_XX'])
        self.assertEqual(picker[0]['months'][4], ['Maytime', 'May'])
        self.assertEqual(picker[1]['label'], 'xx_XX')
        self.assertEqual(picker[1]['months'][11], ['long12', 'short12'])
        self.assertEqual(len(picker), len(MONTH_LANGUAGES) + 1)

    def test_picker_shown(self):
        picker = month_language_picker(ENGLISH_TABLE)
        self.assertEqual([lang['locale'] for lang in picker if lang['shown']], ['en_GB.UTF-8'])
        # browser languages are shown after the table languages, before the hidden ones
        picker = month_language_picker(ENGLISH_TABLE, ['sk', 'cs_cz', 'en_us'])
        shown = [lang['locale'] for lang in picker if lang['shown']]
        self.assertEqual(shown[0], 'en_GB.UTF-8')
        self.assertEqual(sorted(shown[1:]), ['cs_CZ.UTF-8', 'sk_SK.UTF-8'])
        self.assertEqual([lang['locale'] for lang in picker[:3]], shown)
        self.assertFalse(any(lang['shown'] for lang in picker[3:]))

    def test_language_words(self):
        self.assertEqual(set(LANGUAGE_WORDS), {locale for locale, _, _ in MONTH_LANGUAGES})
        for locale, lists in LANGUAGE_WORDS.items():
            self.assertEqual(set(lists), {'issue_nouns', 'volume_nouns', 'mag_nouns', 'name_postfix', 'name_definite'})
            for field, words in lists.items():
                self.assertEqual(len(words), len(set(words)), f'{locale} {field}')
                for word in words:
                    # stored the way they are compared, so one form matches titles with and without accents
                    self.assertEqual(word, word_key(word), f'{locale} {field}')
                    self.assertNotIn(',', word, f'{locale} {field}')

    def test_words_match_without_accents(self):
        self.assertEqual(word_key('Číslo'), 'cislo')
        self.assertEqual(word_key('ROČ.'), 'roc')
        postfixes = LANGUAGE_WORDS['fr_FR.UTF-8']['name_postfix']
        self.assertEqual(surname_first('Alexandre Dumas Père', postfixes), 'Dumas Père, Alexandre')
        self.assertEqual(surname_first('Ján Novák, Ph.D.', LANGUAGE_WORDS['sk_SK.UTF-8']['name_postfix']),
                         'Novák Ph.D., Ján')
        articles = LANGUAGE_WORDS['de_DE.UTF-8']['name_definite']
        self.assertEqual(sort_definite('Die Verwandlung', articles), 'Verwandlung, Die')

    def test_season_names(self):
        self.assertEqual(set(SEASON_NAMES), {locale for locale, _, _ in MONTH_LANGUAGES})
        month_names = {unaccented(name).lower().strip('.')
                       for _, _, months in MONTH_LANGUAGES for pair in months for name in pair}
        for locale, seasons in SEASON_NAMES.items():
            self.assertEqual(set(seasons.values()) - {1, 4, 7, 10, 12}, set(), locale)
            for name in seasons:
                # formatter.month2num matches them without accents and lowercase
                self.assertEqual(name, unaccented(name).lower(), locale)
                self.assertNotIn(',', name, locale)
                self.assertNotIn(':', name, locale)
                # month names are matched first, a season with the name of a month would never be found
                self.assertNotIn(name, month_names, locale)
        for locale, seasons in SEASON_NAMES.items():
            for other, other_seasons in SEASON_NAMES.items():
                for name in set(seasons) & set(other_seasons):
                    self.assertEqual(seasons[name], other_seasons[name], f'{name} in {locale} and {other}')

    def test_default_seasons_are_english(self):
        # startup.build_monthtable() starts seasons.json with these
        self.assertEqual(SEASON_NAMES['en_GB.UTF-8'], {"winter": 1, "spring": 4, "summer": 7, "fall": 10,
                                                       "autumn": 10, "christmas": 12})

    def test_picker_seasons(self):
        table = [list(row) for row in ENGLISH_TABLE]
        table[0] += ['xx_XX', 'xx_XX']
        for month in range(1, 13):
            table[month] += [f'long{month}', f'short{month}']
        picker = {lang['locale']: lang for lang in month_language_picker(table)}
        self.assertEqual(picker['en_GB.UTF-8']['seasons']['autumn'], 10)
        self.assertEqual(picker['sk_SK.UTF-8']['seasons']['jesen'], 10)
        self.assertEqual(picker['xx_XX']['seasons'], {})

    def test_picker_empty_table(self):
        picker = month_language_picker([])
        self.assertEqual(len(picker), len(MONTH_LANGUAGES))
        self.assertEqual(selected(picker), [])

    def test_all_languages_are_valid(self):
        table = ENGLISH_TABLE
        for lang in month_language_picker(table):
            if not lang['selected']:
                table = add_language(table, lang)
                self.assertTrue(validate_monthtable(table), lang['locale'])
        self.assertEqual(len(selected(month_language_picker(table))), len(MONTH_LANGUAGES))
        for locale, _, _ in MONTH_LANGUAGES[1:]:
            table = remove_language(table, locale)
            self.assertTrue(validate_monthtable(table), locale)


if __name__ == '__main__':
    unittest.main()
