#  This file is part of Lazylibrarian.
#
# Purpose:
#    Table of book languages for the language picker on the config page.
#    Metadata sources report languages in different ways (GoodReads "eng", GoogleBooks "en",
#    others the English name) so each language in the picker stands for all of its codes,
#    and selecting it adds every code to IMP_PREFLANG.

import logging

from lazylibrarian import i18n
from lazylibrarian.formatter import get_list
from lazylibrarian.i18n import N_

# Name, then the codes that mean this language: ISO 639-1, ISO 639-2 (B and T), regional
# variants and the English name. The name is translated for display only, the config stores codes.
BOOK_LANGUAGES = [
    (N_('English'), ['en', 'eng', 'en-US', 'en-GB', 'English']),
    (N_('Spanish'), ['es', 'spa', 'Spanish']),
    (N_('French'), ['fr', 'fre', 'fra', 'French']),
    (N_('German'), ['de', 'ger', 'deu', 'German']),
    (N_('Italian'), ['it', 'ita', 'Italian']),
    (N_('Portuguese'), ['pt', 'por', 'pt-BR', 'pt-PT', 'Portuguese']),
    (N_('Russian'), ['ru', 'rus', 'Russian']),
    (N_('Chinese'), ['zh', 'chi', 'zho', 'zh-CN', 'zh-TW', 'Chinese']),
    (N_('Japanese'), ['ja', 'jpn', 'Japanese']),
    (N_('Dutch'), ['nl', 'dut', 'nld', 'Dutch']),
    (N_('Polish'), ['pl', 'pol', 'Polish']),
    (N_('Czech'), ['cs', 'cze', 'ces', 'Czech']),
    (N_('Slovak'), ['sk', 'slo', 'slk', 'Slovak']),
    (N_('Swedish'), ['sv', 'swe', 'Swedish']),
    (N_('Danish'), ['da', 'dan', 'Danish']),
    (N_('Norwegian'), ['no', 'nor', 'nb', 'nob', 'nn', 'nno', 'Norwegian']),
    (N_('Finnish'), ['fi', 'fin', 'Finnish']),
    (N_('Hungarian'), ['hu', 'hun', 'Hungarian']),
    (N_('Turkish'), ['tr', 'tur', 'Turkish']),
    (N_('Korean'), ['ko', 'kor', 'Korean']),
    (N_('Arabic'), ['ar', 'ara', 'Arabic']),
    (N_('Hebrew'), ['he', 'iw', 'heb', 'Hebrew']),
    (N_('Greek'), ['el', 'gre', 'ell', 'Greek']),
    (N_('Ukrainian'), ['uk', 'ukr', 'Ukrainian']),
    (N_('Afrikaans'), ['af', 'afr', 'Afrikaans']),
    (N_('Albanian'), ['sq', 'alb', 'sqi', 'Albanian']),
    (N_('Armenian'), ['hy', 'arm', 'hye', 'Armenian']),
    (N_('Basque'), ['eu', 'baq', 'eus', 'Basque']),
    (N_('Belarusian'), ['be', 'bel', 'Belarusian']),
    (N_('Bengali'), ['bn', 'ben', 'Bengali']),
    (N_('Bosnian'), ['bs', 'bos', 'Bosnian']),
    (N_('Bulgarian'), ['bg', 'bul', 'Bulgarian']),
    (N_('Catalan'), ['ca', 'cat', 'Catalan']),
    (N_('Croatian'), ['hr', 'hrv', 'Croatian']),
    (N_('Esperanto'), ['eo', 'epo', 'Esperanto']),
    (N_('Estonian'), ['et', 'est', 'Estonian']),
    (N_('Filipino'), ['tl', 'tgl', 'fil', 'Filipino', 'Tagalog']),
    (N_('Galician'), ['gl', 'glg', 'Galician']),
    (N_('Georgian'), ['ka', 'geo', 'kat', 'Georgian']),
    (N_('Hindi'), ['hi', 'hin', 'Hindi']),
    (N_('Icelandic'), ['is', 'ice', 'isl', 'Icelandic']),
    (N_('Indonesian'), ['id', 'ind', 'Indonesian']),
    (N_('Irish'), ['ga', 'gle', 'Irish']),
    (N_('Latin'), ['la', 'lat', 'Latin']),
    (N_('Latvian'), ['lv', 'lav', 'Latvian']),
    (N_('Lithuanian'), ['lt', 'lit', 'Lithuanian']),
    (N_('Macedonian'), ['mk', 'mac', 'mkd', 'Macedonian']),
    (N_('Malay'), ['ms', 'may', 'msa', 'Malay']),
    (N_('Malayalam'), ['ml', 'mal', 'Malayalam']),
    (N_('Odia'), ['or', 'ori', 'ory', 'Odia', 'Oriya']),
    (N_('Persian'), ['fa', 'per', 'fas', 'Persian']),
    (N_('Romanian'), ['ro', 'rum', 'ron', 'Romanian']),
    (N_('Serbian'), ['sr', 'srp', 'Serbian']),
    (N_('Slovenian'), ['sl', 'slv', 'Slovenian']),
    (N_('Swahili'), ['sw', 'swa', 'Swahili']),
    (N_('Tamil'), ['ta', 'tam', 'Tamil']),
    (N_('Thai'), ['th', 'tha', 'Thai']),
    (N_('Twi'), ['tw', 'Twi']),
    (N_('Urdu'), ['ur', 'urd', 'Urdu']),
    (N_('Vietnamese'), ['vi', 'vie', 'Vietnamese']),
    (N_('Welsh'), ['cy', 'wel', 'cym', 'Welsh']),
    (N_('Yiddish'), ['yi', 'yid', 'Yiddish']),
]


