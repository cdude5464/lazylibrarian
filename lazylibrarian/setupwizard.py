#  This file is part of Lazylibrarian.
#
# Purpose:
#    The setup wizard: typical settings for the user's country, guessed from the browser languages.
#    The wizard shows each proposal next to the current value and saves only the rows the user ticks.
#    Book language codes, month names and magazine words come from booklanguages.py and
#    monthlanguages.py, so a language added there is available here too.
# SPDX-License-Identifier: GPL-3.0-or-later

import contextlib
import copy
import locale
import logging
import os

import lazylibrarian
from lazylibrarian import i18n
from lazylibrarian.booklanguages import BOOK_LANGUAGES, GB_COUNTRIES
from lazylibrarian.formatter import unaccented
from lazylibrarian.i18n import N_
from lazylibrarian.monthlanguages import LANGUAGE_WORDS, MONTH_LANGUAGES
from lazylibrarian.sources.registry import recommended_providers, wizard_providers
from lazylibrarian.telemetry import TELEMETRY

GENERIC = '_generic'
MONTH_LANGUAGE = 'MONTH_LANGUAGE'  # pseudo key, adds a built-in language to the month name table
LIBGEN = 'LIBGEN'  # pseudo key, switches on the LibGen entry of the generic (GEN) providers

# Per language: date order, series number wording, other languages readers of it usually want,
# and the switch of a metadata source for books in it.
LANGUAGES = {
    'sk': {'date': '$d.$m.$Y', 'sernum': 'Kniha č.$SerNum -$$', 'also': ['cs'], 'source': 'DBK_API'},
    'cs': {'date': '$d.$m.$Y', 'sernum': 'Kniha č.$SerNum -$$', 'also': ['sk'], 'source': 'DBK_API'},
    'de': {'date': '$d.$m.$Y', 'sernum': 'Band $SerNum -$$', 'source': 'DNB_API'},
    'pl': {'date': '$d.$m.$Y', 'sernum': 'Tom $SerNum -$$', 'source': 'BN_API'},
    'fr': {'date': '$d/$m/$Y', 'sernum': 'Tome $SerNum -$$'},
    'es': {'date': '$d/$m/$Y', 'sernum': 'Libro $SerNum -$$'},
    'it': {'date': '$d/$m/$Y', 'sernum': 'Libro $SerNum -$$'},
    'nl': {'date': '$d-$m-$Y', 'sernum': 'Deel $SerNum -$$'},
    'ru': {'date': '$d.$m.$Y', 'sernum': 'Книга $SerNum -$$'},
    'et': {'date': '$d.$m.$Y', 'sernum': 'Raamat $SerNum -$$'},
    'en': {'date': '$d/$m/$Y'},
}

# Country code: name, language and anything the country does differently from its language
COUNTRIES = {
    'SK': {'name': N_('Slovakia'), 'lang': 'sk', 'locale': 'sk_SK.UTF-8'},
    'CZ': {'name': N_('Czech Republic'), 'lang': 'cs', 'locale': 'cs_CZ.UTF-8'},
    'DE': {'name': N_('Germany'), 'lang': 'de', 'locale': 'de_DE.UTF-8'},
    'AT': {'name': N_('Austria'), 'lang': 'de', 'locale': 'de_AT.UTF-8'},
    'CH': {'name': N_('Switzerland'), 'lang': 'de', 'locale': 'de_CH.UTF-8'},
    'PL': {'name': N_('Poland'), 'lang': 'pl', 'locale': 'pl_PL.UTF-8'},
    'FR': {'name': N_('France'), 'lang': 'fr', 'locale': 'fr_FR.UTF-8'},
    'ES': {'name': N_('Spain'), 'lang': 'es', 'locale': 'es_ES.UTF-8'},
    'IT': {'name': N_('Italy'), 'lang': 'it', 'locale': 'it_IT.UTF-8'},
    'NL': {'name': N_('Netherlands'), 'lang': 'nl', 'locale': 'nl_NL.UTF-8'},
    'RU': {'name': N_('Russia'), 'lang': 'ru', 'locale': 'ru_RU.UTF-8'},
    'EE': {'name': N_('Estonia'), 'lang': 'et', 'locale': 'et_EE.UTF-8'},
    'GB': {'name': N_('United Kingdom'), 'lang': 'en', 'locale': 'en_GB.UTF-8', 'codes': ['en-GB']},
    'US': {'name': N_('United States'), 'lang': 'en', 'locale': 'en_US.UTF-8', 'date': '$m/$d/$Y',
           'codes': ['en-US']},
    GENERIC: {'name': N_('Other country'), 'lang': ''},
}

