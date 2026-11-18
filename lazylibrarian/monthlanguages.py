#  This file is part of Lazylibrarian.
#
# Purpose:
#    Built-in month names for the month name table on the config page.
#    The table in monthnames.json starts with English only. The user switches languages on and off
#    from this list, so nothing depends on which locales the system has installed.
#    Each language also brings its season names, for magazine issues like "Winter 2017",
#    its words for issue and volume numbers and other words allowed in magazine titles,
#    and its author name suffixes and articles for sorting.

from lazylibrarian import i18n
from lazylibrarian.i18n import N_

# Locale, display name, then long and short name for each month from January to December.
# The locale is what goes in the month table and DATE_LANG, the name is translated for display only.
MONTH_LANGUAGES = [
    ('cs_CZ.UTF-8', N_('Czech'), [
        ('leden', 'led'), ('únor', 'úno'), ('březen', 'bře'), ('duben', 'dub'),
        ('květen', 'kvě'), ('červen', 'čvn'), ('červenec', 'čvc'), ('srpen', 'srp'),
        ('září', 'zář'), ('říjen', 'říj'), ('listopad', 'lis'), ('prosinec', 'pro')]),
    ('en_GB.UTF-8', N_('English'), [
        ('January', 'Jan'), ('February', 'Feb'), ('March', 'Mar'), ('April', 'Apr'),
        ('May', 'May'), ('June', 'Jun'), ('July', 'Jul'), ('August', 'Aug'),
        ('September', 'Sep'), ('October', 'Oct'), ('November', 'Nov'), ('December', 'Dec')]),
    ('da_DK.UTF-8', N_('Danish'), [
        ('januar', 'jan'), ('februar', 'feb'), ('marts', 'mar'), ('april', 'apr'),
        ('maj', 'maj'), ('juni', 'jun'), ('juli', 'jul'), ('august', 'aug'),
        ('september', 'sep'), ('oktober', 'okt'), ('november', 'nov'), ('december', 'dec')]),
    ('de_DE.UTF-8', N_('German'), [
        ('Januar', 'Jan'), ('Februar', 'Feb'), ('März', 'Mär'), ('April', 'Apr'),
        ('Mai', 'Mai'), ('Juni', 'Jun'), ('Juli', 'Jul'), ('August', 'Aug'),
        ('September', 'Sep'), ('Oktober', 'Okt'), ('November', 'Nov'), ('Dezember', 'Dez')]),
    ('es_ES.UTF-8', N_('Spanish'), [
        ('enero', 'ene'), ('febrero', 'feb'), ('marzo', 'mar'), ('abril', 'abr'),
        ('mayo', 'may'), ('junio', 'jun'), ('julio', 'jul'), ('agosto', 'ago'),
        ('septiembre', 'sep'), ('octubre', 'oct'), ('noviembre', 'nov'), ('diciembre', 'dic')]),
    ('fr_FR.UTF-8', N_('French'), [
        ('janvier', 'janv.'), ('février', 'févr.'), ('mars', 'mars'), ('avril', 'avr.'),
        ('mai', 'mai'), ('juin', 'juin'), ('juillet', 'juil.'), ('août', 'août'),
        ('septembre', 'sept.'), ('octobre', 'oct.'), ('novembre', 'nov.'), ('décembre', 'déc.')]),
    ('hu_HU.UTF-8', N_('Hungarian'), [
        ('január', 'jan.'), ('február', 'febr.'), ('március', 'márc.'), ('április', 'ápr.'),
        ('május', 'máj.'), ('június', 'jún.'), ('július', 'júl.'), ('augusztus', 'aug.'),
        ('szeptember', 'szept.'), ('október', 'okt.'), ('november', 'nov.'), ('december', 'dec.')]),
    ('it_IT.UTF-8', N_('Italian'), [
        ('gennaio', 'gen'), ('febbraio', 'feb'), ('marzo', 'mar'), ('aprile', 'apr'),
        ('maggio', 'mag'), ('giugno', 'giu'), ('luglio', 'lug'), ('agosto', 'ago'),
        ('settembre', 'set'), ('ottobre', 'ott'), ('novembre', 'nov'), ('dicembre', 'dic')]),
    ('nb_NO.UTF-8', N_('Norwegian'), [
        ('januar', 'jan'), ('februar', 'feb'), ('mars', 'mar'), ('april', 'apr'),
        ('mai', 'mai'), ('juni', 'jun'), ('juli', 'jul'), ('august', 'aug'),
        ('september', 'sep'), ('oktober', 'okt'), ('november', 'nov'), ('desember', 'des')]),
    ('nl_NL.UTF-8', N_('Dutch'), [
        ('januari', 'jan'), ('februari', 'feb'), ('maart', 'mrt'), ('april', 'apr'),
        ('mei', 'mei'), ('juni', 'jun'), ('juli', 'jul'), ('augustus', 'aug'),
        ('september', 'sep'), ('oktober', 'okt'), ('november', 'nov'), ('december', 'dec')]),
    ('pl_PL.UTF-8', N_('Polish'), [
        ('styczeń', 'sty'), ('luty', 'lut'), ('marzec', 'mar'), ('kwiecień', 'kwi'),
        ('maj', 'maj'), ('czerwiec', 'cze'), ('lipiec', 'lip'), ('sierpień', 'sie'),
        ('wrzesień', 'wrz'), ('październik', 'paź'), ('listopad', 'lis'), ('grudzień', 'gru')]),
    ('pt_PT.UTF-8', N_('Portuguese'), [
        ('janeiro', 'jan'), ('fevereiro', 'fev'), ('março', 'mar'), ('abril', 'abr'),
        ('maio', 'mai'), ('junho', 'jun'), ('julho', 'jul'), ('agosto', 'ago'),
        ('setembro', 'set'), ('outubro', 'out'), ('novembro', 'nov'), ('dezembro', 'dez')]),
    ('ru_RU.UTF-8', N_('Russian'), [
        ('январь', 'янв'), ('февраль', 'фев'), ('март', 'мар'), ('апрель', 'апр'),
        ('май', 'май'), ('июнь', 'июн'), ('июль', 'июл'), ('август', 'авг'),
        ('сентябрь', 'сен'), ('октябрь', 'окт'), ('ноябрь', 'ноя'), ('декабрь', 'дек')]),
    ('sk_SK.UTF-8', N_('Slovak'), [
        ('január', 'jan'), ('február', 'feb'), ('marec', 'mar'), ('apríl', 'apr'),
        ('máj', 'máj'), ('jún', 'jún'), ('júl', 'júl'), ('august', 'aug'),
        ('september', 'sep'), ('október', 'okt'), ('november', 'nov'), ('december', 'dec')]),
    ('sv_SE.UTF-8', N_('Swedish'), [
        ('januari', 'jan'), ('februari', 'feb'), ('mars', 'mar'), ('april', 'apr'),
        ('maj', 'maj'), ('juni', 'jun'), ('juli', 'jul'), ('augusti', 'aug'),
        ('september', 'sep'), ('oktober', 'okt'), ('november', 'nov'), ('december', 'dec')]),
]