def language_picker(preflang: str, browser_languages: list | tuple = ()) -> dict:
    """ The languages of an IMP_PREFLANG value for the language picker.
        A language is selected if any of its codes is in the value.
        All and Unknown are picker entries of their own, and so is each entry of the value the
        picker doesn't know, so saving keeps it.
        Before "Show all" the picker shows the selected entries, in the order they appear in the
        value, then All and Unknown, then the browser_languages (codes like 'sk' or 'en_us')
        sorted by their translated name. The rest follow, sorted the same.
        Each language also carries what it searches for when Anna's Archive and Z-Library are automatic:
        'anna' for Anna's Archive ('' if not supported), 'zlib' for Z-Library ('' for the special entries).
        Returns {'languages': [{'name', 'label', 'codes', 'anna', 'zlib', 'selected', 'shown'}]} """
    from lazylibrarian.annas import Language as AnnaLanguage

    wanted = [item for item in get_list(preflang, ',') if item]
    position = {}
    for idx, item in enumerate(wanted):
        position.setdefault(item.lower(), idx)
    shown = {lang.split('_')[0].lower() for lang in browser_languages}
    known = set()
    languages = []
    for name, codes in BOOK_LANGUAGES:
        lower_codes = {code.lower() for code in codes}
        known.update(lower_codes)
        found = [position[code] for code in lower_codes if code in position]
        anna = codes[0].upper()
        languages.append({
            'name': name,
            'label': i18n.gettext(name),
            'codes': ', '.join(codes),
            'anna': anna if anna in AnnaLanguage.__members__ else '',
            'zlib': name.lower(),
            'selected': bool(found),
            'position': min(found) if found else 0,
            'shown': bool(found or lower_codes & shown),
        })
    languages.sort(key=lambda lang: lang['label'].lower())

    # All turns the language check off, Unknown also takes books the source has no language for
    special = []
    for code, label in (('All', N_('All languages')), ('Unknown', N_('Unknown'))):
        known.add(code.lower())
        special.append({'name': code, 'label': i18n.gettext(label), 'codes': code, 'anna': '', 'zlib': '',
                        'selected': code.lower() in position, 'position': position.get(code.lower(), 0),
                        'shown': True})
    seen = set()
    for item in wanted:
        if item.lower() not in known and item.lower() not in seen:
            seen.add(item.lower())
            special.append({'name': item, 'label': item, 'codes': item, 'anna': '', 'zlib': '',
                            'selected': True, 'position': position[item.lower()], 'shown': True})

    selected = sorted((lang for lang in special + languages if lang['selected']), key=lambda lang: lang['position'])
    ordered = (selected + [lang for lang in special + languages if lang['shown'] and not lang['selected']]
               + [lang for lang in languages if not lang['shown']])
    return {'languages': ordered}