# The country of each language when the browser does not say
LANGUAGE_COUNTRY = {'sk': 'SK', 'cs': 'CZ', 'de': 'DE', 'pl': 'PL', 'fr': 'FR', 'es': 'ES', 'it': 'IT',
                    'nl': 'NL', 'ru': 'RU', 'et': 'EE', 'en': 'GB'}

BOOK_APIS = ['OpenLibrary', 'GoodReads', 'GoogleBooks', 'HardCover', 'DNB', 'BN', 'DBK', 'RanobeDB']
SOURCE_HELP = {
    'DBK_API': N_('Czech and Slovak book database (databazeknih.cz)'),
    'DNB_API': N_('German National Library (Deutsche Nationalbibliothek)'),
    'BN_API': N_('National Library of Poland (Biblioteka Narodowa)'),
}
# Providers the wizard can switch on: key, label, help. Hosts and logins are set on the Providers tab.
SEARCH_PROVIDERS = wizard_providers() + [
    ('ABB', N_('AudioBookBay'), N_('AudioBooks by torrent, needs a torrent client.')),
    ('LIME', N_('LimeTorrents'), N_('Torrents, needs a torrent client.')),
    ('TPB', N_('The Pirate Bay'), N_('Torrents, needs a torrent client.')),
    ('KAT', N_('KickassTorrents'), N_('Torrents, needs a torrent client.')),
    ('TDL', N_('TorrentDownloads'), N_('Torrents, needs a torrent client.')),
]
# Keys whose change needs the page reloaded to show
RELOAD_KEYS = {'UI_LANGUAGE', 'HTTP_LOOK', 'BOOKSTRAP_THEME', 'EBOOK_TAB', 'AUDIO_TAB', 'MAG_TAB', 'COMIC_TAB',
               'SERIES_TAB'}
TAB_KEYS = [('EBOOK_TAB', N_('eBooks')), ('AUDIO_TAB', N_('AudioBooks')), ('MAG_TAB', N_('Magazines')),
            ('COMIC_TAB', N_('Comics')), ('SERIES_TAB', N_('Series'))]
FOLDER_KEYS = [('EBOOK_DIR', N_('eBook library folder')), ('AUDIO_DIR', N_('AudioBook library folder')),
               ('DOWNLOAD_DIR', N_('Download folder'))]


def _config(config):
    if config is None:
        from lazylibrarian.config2 import CONFIG
        return CONFIG
    return config


def _split(value) -> list:
    return [itm.strip() for itm in str(value or '').split(',') if itm.strip()]


def _merge(*lists) -> list:
    """ Concatenate keeping the first of each item, compared without case and accents """
    seen = set()
    result = []
    for lst in lists:
        for itm in lst:
            key = unaccented(itm).lower()
            if key not in seen:
                seen.add(key)
                result.append(itm)
    return result


def _book_codes(lang: str) -> list:
    """ All the codes BOOK_LANGUAGES has for a language """
    for _name, codes in BOOK_LANGUAGES:
        if lang in codes:
            return list(codes)
    return [lang] if lang else []


def _month_locale(lang: str) -> str:
    """ The built-in month name language for a language code, or '' """
    for loc, _name, _months in MONTH_LANGUAGES:
        if loc.split('_')[0].lower() == lang:
            return loc
    return ''