# Season names of each language and the month an issue with that name is dated.
# They are matched without accents and lowercase (formatter.month2num), so they are stored that way.
SEASON_NAMES = {
    'cs_CZ.UTF-8': {'zima': 1, 'jaro': 4, 'leto': 7, 'podzim': 10},
    'da_DK.UTF-8': {'vinter': 1, 'forar': 4, 'sommer': 7, 'efterar': 10},
    'de_DE.UTF-8': {'winter': 1, 'fruhling': 4, 'fruhjahr': 4, 'sommer': 7, 'herbst': 10, 'weihnachten': 12},
    'en_GB.UTF-8': {'winter': 1, 'spring': 4, 'summer': 7, 'fall': 10, 'autumn': 10, 'christmas': 12},
    'es_ES.UTF-8': {'invierno': 1, 'primavera': 4, 'verano': 7, 'otono': 10, 'navidad': 12},
    'fr_FR.UTF-8': {'hiver': 1, 'printemps': 4, 'ete': 7, 'automne': 10, 'noel': 12},
    'hu_HU.UTF-8': {'tel': 1, 'tavasz': 4, 'nyar': 7, 'osz': 10, 'karacsony': 12},
    'it_IT.UTF-8': {'inverno': 1, 'primavera': 4, 'estate': 7, 'autunno': 10, 'natale': 12},
    'nb_NO.UTF-8': {'vinter': 1, 'var': 4, 'sommer': 7, 'host': 10},
    'nl_NL.UTF-8': {'winter': 1, 'lente': 4, 'voorjaar': 4, 'zomer': 7, 'herfst': 10, 'najaar': 10, 'kerst': 12},
    'pl_PL.UTF-8': {'zima': 1, 'wiosna': 4, 'lato': 7, 'jesien': 10},
    'pt_PT.UTF-8': {'inverno': 1, 'primavera': 4, 'verao': 7, 'outono': 10, 'natal': 12},
    'ru_RU.UTF-8': {'зима': 1, 'весна': 4, 'лето': 7, 'осень': 10},
    'sk_SK.UTF-8': {'zima': 1, 'jar': 4, 'leto': 7, 'jesen': 10, 'vianoce': 12},
    'sv_SE.UTF-8': {'vinter': 1, 'var': 4, 'sommar': 7, 'host': 10},
}