def _search_languages(preflang: str) -> list | None:
    """ The BOOK_LANGUAGES entries in an IMP_PREFLANG value, in the order they appear in it.
        None if the value doesn't limit languages: empty, or "All" in it """
    wanted = [item.lower() for item in get_list(preflang, ',') if item]
    if not wanted or 'all' in wanted:
        return None
    found = []
    for name, codes in BOOK_LANGUAGES:
        positions = [wanted.index(code.lower()) for code in codes if code.lower() in wanted]
        if positions:
            found.append((min(positions), name, codes))
    return [(name, codes) for _, name, codes in sorted(found)]


# Country codes people enter for a language whose code is different (CZ is Czechia, Czech is cs)
COUNTRY_LANGUAGES = {'cn': 'zh', 'cz': 'cs', 'dk': 'da', 'gr': 'el', 'jp': 'ja', 'kr': 'ko', 'se': 'sv', 'ua': 'uk'}


def search_language_value(item: str, source: str) -> str:
    """ What ANNA_SEARCH_LANG (source 'anna') or BOK_SEARCH_LANG (source 'zlib') stores for a language
        entered as item: the upper case code for Anna's Archive, the lower case English name for Z-Library.
        item can be any code or English name of a BOOK_LANGUAGES language, or a country code in
        COUNTRY_LANGUAGES, case insensitive. '' if it's none of these, or Anna's Archive doesn't support it """
    from lazylibrarian.annas import Language as AnnaLanguage

    code = item.strip().lower()
    if not code or code == 'any':
        return ''
    if source == 'anna' and code.upper() in AnnaLanguage.__members__:
        return code.upper()
    for wanted in (code, COUNTRY_LANGUAGES.get(code)):
        if not wanted:
            continue
        for name, codes in BOOK_LANGUAGES:
            if wanted in (lang_code.lower() for lang_code in codes):
                if source == 'anna':
                    value = codes[0].upper()
                    return value if value in AnnaLanguage.__members__ else ''
                return name.lower()
    return ''


# Magazines and comics have a language of their own, not the Import languages,
# so automatic search languages search them in all languages
ALL_LANGUAGE_SEARCHES = ('mag', 'comic')


def anna_search_languages(anna_search_lang: str, preflang: str, searchtype: str = '') -> str:
    """ ANNA_SEARCH_LANG, or when it's empty (automatic) the Import languages for Anna's Archive.
        ANY for magazines and comics, and when an Import language isn't one Anna's Archive
        supports: leaving it out would drop that language without a word, and searching a
        language we don't want is better than finding nothing """
    if anna_search_lang.strip():
        return anna_search_lang
    if searchtype in ALL_LANGUAGE_SEARCHES:
        return 'ANY'
    from lazylibrarian.annas import Language as AnnaLanguage

    languages = _search_languages(preflang) or []
    unsupported = [name for name, codes in languages if codes[0].upper() not in AnnaLanguage.__members__]
    if unsupported:
        logging.getLogger(__name__).debug(
            f"Annas Archive doesn't support {', '.join(unsupported)}, searching all languages")
        return 'ANY'
    return ', '.join(codes[0].upper() for _, codes in languages) or 'ANY'


def zlib_search_languages(bok_search_lang: str, preflang: str, searchtype: str = '') -> str:
    """ BOK_SEARCH_LANG, or when it's empty (automatic) the Import languages as Z-Library names.
        ANY for magazines and comics, and if they don't limit the language """
    if bok_search_lang.strip():
        return bok_search_lang
    if searchtype in ALL_LANGUAGE_SEARCHES:
        return 'ANY'
    return ', '.join(name.lower() for name, _ in _search_languages(preflang) or []) or 'ANY'