def _parse_tag(tag: str) -> tuple:
    parts = [p for p in str(tag or '').strip().lower().replace('_', '-').split('-') if p]
    if not parts or len(parts[0]) < 2 or not parts[0].isalpha():
        return '', ''  # x-klingon, i-default, * are no language
    region = parts[-1] if len(parts) > 1 and len(parts[-1]) == 2 and parts[-1].isalpha() else ''
    return parts[0], region


def guess_country(languages) -> str:
    """ The country for the browser languages, like ['sk-SK', 'en'], the first usable one wins """
    for tag in languages or []:
        lang, region = _parse_tag(tag)
        if region and region.upper() in COUNTRIES:
            return region.upper()
        if lang in LANGUAGE_COUNTRY:
            return LANGUAGE_COUNTRY[lang]
    return GENERIC


def country_choices() -> list:
    """ [{'code', 'label'}] for the country dropdown, sorted by translated name, other country last """
    choices = [{'code': code, 'label': i18n.gettext(info['name'])} for code, info in COUNTRIES.items()
               if code != GENERIC]
    choices.sort(key=lambda c: c['label'].lower())
    choices.append({'code': GENERIC, 'label': i18n.gettext(COUNTRIES[GENERIC]['name'])})
    return choices


def profile(country: str, browser_langs=()) -> dict:
    """ The layered preset for a country: language profile, then the country's own values.
        Another country takes its language from the browser """
    country = country if country in COUNTRIES else GENERIC
    info = COUNTRIES[country]
    lang = info['lang']
    if not lang:
        for tag in browser_langs or []:
            lang = _parse_tag(tag)[0]
            if lang:
                break
    prof = {'country': country, 'lang': lang, 'date': '', 'sernum': '', 'also': [], 'source': '',
            'codes': [], 'locale': ''}
    prof.update(LANGUAGES.get(lang, {}))
    prof.update({k: v for k, v in info.items() if k not in ('name', 'lang')})
    prof['month_locale'] = _month_locale(lang)
    if not prof['locale']:
        prof['locale'] = prof['month_locale']
    return prof


def _row(config, key, label, kind, proposed, choices=None, help_text='', current=None):
    if current is None:
        if kind == 'bool':
            current = config.get_bool(key)
        else:
            current = config.get_str(key)
    return {'key': key, 'label': i18n.gettext(label), 'kind': kind, 'current': current, 'proposed': proposed,
            'choices': choices or [], 'changed': proposed != current,
            'help': i18n.gettext(help_text) if help_text else ''}


def _wizard_language_codes() -> set:
    """ Lowercase codes of every language a preset can propose, the codes of other languages are the user's own """
    codes = set()
    for lang in LANGUAGES:
        codes.update(code.lower() for code in _book_codes(lang))
    for info in COUNTRIES.values():
        codes.update(code.lower() for code in info.get('codes', []))
    return codes


def _replace_languages(head: list, current: list) -> list:
    """ The country's languages, then the user's own languages from the current value.
        Languages of the other presets are dropped, so picking another country replaces them """
    ours = _wizard_language_codes() | {code.lower() for code in head}
    return _merge(head, [code for code in current if code.lower() not in ours])


def _replace_words(key: str, current: list, locale_name: str, default: list) -> list:
    """ The current words without those of other languages, then the words of this language.
        English words and the setting's default stay, so do words the user added that no language has """
    attr = key.lower()
    target = LANGUAGE_WORDS.get(locale_name, {}).get(attr, [])
    english = LANGUAGE_WORDS.get('en_GB.UTF-8', {}).get(attr, [])
    keep = {unaccented(word).lower() for word in target + english + default}
    others = {unaccented(word).lower() for words in LANGUAGE_WORDS.values() for word in words.get(attr, [])}
    kept = [word for word in current if unaccented(word).lower() in keep or unaccented(word).lower() not in others]
    return _merge(kept, target)