# Words of each language for the ISSUE_NOUNS, VOLUME_NOUNS, MAG_NOUNS, NAME_POSTFIX, NAME_PREFIX and
# NAME_DEFINITE settings. They are compared without accents and lowercase (formatter.word_key), so they are
# stored that way and match titles written with or without accents. English is the defaults of the settings.
# Name suffixes include titles written after the name, like PhD, prefixes those written before it, like Ing.
# Short ones that are also names (MA, BA, Don, M.) are left out. Articles are only those a title starts with,
# languages without articles have none.
# MULTI_AUTHOR_SPLIT, REJECT_WORDS and COMIC_GENRES are compared lowercase but with accents, so their words
# are lowercase and written both ways where people write both (hörbuch, horbuch). Split words that are also
# part of names are left out (Spanish y as in Ortega y Gasset, Portuguese e).
LANGUAGE_WORDS = {
    'cs_CZ.UTF-8': {'issue_nouns': ['cislo', 'cis', 'c'],
                    'volume_nouns': ['rocnik', 'roc'],
                    'mag_nouns': ['vydani', 'special', 'edice'],
                    'name_postfix': ['ml', 'st', 'phd', 'ph.d', 'csc', 'drsc', 'artd', 'mba', 'dis'],
                    'name_definite': [],
                    'name_prefix': ['ing', 'arch', 'mgr', 'bc', 'doc', 'prof', 'dr', 'mudr', 'judr', 'phdr', 'rndr',
                                    'paeddr', 'mvdr', 'mddr', 'pharmdr', 'thdr'],
                    'multi_author_split': ['a', 's'],
                    'reject_words': ['audiokniha', 'audioknihy'],
                    'comic_genres': ['komiks', 'komiksy']},
    'da_DK.UTF-8': {'issue_nouns': ['nummer', 'nr'],
                    'volume_nouns': ['argang', 'bind'],
                    'mag_nouns': ['udgave', 'special'],
                    'name_postfix': ['jr', 'sr', 'mba', 'ph.d'],
                    'name_definite': ['en', 'et'],
                    'name_prefix': ['dr', 'prof'],
                    'multi_author_split': ['og', 'med'],
                    'reject_words': ['lydbog', 'lydbøger', 'lydboger'],
                    'comic_genres': ['tegneserie', 'tegneserier']},
    'de_DE.UTF-8': {'issue_nouns': ['ausgabe', 'heft', 'nr'],
                    'volume_nouns': ['jahrgang', 'jg', 'band', 'bd'],
                    'mag_nouns': ['sonderausgabe', 'sonderheft', 'edition', 'spezial'],
                    'name_postfix': ['jun', 'sen', 'jr', 'sr', 'mba', 'bsc', 'msc'],
                    'name_definite': ['der', 'die', 'das', 'ein', 'eine'],
                    'name_prefix': ['dr', 'prof', 'dipl.-ing', 'mag'],
                    'multi_author_split': ['und', 'mit'],
                    'reject_words': ['hörbuch', 'horbuch', 'hoerbuch', 'hörspiel', 'horspiel', 'hoerspiel'],
                    'comic_genres': ['comic', 'comics', 'manga']},
    'en_GB.UTF-8': {'issue_nouns': ['issue', 'iss', 'no', 'nr', '#', 'n'],
                    'volume_nouns': ['vol', 'volume'],
                    'mag_nouns': ['edition', 'special'],
                    'name_postfix': ['snr', 'jnr', 'jr', 'sr', 'phd'],
                    'name_definite': ['the', 'a'],
                    'name_prefix': ['mr', 'mrs', 'ms', 'dr', 'prof', 'sir', 'dame', 'rev'],
                    'multi_author_split': ['and', 'with'],
                    'reject_words': ['audiobook'],
                    'comic_genres': ['graphic novel', 'comics', 'comic', 'manga', 'graphic novels']},
    'es_ES.UTF-8': {'issue_nouns': ['numero', 'num', 'n', 'no'],
                    'volume_nouns': ['volumen', 'vol', 'tomo'],
                    'mag_nouns': ['edicion', 'especial'],
                    'name_postfix': ['hijo', 'jr', 'mba', 'ph.d'],
                    'name_definite': ['el', 'la', 'los', 'las', 'un', 'una'],
                    'name_prefix': ['sr', 'sra', 'dr', 'dra', 'prof'],
                    'multi_author_split': ['con'],
                    'reject_words': ['audiolibro'],
                    'comic_genres': ['historieta', 'historietas', 'novela gráfica', 'novela grafica', 'manga']},
    'fr_FR.UTF-8': {'issue_nouns': ['numero', 'n', 'no'],
                    'volume_nouns': ['volume', 'vol', 'tome'],
                    'mag_nouns': ['edition', 'special'],
                    'name_postfix': ['fils', 'pere', 'jr', 'mba', 'ph.d'],
                    'name_definite': ['le', 'la', 'les', 'un', 'une'],
                    'name_prefix': ['mme', 'mlle', 'dr', 'pr'],
                    'multi_author_split': ['et', 'avec'],
                    'reject_words': [],
                    'comic_genres': ['bandes dessinées', 'bandes dessinees', 'bande dessinée', 'bande dessinee',
                                     'bd', 'manga']},
    'hu_HU.UTF-8': {'issue_nouns': ['szam', 'sz'],
                    'volume_nouns': ['evfolyam', 'evf'],
                    'mag_nouns': ['kiadas', 'kulonszam'],
                    'name_postfix': ['mba', 'ph.d'],
                    'name_definite': ['a', 'az', 'egy'],
                    'name_prefix': ['dr', 'prof', 'ifj', 'id'],
                    'multi_author_split': ['és', 'es'],
                    'reject_words': ['hangoskönyv', 'hangoskonyv'],
                    'comic_genres': ['képregény', 'kepregeny', 'manga']},
    'it_IT.UTF-8': {'issue_nouns': ['numero', 'num', 'n'],
                    'volume_nouns': ['volume', 'vol'],
                    'mag_nouns': ['edizione', 'speciale'],
                    'name_postfix': ['jr', 'sr', 'mba', 'ph.d'],
                    'name_definite': ['il', 'lo', 'la', 'i', 'gli', 'le', 'un', 'uno', 'una'],
                    'name_prefix': ['dott', 'dott.ssa', 'dr', 'prof', 'ing', 'avv', 'sig', 'sig.ra'],
                    'multi_author_split': ['e', 'con'],
                    'reject_words': ['audiolibro'],
                    'comic_genres': ['fumetti', 'fumetto', 'manga']},
    'nb_NO.UTF-8': {'issue_nouns': ['nummer', 'nr'],
                    'volume_nouns': ['argang', 'bind'],
                    'mag_nouns': ['utgave', 'spesial'],
                    'name_postfix': ['jr', 'sr', 'mba', 'ph.d'],
                    'name_definite': ['en', 'et', 'ei'],
                    'name_prefix': ['dr', 'prof'],
                    'multi_author_split': ['og', 'med'],
                    'reject_words': ['lydbok', 'lydbøker', 'lydboker'],
                    'comic_genres': ['tegneserie', 'tegneserier']},
    'nl_NL.UTF-8': {'issue_nouns': ['nummer', 'nr', 'uitgave'],
                    'volume_nouns': ['jaargang', 'jrg', 'deel'],
                    'mag_nouns': ['editie', 'speciale', 'special'],
                    'name_postfix': ['jr', 'sr', 'mba', 'ph.d'],
                    'name_definite': ['de', 'het', 'een'],
                    'name_prefix': ['dr', 'prof', 'drs', 'ir', 'ing', 'mr'],
                    'multi_author_split': ['en', 'met'],
                    'reject_words': ['luisterboek'],
                    'comic_genres': ['strip', 'strips', 'stripboek', 'stripverhaal', 'manga']},
    'pl_PL.UTF-8': {'issue_nouns': ['numer', 'nr'],
                    'volume_nouns': ['rocznik', 'tom'],
                    'mag_nouns': ['wydanie', 'specjalne', 'edycja'],
                    'name_postfix': ['jr', 'sr', 'mba', 'ph.d'],
                    'name_definite': [],
                    'name_prefix': ['dr', 'prof', 'hab', 'mgr', 'inz'],
                    'multi_author_split': ['i', 'z'],
                    'reject_words': ['audiobook', 'audiobooki'],
                    'comic_genres': ['komiks', 'komiksy', 'manga']},
    'pt_PT.UTF-8': {'issue_nouns': ['numero', 'no', 'n', 'edicao'],
                    'volume_nouns': ['volume', 'vol'],
                    'mag_nouns': ['especial'],
                    'name_postfix': ['filho', 'neto', 'junior', 'jr', 'mba', 'ph.d'],
                    'name_definite': ['o', 'a', 'os', 'as', 'um', 'uma'],
                    'name_prefix': ['dr', 'dra', 'prof', 'eng', 'sr', 'sra'],
                    'multi_author_split': ['com'],
                    'reject_words': ['audiolivro', 'audiobook'],
                    'comic_genres': ['banda desenhada', 'quadrinhos', 'manga']},
    'ru_RU.UTF-8': {'issue_nouns': ['номер', 'выпуск', 'no'],
                    'volume_nouns': ['том'],
                    'mag_nouns': ['издание', 'спецвыпуск'],
                    'name_postfix': ['mba', 'ph.d'],
                    'name_definite': [],
                    'name_prefix': [],
                    'multi_author_split': ['и', 'с'],
                    'reject_words': ['аудиокнига'],
                    'comic_genres': ['комикс', 'комиксы', 'манга']},
    'sk_SK.UTF-8': {'issue_nouns': ['cislo', 'c'],
                    'volume_nouns': ['rocnik', 'roc'],
                    'mag_nouns': ['vydanie', 'special', 'edicia'],
                    'name_postfix': ['ml', 'st', 'phd', 'ph.d', 'csc', 'drsc', 'artd', 'mba', 'dis'],
                    'name_definite': [],
                    'name_prefix': ['ing', 'arch', 'mgr', 'bc', 'doc', 'prof', 'dr', 'mudr', 'judr', 'phdr', 'rndr',
                                    'paeddr', 'mvdr', 'mddr', 'pharmdr', 'thdr'],
                    'multi_author_split': ['a', 's'],
                    'reject_words': ['audiokniha', 'audioknihy'],
                    'comic_genres': ['komiks', 'komiksy']},
    'sv_SE.UTF-8': {'issue_nouns': ['nummer', 'nr'],
                    'volume_nouns': ['argang', 'volym'],
                    'mag_nouns': ['utgava', 'special'],
                    'name_postfix': ['jr', 'sr', 'mba', 'ph.d'],
                    'name_definite': ['en', 'ett'],
                    'name_prefix': ['dr', 'prof'],
                    'multi_author_split': ['och', 'med'],
                    'reject_words': ['ljudbok', 'ljudböcker', 'ljudbocker'],
                    'comic_genres': ['serier', 'seriealbum', 'tecknade serier', 'manga']},
}