def search_language_picker(search_lang: str, source: str, preflang: str = '',
                           browser_languages: list | tuple = ()) -> dict:
    """ The languages of an ANNA_SEARCH_LANG (source 'anna') or BOK_SEARCH_LANG (source 'zlib')
        value for their pickers. 'value' is what the setting stores for a language: the upper case
        code for Anna's Archive, which only lists the languages it supports, the lower case English
        name for Z-Library. Matching is case insensitive, and any code or name of a language, or a
        country code like CZ, selects that language (see search_language_value), so saving corrects it.
        The mode is 'auto' for an empty value (the Import languages), 'any' if ANY is in it, else 'custom'.
        Each entry of the value the picker doesn't know is an entry of its own, so saving keeps it.
        Before "Show all" the picker shows the selected entries in the order they appear in the
        value, then the Import languages and the browser_languages, sorted by their translated name.
        Returns {'mode': str, 'languages': [{'value', 'label', 'selected', 'shown'}]} """
    from lazylibrarian.annas import Language as AnnaLanguage

    wanted = [item for item in get_list(search_lang, ',') if item]
    keys = [(search_language_value(item, source) or item).lower() for item in wanted]
    position = {}
    for idx, key in enumerate(keys):
        position.setdefault(key, idx)
    if not wanted:
        mode = 'auto'
    elif 'any' in position:
        mode = 'any'
    else:
        mode = 'custom'
    imported = {name for name, _ in _search_languages(preflang) or []}
    browser = {lang.split('_')[0].lower() for lang in browser_languages}
    languages = []
    for name, codes in BOOK_LANGUAGES:
        if source == 'anna':
            value = codes[0].upper()
            if value not in AnnaLanguage.__members__:
                continue
        else:
            value = name.lower()
        selected = value.lower() in position
        languages.append({
            'value': value,
            'label': i18n.gettext(name),
            'selected': selected,
            'position': position.get(value.lower(), 0),
            'shown': selected or name in imported or bool({code.lower() for code in codes} & browser),
        })
    languages.sort(key=lambda lang: lang['label'].lower())

    known = {lang['value'].lower() for lang in languages} | {'any'}
    other = []
    for item, key in zip(wanted, keys):
        if key not in known:
            known.add(key)
            other.append({'value': item, 'label': item, 'selected': True, 'position': position[key],
                          'shown': True})

    selected = sorted((lang for lang in other + languages if lang['selected']), key=lambda lang: lang['position'])
    ordered = (selected + [lang for lang in languages if lang['shown'] and not lang['selected']]
               + [lang for lang in languages if not lang['shown']])
    return {'mode': mode, 'languages': ordered}


# ISO 3166-1 alpha-2 codes for the GoogleBooks country setting, the browser shows their names
GB_COUNTRIES = [
    'AD', 'AE', 'AF', 'AG', 'AI', 'AL', 'AM', 'AO', 'AQ', 'AR', 'AS', 'AT', 'AU', 'AW', 'AX',
    'AZ', 'BA', 'BB', 'BD', 'BE', 'BF', 'BG', 'BH', 'BI', 'BJ', 'BL', 'BM', 'BN', 'BO', 'BQ',
    'BR', 'BS', 'BT', 'BV', 'BW', 'BY', 'BZ', 'CA', 'CC', 'CD', 'CF', 'CG', 'CH', 'CI', 'CK',
    'CL', 'CM', 'CN', 'CO', 'CR', 'CU', 'CV', 'CW', 'CX', 'CY', 'CZ', 'DE', 'DJ', 'DK', 'DM',
    'DO', 'DZ', 'EC', 'EE', 'EG', 'EH', 'ER', 'ES', 'ET', 'FI', 'FJ', 'FK', 'FM', 'FO', 'FR',
    'GA', 'GB', 'GD', 'GE', 'GF', 'GG', 'GH', 'GI', 'GL', 'GM', 'GN', 'GP', 'GQ', 'GR', 'GS',
    'GT', 'GU', 'GW', 'GY', 'HK', 'HM', 'HN', 'HR', 'HT', 'HU', 'ID', 'IE', 'IL', 'IM', 'IN',
    'IO', 'IQ', 'IR', 'IS', 'IT', 'JE', 'JM', 'JO', 'JP', 'KE', 'KG', 'KH', 'KI', 'KM', 'KN',
    'KP', 'KR', 'KW', 'KY', 'KZ', 'LA', 'LB', 'LC', 'LI', 'LK', 'LR', 'LS', 'LT', 'LU', 'LV',
    'LY', 'MA', 'MC', 'MD', 'ME', 'MF', 'MG', 'MH', 'MK', 'ML', 'MM', 'MN', 'MO', 'MP', 'MQ',
    'MR', 'MS', 'MT', 'MU', 'MV', 'MW', 'MX', 'MY', 'MZ', 'NA', 'NC', 'NE', 'NF', 'NG', 'NI',
    'NL', 'NO', 'NP', 'NR', 'NU', 'NZ', 'OM', 'PA', 'PE', 'PF', 'PG', 'PH', 'PK', 'PL', 'PM',
    'PN', 'PR', 'PS', 'PT', 'PW', 'PY', 'QA', 'RE', 'RO', 'RS', 'RU', 'RW', 'SA', 'SB', 'SC',
    'SD', 'SE', 'SG', 'SH', 'SI', 'SJ', 'SK', 'SL', 'SM', 'SN', 'SO', 'SR', 'SS', 'ST', 'SV',
    'SX', 'SY', 'SZ', 'TC', 'TD', 'TF', 'TG', 'TH', 'TJ', 'TK', 'TL', 'TM', 'TN', 'TO', 'TR',
    'TT', 'TV', 'TW', 'TZ', 'UA', 'UG', 'UM', 'US', 'UY', 'UZ', 'VA', 'VC', 'VE', 'VG', 'VI',
    'VN', 'VU', 'WF', 'WS', 'YE', 'YT', 'ZA', 'ZM', 'ZW',
]