def _language_buttons(preflang: str, browser_langs) -> list:
    """ The language buttons of the config page for IMP_PREFLANG: [{'label', 'codes', 'shown'}], those in
        preflang first in its order. Codes the picker doesn't know are buttons of their own """
    from lazylibrarian.booklanguages import language_picker
    browser = [str(tag).replace('-', '_').lower() for tag in browser_langs or []]
    return [{'label': lang['label'], 'codes': _split(lang['codes']), 'shown': lang['shown']}
            for lang in language_picker(preflang, browser)['languages']]


def _gb_country_choices() -> list:
    """ GoogleBooks takes one country: [{'value', 'label'}], automatic first, the code with the name
        for the wizard's countries, like the select on the config page """
    choices = [{'value': '', 'label': i18n.gettext('Automatic (where the server is)')}]
    for code in GB_COUNTRIES:
        name = COUNTRIES.get(code, {}).get('name')
        choices.append({'value': code, 'label': f'{code} – {i18n.gettext(name)}' if name else code})
    return choices


def _langid_buttons(value: str, browser_langs) -> list:
    """ Buttons for LANGID_LANGUAGES, one two letter code each: [{'label', 'codes', 'shown'}].
        Shown before "Show all" are the selected ones and the browser's, codes no language has get their own """
    selected = {code.lower() for code in _split(value)}
    browser = {_parse_tag(tag)[0] for tag in browser_langs or []}
    buttons = []
    known = set()
    for name, codes in BOOK_LANGUAGES:
        code = codes[0]
        if len(code) != 2:
            continue
        known.add(code.lower())
        buttons.append({'label': i18n.gettext(name), 'codes': [code],
                        'shown': code.lower() in selected or code.lower() in browser})
    buttons += [{'label': code, 'codes': [code], 'shown': True} for code in _split(value) if code.lower() not in known]
    buttons.sort(key=lambda b: b['label'].lower())
    return buttons


def _with_extra(choices: list, values: list) -> list:
    """ Add values the list doesn't have, so the select can show the current and the proposed value """
    have = {c['value'] for c in choices}
    for value in values:
        if value and value not in have:
            have.add(value)
            choices.insert(0, {'value': value, 'label': value})
    return choices


def _date_format_choices(values: list, date_lang: str) -> list:
    """ The date formats of the config page select, each shown as today's date """
    from lazylibrarian.formatter import DISPLAY_DATE_FORMATS, date_format_picker
    picker = date_format_picker(values[-1], DISPLAY_DATE_FORMATS, datelang=date_lang)
    choices = [{'value': fmt['format'], 'label': fmt['example']} for fmt in picker['formats']]
    return _with_extra(choices, values)


def _date_lang_choices(values: list) -> list:
    """ The built-in month name languages and the country's own locale, like the Date Language select """
    names = {loc: i18n.gettext(name) for loc, name, _months in MONTH_LANGUAGES}
    choices = [{'value': loc, 'label': f'{names[loc]} ({loc})'} for loc in sorted(names, key=lambda x: names[x].lower())]
    for value in values:
        lang = value.split('_')[0].lower()
        base = next((name for loc, name in names.items() if loc.split('_')[0].lower() == lang), '')
        if value and value not in names:
            choices.insert(0, {'value': value, 'label': f'{base} ({value})' if base else value})
            names[value] = base
    return choices


def _maglang_choices(values: list) -> list:
    """ The languages of the magazine language select, by name with the code """
    from lazylibrarian.booklanguages import magazine_language_picker
    choices = [{'value': lang['code'], 'label': f"{lang['label']} ({lang['code']})"}
               for lang in magazine_language_picker('')['languages']]
    return _with_extra(choices, values)


def _recommended_providers(country: str) -> list:
    return recommended_providers(country)


def _libgen_entry(config):
    """ The generic (GEN) provider that is LibGen, the one the program prepares switched off, or None """
    array = config.get_array('GEN')
    if array is None:
        return None
    for entry in array:
        if 'libgen' in entry.get_str('HOST').lower():
            return entry
    return None


