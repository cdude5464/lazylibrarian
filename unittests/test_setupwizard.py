#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test the country presets and the saving of the setup wizard in setupwizard.py

import copy
import os
from unittest import mock

import lazylibrarian
from lazylibrarian import i18n, setupwizard
from lazylibrarian.filesystem import DIRS
from lazylibrarian.formatter import ImportPrefs
from lazylibrarian.setupwizard import (
    COUNTRIES,
    WIZARD_KEYS,
    apply,
    folder_status,
    guess_country,
    presets_for,
    should_autoopen,
)
from unittests.unittesthelpers import LLTestCaseWithConfigandDIRS

ENGLISH_ONLY = [['en_GB.UTF-8', 'en_GB.UTF-8']] + [[f'm{m}', f'm{m}'] for m in range(1, 13)]


class SetupWizardTest(LLTestCaseWithConfigandDIRS):
    def setUp(self):
        super().setUp()
        self.saved_months = lazylibrarian.MONTHNAMES
        lazylibrarian.MONTHNAMES = [copy.deepcopy(ENGLISH_ONLY), []]
        # the config is shared by the whole class: put every value back, without the onchange callbacks
        self.saved_values = {key: copy.deepcopy(item.value) for key, item in self.config.config.items()}
        self.saved_langs = list(ImportPrefs.LANG_LIST)
        patcher = mock.patch.object(self.config, 'save_config_and_backup_old')
        self.save = patcher.start()
        self.addCleanup(patcher.stop)
        months = mock.patch('lazylibrarian.common.save_monthtable', return_value=True)
        self.save_months = months.start()
        self.addCleanup(months.stop)

    def tearDown(self):
        lazylibrarian.MONTHNAMES = self.saved_months
        for key, value in self.saved_values.items():
            self.config.config[key].value = value
        ImportPrefs.LANG_LIST = self.saved_langs
        super().tearDown()

    def rows(self, country, langs=()):
        return {r['key']: r for s in presets_for(country, langs, self.config) for r in s['rows']}

    # guessing the country

    def test_guess_country(self):
        self.assertEqual(guess_country(['sk-SK', 'en']), 'SK')
        self.assertEqual(guess_country(['sk']), 'SK')
        self.assertEqual(guess_country(['de-AT']), 'AT')
        self.assertEqual(guess_country(['de']), 'DE')
        self.assertEqual(guess_country(['en-US']), 'US')
        self.assertEqual(guess_country(['en']), 'GB')
        self.assertEqual(guess_country(['cs']), 'CZ')
        self.assertEqual(guess_country(['et']), 'EE')

    def test_guess_country_edge_cases(self):
        for tags in ([], [''], ['x-klingon'], ['zh-Hant-TW'], ['pt-BR'], None):
            self.assertIn(guess_country(tags), COUNTRIES)
        self.assertEqual(guess_country(['SK-sk']), 'SK')
        self.assertEqual(guess_country(['x-klingon', 'pl']), 'PL')
        self.assertEqual(guess_country(['*']), '_generic')

    def test_generic_ignores_private_tags(self):
        r = self.rows('_generic', ['x-klingon', 'i-default'])
        self.assertTrue(r['IMP_PREFLANG']['proposed'].startswith('en'))
        self.assertNotIn('PREF_MAGLANG', r)

    # presets

    def test_sk_preset(self):
        r = self.rows('SK')
        self.assertIs(r['DBK_API']['proposed'], True)
        self.assertEqual(r['DATE_LANG']['proposed'], 'sk_SK.UTF-8')
        self.assertEqual(r['DATE_FORMAT']['proposed'], '$d.$m.$Y')
        self.assertEqual(r['GB_COUNTRY']['proposed'], 'SK')
        self.assertTrue(r['IMP_PREFLANG']['proposed'].startswith('sk, slo, slk, Slovak, cs'))
        self.assertIn('en', r['IMP_PREFLANG']['proposed'].split(', '))
        self.assertEqual(r['MONTH_LANGUAGE']['proposed'], 'sk_SK.UTF-8')

    def test_gb_country_is_one_choice(self):
        row = self.rows('SK')['GB_COUNTRY']
        self.assertEqual(row['kind'], 'choice')
        values = [c['value'] for c in row['choices']]
        self.assertEqual(values[0], '')
        self.assertIn('SK', values)
        self.assertFalse(apply({'GB_COUNTRY': 'SK, CZ'}, self.config)['ok'])
        self.assertTrue(apply({'GB_COUNTRY': 'sk'}, self.config)['ok'])
        self.assertEqual(self.config['GB_COUNTRY'], 'SK')

    def test_langid_buttons(self):
        row = self.rows('SK')['LANGID_LANGUAGES']
        self.assertEqual(row['kind'], 'langs')
        self.assertIn('sk', row['proposed'].split(', '))
        self.assertIn('de', row['proposed'].split(', '))  # other languages stay, so their books are recognised
        self.assertTrue(all(len(b['codes']) == 1 for b in row['choices']))

    def test_selects_like_the_config_page(self):
        r = self.rows('SK')
        for key in ('DATE_FORMAT', 'AUTHOR_DATE_FORMAT', 'DATE_LANG', 'PREF_MAGLANG'):
            self.assertEqual(r[key]['kind'], 'choice', key)
            values = [c['value'] for c in r[key]['choices']]
            self.assertIn(r[key]['proposed'], values, key)
            self.assertIn(r[key]['current'], values, key)

    def test_at_inherits_german(self):
        r = self.rows('AT')
        self.assertIs(r['DNB_API']['proposed'], True)
        self.assertEqual(r['DATE_LANG']['proposed'], 'de_DE.UTF-8')  # the month table has German as de_DE
        self.assertEqual(r['MONTH_LANGUAGE']['proposed'], 'de_DE.UTF-8')
        self.assertTrue(r['IMP_PREFLANG']['proposed'].startswith('de, ger, deu, German'))

    def test_us_date_order(self):
        self.assertEqual(self.rows('US')['DATE_FORMAT']['proposed'], '$m/$d/$Y')

    def test_generic_follows_browser_and_keeps_dates(self):
        r = self.rows('_generic', ['pt-BR'])
        self.assertTrue(r['IMP_PREFLANG']['proposed'].startswith('pt, por'))
        self.assertFalse(r['DATE_FORMAT']['changed'])
        self.assertEqual(r['UI_LANGUAGE']['proposed'], 'auto')

    def test_picked_ui_language_wins(self):
        lang = next((code for code in i18n.available_languages() if code != 'sk'), 'en')
        rows = {r['key']: r for s in presets_for('SK', (), self.config, ui_lang=lang) for r in s['rows']}
        self.assertEqual(rows['UI_LANGUAGE']['proposed'], lang)

    def test_recommended_search_providers(self):
        for code in COUNTRIES:
            r = self.rows(code)
            self.assertIs(r['ANNA']['proposed'], True, code)
            self.assertIs(r['BOK']['proposed'], False, code)  # needs a login, never proposed on
            self.assertEqual(r['WEBSHARE']['proposed'], code in ('SK', 'CZ'), code)

    def test_libgen_switches_on_the_gen_entry(self):
        self.config.ensure_libgen_preset()
        entry = next(e for e in self.config.get_array('GEN') if 'libgen' in e.get_str('HOST'))
        self.assertFalse(entry.get_bool('ENABLED'))
        row = self.rows('SK')['LIBGEN']
        self.assertIs(row['proposed'], True)
        self.assertIs(row['current'], False)
        res = apply({'LIBGEN': True}, self.config, finish=False)
        self.assertTrue(res['ok'], res)
        self.assertIn('LIBGEN', res['changed'])
        self.assertTrue(entry.get_bool('ENABLED'))

    def test_nouns_merged_without_duplicates(self):
        self.config.set_csv('ISSUE_NOUNS', 'issue, iss, no, nr, #, n, cislo')
        proposed = self.rows('CZ')['ISSUE_NOUNS']['proposed'].split(', ')
        self.assertEqual(proposed[:6], ['issue', 'iss', 'no', 'nr', '#', 'n'])
        self.assertEqual(proposed.count('cislo'), 1)

    def test_nouns_accented_word_not_added_again(self):
        self.config.set_csv('ISSUE_NOUNS', 'issue, číslo')
        self.assertNotIn('cislo', self.rows('CZ')['ISSUE_NOUNS']['proposed'].split(', '))

    def test_other_country_languages_replaced(self):
        self.config.set_csv('IMP_PREFLANG', 'de, ger, deu, German, en, eng, ja, Unknown')
        r = self.rows('SK')['IMP_PREFLANG']
        codes = r['proposed'].split(', ')
        self.assertNotIn('de', codes)
        self.assertNotIn('German', codes)
        self.assertEqual(codes[-2:], ['ja', 'Unknown'])  # the user's own stay, after the country's
        self.assertEqual(r['kind'], 'langs')
        self.assertEqual(r['choices'][0]['label'], i18n.gettext('Slovak'))

    def test_other_language_words_replaced(self):
        self.config.set_csv('ISSUE_NOUNS', 'issue, iss, no, nr, #, n, ausgabe, heft, mywordx')
        words = self.rows('SK')['ISSUE_NOUNS']['proposed'].split(', ')
        self.assertNotIn('ausgabe', words)
        self.assertIn('nr', words)  # English and the default stay
        self.assertIn('mywordx', words)  # a word no language has is the user's own
        self.assertIn('cislo', words)

    def test_preflang_keeps_other_languages(self):
        self.config.set_csv('IMP_PREFLANG', 'en, eng, ja')
        self.assertIn('ja', self.rows('SK')['IMP_PREFLANG']['proposed'].split(', '))

    def test_ui_language_only_if_translated(self):
        self.assertIn(self.rows('SK')['UI_LANGUAGE']['proposed'], ['auto'] + i18n.available_languages())
        self.assertEqual(self.rows('_generic')['UI_LANGUAGE']['proposed'], 'auto')

    def test_changed_flag(self):
        for row in self.rows('SK').values():
            self.assertEqual(row['changed'], row['proposed'] != row['current'])

    def test_wizard_keys_cover_every_country(self):
        for code in COUNTRIES:
            self.assertLessEqual(set(self.rows(code)), WIZARD_KEYS)
        self.assertNotIn('HTTP_PASS', WIZARD_KEYS)
        self.assertNotIn('HTTP_USER', WIZARD_KEYS)

    # saving

    def test_apply_sets_values_and_done(self):
        self.config.set_bool('SETUP_WIZARD_DONE', False)
        res = apply({'DATE_LANG': 'sk_SK.UTF-8', 'DBK_API': True}, self.config)
        self.assertTrue(res['ok'])
        self.assertEqual(self.config['DATE_LANG'], 'sk_SK.UTF-8')
        self.assertTrue(self.config.get_bool('DBK_API'))
        self.assertTrue(self.config.get_bool('SETUP_WIZARD_DONE'))
        self.save.assert_called_once()

    def test_apply_rejects_unknown_key_saves_nothing(self):
        before = self.config['DATE_LANG']
        res = apply({'DATE_LANG': 'sk_SK.UTF-8', 'HTTP_PASS': 'x'}, self.config)
        self.assertFalse(res['ok'])
        self.assertIn('HTTP_PASS', res['error'])
        self.assertEqual(self.config['DATE_LANG'], before)
        self.save.assert_not_called()

    def test_apply_bad_value_saves_nothing(self):
        before = self.config['DATE_LANG']
        res = apply({'DATE_LANG': 'sk_SK.UTF-8', 'MAG_TAB': 'notabool'}, self.config)
        self.assertFalse(res['ok'])
        self.assertEqual(self.config['DATE_LANG'], before)
        self.save.assert_not_called()
        self.assertFalse(apply({'HTTP_LOOK': 'nope'}, self.config)['ok'])
        self.assertFalse(apply({'UI_LANGUAGE': 'xx'}, self.config)['ok'])

    def test_apply_bad_csv_saves_nothing(self):
        before = self.config['DATE_LANG']
        res = apply({'DATE_LANG': 'sk_SK.UTF-8', 'IMP_PREFLANG': 'sk, cs,'}, self.config)
        self.assertFalse(res['ok'])
        self.assertIn('IMP_PREFLANG', res['error'])
        self.assertEqual(self.config['DATE_LANG'], before)
        self.save.assert_not_called()

    def test_apply_records_telemetry_only_when_saved(self):
        with mock.patch('lazylibrarian.setupwizard.TELEMETRY') as telemetry:
            self.assertFalse(apply({'HTTP_PASS': 'x'}, self.config)['ok'])
            telemetry.record_usage_data.assert_not_called()
            self.assertTrue(apply({'DATE_FORMAT': '$d.$m.$Y'}, self.config)['ok'])
            telemetry.record_usage_data.assert_called_once_with('SetupWizard')

    def test_apply_without_finish(self):
        self.config.set_bool('SETUP_WIZARD_DONE', False)
        self.assertTrue(apply({'DATE_FORMAT': '$d.$m.$Y'}, self.config, finish=False)['ok'])
        self.assertFalse(self.config.get_bool('SETUP_WIZARD_DONE'))

    def test_reload_flag(self):
        self.config.set_str('HTTP_LOOK', 'bookstrap')
        self.config.set_bool('MAG_TAB', True)
        self.assertFalse(apply({'DATE_FORMAT': '$d.$m.$Y'}, self.config)['reload'])
        self.assertTrue(apply({'HTTP_LOOK': 'modern'}, self.config)['reload'])
        self.assertTrue(apply({'MAG_TAB': False}, self.config)['reload'])

    def test_month_language_added(self):
        apply({'MONTH_LANGUAGE': 'sk_SK.UTF-8'}, self.config)
        table = self.save_months.call_args[0][0]
        self.assertEqual(table[0].count('sk_SK.UTF-8'), 2)
        self.assertEqual(len(table), 13)
        self.assertEqual(table[1][-2:], ['január', 'jan'])
        self.assertEqual(lazylibrarian.MONTHNAMES[0][0], ENGLISH_ONLY[0])  # not changed in place

    def test_month_language_not_added_twice(self):
        lazylibrarian.MONTHNAMES[0][0] += ['sk_SK.UTF-8', 'sk_SK.UTF-8']
        apply({'MONTH_LANGUAGE': 'sk_SK.UTF-8'}, self.config)
        self.save_months.assert_not_called()

    def test_folder_status(self):
        self.assertEqual(folder_status(''), 'empty')
        self.assertEqual(folder_status(os.path.join(DIRS.DATADIR, 'nope-xyz')), 'missing')
        self.assertEqual(folder_status(DIRS.DATADIR), 'ok')

    def test_should_autoopen_existing_install(self):
        self.config.set_bool('SETUP_WIZARD_DONE', False)
        self.config.set_str('EBOOK_DIR', '/books')
        self.assertFalse(should_autoopen(self.config))
        self.config.set_str('EBOOK_DIR', '')
        self.config.set_str('AUDIO_DIR', '/audio')
        self.assertFalse(should_autoopen(self.config))
        self.config.set_str('AUDIO_DIR', '')
        self.assertTrue(should_autoopen(self.config))
        setupwizard.dismiss(self.config)
        self.assertFalse(should_autoopen(self.config))