def country_picker(gb_country: str) -> dict:
    """ Countries for the GoogleBooks country select and the one to select.
        GoogleBooks takes a single country, anything else was ignored so it selects automatic ('').
        Returns {'countries': [codes], 'selected': str} """
    country = gb_country.strip().upper()
    return {'countries': GB_COUNTRIES, 'selected': country if country in GB_COUNTRIES else ''}


def magazine_language_picker(pref_maglang: str) -> dict:
    """ Languages for the default magazine language select, sorted by their translated name.
        Magazines take a single code, the ISO 639-1 one. A stored value that isn't one of these
        codes is returned as 'other' so the select can keep it and saving doesn't change it.
        Returns {'languages': [{'code', 'label'}], 'selected': str, 'other': str | None} """
    languages = sorted(({'code': codes[0], 'label': i18n.gettext(name)} for name, codes in BOOK_LANGUAGES),
                       key=lambda lang: lang['label'].lower())
    value = pref_maglang.strip()
    for lang in languages:
        if lang['code'].lower() == value.lower():
            return {'languages': languages, 'selected': lang['code'], 'other': None}
    return {'languages': languages, 'selected': value, 'other': value}


def _book_language(code: str) -> tuple:
    """ The BOOK_LANGUAGES entry (name, codes) a language code belongs to, (None, None) if none """
    code = code.strip().lower()
    for name, codes in BOOK_LANGUAGES:
        if code in (item.lower() for item in codes):
            return name, codes
    return None, None


def language_filter_options(booklangs) -> list:
    """ The languages for the language filter of the eBook, AudioBook and author book lists, one each.
        booklangs are the BookLang values in the list (strings or rows with a BookLang column), which
        sources report in different ways (cs, cze, Czech), sometimes several separated by commas.
        Each code of a language counts as that language, a value the table doesn't know is an entry
        of its own (compared case insensitive).
        Returns [{'BookLang', 'booklang', 'label'}] sorted by label, BookLang/booklang being the value
        to filter on: the English name for a known language """
    options = {}
    for value in booklangs:
        if value is not None and not isinstance(value, str):
            value = value['BookLang']
        for item in get_list(value or '', ','):
            if not item:
                continue
            name, _ = _book_language(item)
            if name:
                options.setdefault(name.lower(), {'BookLang': name, 'booklang': name,
                                                  'label': i18n.gettext(name)})
            else:
                options.setdefault(item.lower(), {'BookLang': item, 'booklang': item, 'label': item})
    return sorted(options.values(), key=lambda option: option['label'].lower())


def language_filter_sql(booklang: str, column: str = 'BookLang') -> tuple:
    """ SQL condition and its args for books in the language chosen in a language filter:
        BookLang is one of the codes of that language, or a comma separated list with one of them.
        Returns (condition, args) """
    _, codes = _book_language(booklang)
    if not codes:
        codes = [booklang]
    wanted = sorted({code.strip().lower().replace(' ', '') for code in codes})
    value = f"',' || replace(lower({column}), ' ', '') || ','"
    condition = ' OR '.join(f"{value} LIKE ?" for _ in wanted)
    return f"({condition})", [f"%,{code},%" for code in wanted]