def _month_table() -> list:
    return lazylibrarian.MONTHNAMES[0] if lazylibrarian.MONTHNAMES else []


def presets_for(country: str, browser_langs=(), config=None, ui_lang: str = '') -> list:
    """ The wizard steps for a country, each {'id', 'title', 'rows'}, every row
        {'key', 'label', 'kind', 'current', 'proposed', 'choices', 'changed', 'help'}.
        ui_lang is the language the user picked in the wizard, it becomes UI_LANGUAGE """
    config = _config(config)
    prof = profile(country, browser_langs)
    lang = prof['lang']

    ui_langs = ['auto'] + i18n.available_languages()
    if ui_lang in ui_langs:
        ui_proposed = ui_lang
    else:
        ui_proposed = lang if lang in ui_langs and country != GENERIC else 'auto'
    language = [
        _row(config, 'UI_LANGUAGE', N_('Interface language'), 'choice', ui_proposed, ui_langs),
    ]

    sources = [
        _row(config, 'BOOK_API', N_('Main book information source'), 'choice', config.get_str('BOOK_API'),
             BOOK_APIS),
    ]
    if prof['source']:
        sources.append(_row(config, prof['source'], N_('Local book database'), 'bool', True,
                            help_text=SOURCE_HELP.get(prof['source'], '')))
    if country != GENERIC:
        sources.append(_row(config, 'GB_COUNTRY', N_('Country for Google Books results'), 'choice', country,
                            _gb_country_choices(), current=config.get_str('GB_COUNTRY').strip().upper()))

    pref_head = []
    for code in [lang] + prof['also']:
        pref_head += _book_codes(code)
    pref_head += prof['codes'] + _book_codes('en')
    pref = _replace_languages(pref_head, _split(config.get_str('IMP_PREFLANG')))
    langid = _merge(_split(config.get_str('LANGID_LANGUAGES')), [lang] if lang and len(lang) == 2 else [])
    books = [
        _row(config, 'IMP_PREFLANG', N_('Preferred book languages'), 'langs', ', '.join(pref),
             _language_buttons(', '.join(pref), browser_langs)),
        _row(config, 'LANGID_LANGUAGES', N_('Languages to detect in book titles'), 'langs', ', '.join(langid),
             _langid_buttons(', '.join(langid), browser_langs),
             help_text=N_('When a source does not say the language of a book, it is guessed from the title, '
                          'choosing only from these languages. Keep the languages you do not want too, '
                          'so their books are recognised and left out.')),
    ]
    books[-1]['numbered'] = False  # the order doesn't matter to the detection

    dates = []
    month_locale = prof['month_locale']
    if month_locale:
        table = _month_table()
        present = bool(table) and month_locale.lower() in [loc.lower() for loc in table[0]]
        dates.append(_row(config, MONTH_LANGUAGE, N_('Add month names'), 'months', month_locale,
                          current=month_locale if present else ''))
    # month names are looked up by DATE_LANG in the month table, so it is the language there, de_DE in Austria too
    date_lang = month_locale or prof['locale'] or config.get_str('DATE_LANG')
    if month_locale or prof['locale']:
        dates.append(_row(config, 'DATE_LANG', N_('Language for dates'), 'choice', date_lang,
                          _date_lang_choices([date_lang, config.get_str('DATE_LANG')])))
    for key, label in (('DATE_FORMAT', N_('Date format')), ('AUTHOR_DATE_FORMAT', N_('Author date format'))):
        proposed = prof['date'] or config.get_str(key)
        dates.append(_row(config, key, label, 'choice', proposed,
                          _date_format_choices([proposed, config.get_str(key)], date_lang)))
    if lang:
        dates.append(_row(config, 'PREF_MAGLANG', N_('Preferred magazine language'), 'choice', lang,
                          _maglang_choices([lang, config.get_str('PREF_MAGLANG')])))
    for key, label in (('ISSUE_NOUNS', N_('Words for issue numbers')),
                       ('VOLUME_NOUNS', N_('Words for volume numbers')),
                       ('MAG_NOUNS', N_('Other words allowed in magazine titles'))):
        item = config.get_item(key)
        default = _split(item.get_default()) if item else []
        words = _replace_words(key, _split(config.get_str(key)), month_locale, default)
        dates.append(_row(config, key, label, 'csv', ', '.join(words)))

    other = [_row(config, key, label, 'folder', config.get_str(key)) for key, label in FOLDER_KEYS]
    other += [_row(config, key, label, 'bool', config.get_bool(key)) for key, label in TAB_KEYS]
    providers = []
    recommended = _recommended_providers(country)
    for key, label, help_text in SEARCH_PROVIDERS:
        providers.append(_row(config, key, label, 'bool', key in recommended or config.get_bool(key),
                              help_text=help_text))
        if key in recommended:
            providers[-1]['help'] = (i18n.gettext('Recommended for your country') + '. ' + providers[-1]['help']).strip()
    libgen = _libgen_entry(config)
    if libgen is not None:
        providers.insert(1, _row(config, LIBGEN, N_('LibGen'), 'bool', True, current=libgen.get_bool('ENABLED'),
                                 help_text=N_('Recommended for your country. Books and comics from the LibGen mirror.')))
    other.append(_row(config, 'FMT_SERNUM', N_('Series number format'), 'str',
                      prof['sernum'] or config.get_str('FMT_SERNUM')))
    other.append(_row(config, 'HTTP_LOOK', N_('Interface'), 'choice', config.get_str('HTTP_LOOK'),
                      ['bookstrap', 'modern']))
    themes = list(lazylibrarian.BOOKSTRAP_THEMELIST) or [config.get_str('BOOKSTRAP_THEME')]
    other.append(_row(config, 'BOOKSTRAP_THEME', N_('Bookstrap theme'), 'choice',
                      config.get_str('BOOKSTRAP_THEME'), themes))

    return [
        {'id': 'language', 'title': i18n.gettext('Country and language'), 'rows': language},
        {'id': 'sources', 'title': i18n.gettext('Book databases'), 'rows': sources},
        {'id': 'books', 'title': i18n.gettext('Book languages'), 'rows': books},
        {'id': 'dates', 'title': i18n.gettext('Dates, months and magazines'), 'rows': dates},
        {'id': 'providers', 'title': i18n.gettext('Search providers'), 'rows': providers},
        {'id': 'other', 'title': i18n.gettext('Library and other settings'), 'rows': other},
    ]