def month_language_picker(table: list, browser_languages: list | tuple = ()) -> list:
    """ The languages for the month name picker, those in the month name table first, in table order,
        then the other built-in languages, those the browser asks for (codes like 'sk' or 'en_us') first,
        each sorted by translated name. Before "Show all" the picker shows the languages in the table
        and those the browser asks for.
        A language in the table takes its month names from the table, so edits and languages
        added by hand keep their names when switched off and on again.
        Season names and words are the built-in ones, seasons.json and the settings
        have no languages to take them from.
        Returns [{'locale', 'label', 'months', 'seasons', 'words', 'selected', 'shown'}],
        months being 12 [long, short] pairs, seasons {name: month},
        words {setting in lowercase: [words]} as in LANGUAGE_WORDS """
    seasons = {locale.lower(): names for locale, names in SEASON_NAMES.items()}
    words = {locale.lower(): lists for locale, lists in LANGUAGE_WORDS.items()}
    builtin = {locale.lower(): (name, months) for locale, name, months in MONTH_LANGUAGES}
    wanted = {lang.split('_')[0].lower() for lang in browser_languages}
    selected = []
    seen = set()
    if table:
        for idx, locale in enumerate(table[0]):
            if locale.lower() in seen or idx + 1 >= len(table[0]):
                continue
            seen.add(locale.lower())
            name = builtin.get(locale.lower(), (None, None))[0]
            selected.append({
                'locale': locale,
                'label': i18n.gettext(name) if name else locale,
                'months': [[row[idx], row[idx + 1]] for row in table[1:13]],
                'seasons': seasons.get(locale.lower(), {}),
                'words': words.get(locale.lower(), {}),
                'selected': True,
                'shown': True,
            })
    others = []
    for locale, name, months in MONTH_LANGUAGES:
        if locale.lower() not in seen:
            others.append({
                'locale': locale,
                'label': i18n.gettext(name),
                'months': [list(pair) for pair in months],
                'seasons': seasons.get(locale.lower(), {}),
                'words': words.get(locale.lower(), {}),
                'selected': False,
                'shown': locale.split('_')[0].lower() in wanted,
            })
    others.sort(key=lambda lang: (not lang['shown'], lang['label'].lower()))
    return selected + others