def _all_keys() -> frozenset:
    keys = {MONTH_LANGUAGE, LIBGEN, 'UI_LANGUAGE', 'BOOK_API', 'GB_COUNTRY', 'IMP_PREFLANG', 'LANGID_LANGUAGES',
            'DATE_LANG', 'DATE_FORMAT', 'AUTHOR_DATE_FORMAT', 'PREF_MAGLANG', 'ISSUE_NOUNS', 'VOLUME_NOUNS',
            'MAG_NOUNS', 'FMT_SERNUM', 'HTTP_LOOK', 'BOOKSTRAP_THEME'}
    keys.update(key for key, _label, _help in SEARCH_PROVIDERS)
    keys.update(prof['source'] for prof in LANGUAGES.values() if prof.get('source'))
    keys.update(key for key, _label in FOLDER_KEYS + TAB_KEYS)
    return frozenset(keys)


WIZARD_KEYS = _all_keys()
_KIND = {'UI_LANGUAGE': 'choice', 'BOOK_API': 'choice', 'HTTP_LOOK': 'choice', 'GB_COUNTRY': 'choice',
         'DBK_API': 'bool', 'DNB_API': 'bool', 'BN_API': 'bool', MONTH_LANGUAGE: 'months', LIBGEN: 'bool'}
_KIND.update({key: 'bool' for key, _label in TAB_KEYS})
_KIND.update({key: 'bool' for key, _label, _help in SEARCH_PROVIDERS})
_BOOL_STRINGS = {'1': True, 'true': True, '0': False, 'false': False, '': False}


def _coerce(key: str, value, config):
    """ The value as the wizard saves it, or raise ValueError """
    kind = _KIND.get(key, 'str')
    if kind == 'bool':
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
        if isinstance(value, str) and value.strip().lower() in _BOOL_STRINGS:
            return _BOOL_STRINGS[value.strip().lower()]
        raise ValueError(f'{key}: not a yes/no value')
    if not isinstance(value, str):
        raise ValueError(f'{key}: not text')
    value = value.strip()
    if key == 'UI_LANGUAGE' and value not in ['auto'] + i18n.available_languages():
        raise ValueError(f'{key}: unknown language {value}')
    if key == 'BOOK_API' and value not in BOOK_APIS:
        raise ValueError(f'{key}: unknown source {value}')
    if key == 'GB_COUNTRY':
        value = value.upper()
        if value and value not in GB_COUNTRIES:
            raise ValueError(f'{key}: unknown country {value}')
    if key == 'HTTP_LOOK' and value not in ('bookstrap', 'modern'):
        raise ValueError(f'{key}: unknown interface {value}')
    if key == MONTH_LANGUAGE:
        if value not in [loc for loc, _n, _m in MONTH_LANGUAGES]:
            raise ValueError(f'{key}: no built-in month names for {value}')
        return value
    item = config.get_item(key)
    if item is None:
        raise ValueError(f'{key}: unknown setting')  # LIBGEN is a bool, returned above
    if item.get_force_lower():
        value = value.lower()
    if not item.is_valid_value(value):
        raise ValueError(f'{i18n.gettext("Not a valid value")}: {key} = {value}')
    return value


def _add_month_language(loc: str) -> bool:
    """ Add a built-in language to the month name table, False if it is there already """
    table = _month_table()
    if not table or loc.lower() in [itm.lower() for itm in table[0]]:
        return False
    months = next(m for code, _n, m in MONTH_LANGUAGES if code == loc)
    new_table = copy.deepcopy(table)
    new_table[0] += [loc, loc]
    for idx, (long_name, short_name) in enumerate(months, start=1):
        new_table[idx] += [long_name, short_name]
    from lazylibrarian import common
    return common.save_monthtable(new_table)


def _locale_available(name: str) -> bool:
    try:
        old = locale.setlocale(locale.LC_TIME)
    except locale.Error:
        return True
    try:
        locale.setlocale(locale.LC_TIME, name)
        return True
    except locale.Error:
        return False
    finally:
        with contextlib.suppress(locale.Error):
            locale.setlocale(locale.LC_TIME, old)


def folder_status(path: str) -> str:
    """ ok, missing, not_writable or empty """
    path = str(path or '').strip()
    if not path:
        return 'empty'
    if not os.path.isdir(path):
        return 'missing'
    if not os.access(path, os.W_OK):
        return 'not_writable'
    return 'ok'


def apply(values: dict, config=None, finish: bool = True) -> dict:
    """ Validate every value first, then set them all and save. Nothing is saved if any value is wrong.
        finish marks the wizard done, so it is not offered on start again.
        Returns {'ok', 'changed', 'reload', 'warnings', 'error'} """
    logger = logging.getLogger(__name__)
    config = _config(config)
    result = {'ok': False, 'changed': [], 'reload': False, 'warnings': [], 'error': ''}
    if not isinstance(values, dict):
        result['error'] = 'values must be an object'
        return result
    unknown = sorted(key for key in values if str(key).upper() not in WIZARD_KEYS)
    if unknown:
        result['error'] = i18n.gettext('Not a setting the wizard can change') + ': ' + ', '.join(unknown)
        return result
    clean = {}
    try:
        for key, value in values.items():
            clean[key.upper()] = _coerce(key.upper(), value, config)
    except ValueError as e:
        result['error'] = str(e)
        return result

    try:
        for key, value in clean.items():
            if key == MONTH_LANGUAGE:
                if _add_month_language(value):
                    result['changed'].append(key)
                continue
            if key == LIBGEN:
                entry = _libgen_entry(config)
                if entry is not None and entry.get_item('ENABLED').set_from_ui(value):
                    result['changed'].append(key)
                continue
            if config.set_from_ui(key, value):
                result['changed'].append(key)
        if finish:
            config.set_bool('SETUP_WIZARD_DONE', True)
        # search providers switched on should start searching, like a save on the config page
        config.save_config_and_backup_old(restart_jobs=True)
    except Exception as e:
        logger.error(f'Setup wizard could not save: {type(e).__name__} {e}')
        result['error'] = str(e)
        return result
    TELEMETRY.record_usage_data('SetupWizard')

    if 'DATE_LANG' in clean and not _locale_available(clean['DATE_LANG']):
        result['warnings'].append(i18n.gettext('The system does not have the locale') + f" {clean['DATE_LANG']}")
    for key, _label in FOLDER_KEYS:
        if clean.get(key) and folder_status(clean[key]) != 'ok':
            result['warnings'].append(i18n.gettext('Folder not found or not writable') + f': {clean[key]}')
    result['reload'] = bool(RELOAD_KEYS & set(result['changed']))
    result['ok'] = True
    logger.info(f"Setup wizard changed {', '.join(result['changed']) or 'nothing'}")
    return result


def dismiss(config=None):
    """ Don't offer the wizard on start again """
    config = _config(config)
    config.set_bool('SETUP_WIZARD_DONE', True)
    config.save_config_and_backup_old()


def should_autoopen(config=None) -> bool:
    """ Offer the wizard on a new install only, an install with a library folder is set up already """
    config = _config(config)
    return (not config.get_bool('SETUP_WIZARD_DONE') and not config.get_str('EBOOK_DIR')
            and not config.get_str('AUDIO_DIR'))


def language_choices() -> list:
    """ [{'code', 'label', 'country'}] for the language dropdown, country is the one the language suggests """
    return [{'code': lang, 'label': i18n.language_name(lang), 'country': LANGUAGE_COUNTRY.get(lang, '')}
            for lang in i18n.available_languages()]


def ui_strings() -> dict:
    """ The dialog's texts in the current UI language, so a language picked in the wizard shows at once """
    _ = i18n.gettext
    return {
        'title': _('Setup Wizard'), 'summary': _('Summary'), 'country': _('Country'), 'language': _('Language'),
        'intro': _('Pick your language and country. The next steps show what will be set for them, '
                   'check it and untick anything you want to keep as it is.'),
        'review': _('These settings will be changed for your country:'),
        'no_changes': _('Nothing to change here, the settings already suit your country.'),
        'show_all': _('Show unchanged settings too'), 'edit': _('Edit'),
        'show_langs': _('Show all languages'),
        'where': _('You can run the Setup Wizard again any time: in Settings, the Setup Wizard button '
                   'next to Check Version.'),
        'loading': _('Loading...'), 'current': _('Now'), 'on': _('On'), 'off': _('Off'),
        'setting': _('Setting'), 'change': _('Change'), 'nothing': _('Nothing is ticked, nothing will be changed.'),
        'back': _('Back'), 'next': _('Next'), 'skip': _('Skip step'), 'apply': _('Apply'), 'cancel': _('Cancel'),
        'dismiss': _("Don't show again"), 'failed': _('Something went wrong, try again'),
        'saved': _('%(count)s settings changed.'),
        'auth': _('The web interface has no username and password, anyone on your network can change the '
                  'settings.'),
        'auth_link': _('Set them on the Interface tab'),
        'folder_ok': _('Folder found'), 'folder_missing': _('Folder not found'),
        'folder_not_writable': _('Folder is not writable'), 'folder_empty': _('Not set'),
    }
