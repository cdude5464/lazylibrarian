#  This file is part of Lazylibrarian.
#
#  Lazylibrarian is free software':'you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Lazylibrarian is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Lazylibrarian.  If not, see <http://www.gnu.org/licenses/>.

import logging
import re
import traceback

from rapidfuzz import fuzz
from rapidfuzz.utils import default_process

from lazylibrarian import database
from lazylibrarian.anna_download_policy import (
    ANNA_AUTH_FAILURES, ANNA_PARTNER_UNAVAILABLE, anna_account_failure, anna_file_retry_due,
)
from lazylibrarian.common import only_punctuation
from lazylibrarian.calibre_failure_policy import calibre_command_crashed
from lazylibrarian.ebook_identity import ebook_graphic_volume_unverified, ebook_volume_conflict
from lazylibrarian.config2 import CONFIG
from lazylibrarian.downloadmethods import (
    direct_dl_method,
    irc_dl_method,
    nzb_dl_method,
    tor_dl_method,
)
from lazylibrarian.formatter import check_int, get_list, now, replace_all, unaccented
from lazylibrarian.matchguard import weak_author_extra_title_words
from lazylibrarian.notifiers import custom_notify_snatch, notify_snatch, notify_text
from lazylibrarian.providers import get_searchterm
from lazylibrarian.subtitle_search import exact_primary_result
from lazylibrarian.scheduling import SchedulerCommand, schedule_job
from lazylibrarian.webshare import valid_ident


_AUDIOBOOK_FORMAT_TAGS = (
    r'mp3|m4a|m4b|aac|flac|ogg|opus|wav|wma|'
    r'64|96|128|192|256|320|kbps|kbit|vbr|cbr|variable|'
    r'unabridged|abridged'
)


def _audiobook_failed_title_key(title):
    """Normalize volatile audiobook result labels for failed-source comparison."""
    title = unaccented(title or '', only_ascii=False).lower()
    title = re.sub(rf'\[({_AUDIOBOOK_FORMAT_TAGS})[^\]]*\]', ' ', title)
    title = re.sub(rf'\(({_AUDIOBOOK_FORMAT_TAGS})[^\)]*\)', ' ', title)
    title = replace_all(title, {'...': ' ', '.': ' ', '&': ' ', '=': ' ', '?': ' ', '$': 's', '+': ' ',
                                '"': ' ', ',': ' ', '*': ' ', ':': ' ', ';': ' ', '\'': ' ',
                                '!': ' ', '-': ' ', '_': ' ', '#': ' ', '(': ' ', ')': ' ',
                                '[': ' ', ']': ' '})
    return ' '.join(title.split())


def _reject_word_tokens(value):
    return set(re.findall(r'[a-z0-9]+', unaccented(value or '', only_ascii=False).lower()))


def _reject_word_text(value):
    return ' '.join(re.findall(r'[a-z0-9]+', unaccented(value or '', only_ascii=False).lower()))


def _reject_word_matches(word, result_title, author, title):
    word = (word or '').strip().lower()
    if not word:
        return False
    word_text = _reject_word_text(word)
    word_tokens = set(word_text.split())
    if len(word_tokens) == 1:
        word = next(iter(word_tokens))
        result_words = _reject_word_tokens(result_title)
        if word not in result_words:
            return False
        return word not in _reject_word_tokens(author) and word not in _reject_word_tokens(title)
    if not word_text:
        return False
    result_text = f" {_reject_word_text(result_title)} "
    author_text = f" {_reject_word_text(author)} "
    title_text = f" {_reject_word_text(title)} "
    return (
        f" {word_text} " in result_text
        and f" {word_text} " not in author_text
        and f" {word_text} " not in title_text
    )


def _normalize_book_language(value):
    language = unaccented(value or '', only_ascii=False).strip().lower().replace('_', '-')
    if not language or language == 'unknown':
        return ''
    primary = language.split('-', 1)[0].strip()
    aliases = {
        'eng': 'en',
        'english': 'en',
        'nld': 'nl',
        'dut': 'nl',
        'dutch': 'nl',
        'ita': 'it',
        'italian': 'it',
        'pol': 'pl',
        'polish': 'pl',
        'deu': 'de',
        'ger': 'de',
        'german': 'de',
        'fra': 'fr',
        'fre': 'fr',
        'french': 'fr',
        'spa': 'es',
        'spanish': 'es',
    }
    return aliases.get(primary, primary)


def _expected_book_language(db, book):
    for key in ('BookLang', 'bookLang', 'booklang'):
        if book.get(key):
            return book.get(key)
    bookid = book.get('bookid') or book.get('BookID')
    if bookid:
        row = db.match('SELECT BookLang from books WHERE BookID=?', (bookid,))
        row_language = _row_value(row, 'BookLang')
        if row_language:
            return row_language
    from lazylibrarian.booklanguages import anna_search_languages
    search_languages = (CONFIG['ANNA_SEARCH_LANG'] or '').strip()
    if search_languages.casefold() == 'auto':
        search_languages = ''
    try:
        import_languages = CONFIG['IMP_PREFLANG'] or ''
    except KeyError:
        import_languages = ''
    allowed = anna_search_languages(search_languages, import_languages)
    return '' if allowed.casefold() == 'any' else allowed


def _row_value(row, key):
    if not row:
        return None
    if hasattr(row, 'get'):
        return row.get(key)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return None


def _ebook_result_language_mismatch(result_language, expected_language):
    observed = _normalize_book_language(result_language)
    expected = {_normalize_book_language(item.strip()) for item in (expected_language or '').split(',')}
    # Unknown/ANY preferences leave language unconstrained, just as explicit
    # unknown book metadata does; never interpret 'auto' as a language code.
    expected -= {'', 'any', 'auto', 'all'}
    return bool(observed and expected and observed not in expected)


def _audiobook_failed_source_retryable(row):
    """Return True for failures that should not permanently blacklist a source."""
    if not row:
        return False
    if hasattr(row, 'get'):
        result = row.get('DLResult') or ''
    else:
        result = row['DLResult'] if 'DLResult' in row.keys() else ''
    result = result.lower()
    return (
        'stalled incomplete audiobook source' in result
        or ('m4b conversion failed:' in result and 'not an all-mp3 payload' in result)
        or ('m4b conversion failed:' in result and 'm4b output has' in result and 'chapters, expected' in result)
    )


def _legacy_unknown_language_failure_retryable(row, auxinfo, result):
    """Reconsider only the old Unknown-language bug against current settings."""
    if auxinfo != 'eBook':
        return False
    failure = re.fullmatch(
        r'embedded ebook metadata declares an unexpected language: ([a-z][a-z_-]*) '
        r'\(expected unknown\)', result,
    )
    bookid = _row_value(row, 'BookID')
    if not failure or not bookid:
        return False
    observed = _normalize_book_language(failure.group(1))
    if not observed:
        return False
    db = None
    try:
        db = database.DBConnection()
        if not db.match("SELECT BookLang FROM books WHERE BookID=?", (bookid,)):
            return False
        # Use the same row/default preference as current search selection.
        expected = _expected_book_language(db, {'bookid': bookid})
        return not _ebook_result_language_mismatch(observed, expected)
    except Exception:
        # Failure to inspect current preferences never authorizes a retry.
        return False
    finally:
        if db is not None:
            db.close()


def _failed_source_retryable(row, auxinfo, author='', title=''):
    """Return True when a failed wanted row should not permanently suppress the same source."""
    if not row:
        return False
    if hasattr(row, 'get'):
        provider = (row.get('NZBprov') or '').lower()
        status = row.get('Status') or ''
        result = row.get('DLResult') or ''
    else:
        provider = row['NZBprov'].lower() if 'NZBprov' in row.keys() and row['NZBprov'] else ''
        status = row['Status'] if 'Status' in row.keys() else ''
        result = row['DLResult'] if 'DLResult' in row.keys() else ''
    if status != 'Failed':
        return False
    if (auxinfo == 'eBook' and str(_row_value(row, 'Source') or '').casefold() == 'direct'
            and str(_row_value(row, 'NZBmode') or '').casefold() == 'direct'
            and calibre_command_crashed(result)):
        return True
    result = result.lower()
    if provider == 'annas' and result == ANNA_PARTNER_UNAVAILABLE.lower():
        return auxinfo == 'eBook' and anna_file_retry_due(row)
    if provider == 'annas' and result in {text.lower() for text in ANNA_AUTH_FAILURES}:
        return auxinfo == 'eBook'
    if auxinfo == 'eBook' and result.removeprefix('destination: ').startswith(
            'calibre duplicate has no verified existing ebook file; source retained for reconciliation'):
        return True
    if _legacy_unknown_language_failure_retryable(row, auxinfo, result):
        return True
    # A pre-add configuration refusal says nothing about source quality.
    # Reconsider it after configuration repair; download policy gates still run.
    if result == 'refusing qbittorrent add without an explicit provider share policy':
        return True
    if provider == 'annas' and (
            'fast-download limit reached' in result
            or 'rate limited' in result
            or 'download limit' in result
            or 'error status: 429' in result
            or 'error status: 409' in result):
        return True
    failed_reject = re.search(r'\bcontains\s+(.+?)\s*$', result)
    if failed_reject and not _reject_word_matches(failed_reject.group(1), result, author, title):
        return True
    return auxinfo == 'AudioBook' and _audiobook_failed_source_retryable(row)


def _audiobook_size_matches(stored_size, result_size):
    """Compare processed-source sizes in MB, failing closed when size evidence is absent."""
    try:
        stored = float(stored_size)
        current = round(float(check_int(result_size, 1000)) / 1048576, 2)
    except (TypeError, ValueError):
        return True
    if stored <= 0 or current <= 0:
        return True
    return abs(stored - current) <= max(1.0, max(stored, current) * 0.01)


def _audiobook_failed_source_blocks_result(db, bookid, auxinfo, result_title, result_size):
    """Return the failed wanted row that blocks a known-bad audiobook source."""
    if auxinfo != 'AudioBook':
        return None
    failed_titles = db.select("SELECT NZBtitle,NZBprov,DLResult,NZBsize from wanted "
                              "WHERE BookID=? and AuxInfo=? "
                              "and Status='Failed' "
                              "and (DLResult like '%single-file MP3%' "
                              "or DLResult like 'Rejected stalled audiobook torrent%' "
                              "or DLResult like 'Rejected % audiobook source before transfer' "
                              "or DLResult like 'Rejected repeated previously failed audiobook source%' "
                              "or DLResult like 'M4B conversion failed:%')",
                              (bookid, auxinfo))
    result_title_key = _audiobook_failed_title_key(result_title)
    for failed_title in failed_titles:
        if _audiobook_failed_source_retryable(failed_title):
            continue
        if result_title_key and result_title_key == _audiobook_failed_title_key(
                failed_title['NZBtitle']) and _audiobook_size_matches(
                failed_title['NZBsize'], result_size):
            return failed_title
    return None


def _anna_failure_blocks(db, identifier, auxinfo, author='', title=''):
    """A retryable failure cannot hide another manual/content block."""
    failures = db.select("SELECT * FROM wanted WHERE lower(NZBurl)=? AND Status='Failed'",
                         (str(identifier).lower(),))
    return any(not _failed_source_retryable(row, auxinfo, author, title) for row in failures)


def process_result_list(resultlist, book, searchtype, source):
    """ Separated this out into two functions
        1. get the "best" match
        2. if over match threshold, send it to downloader
        This lets us try several searchtypes and stop at the first successful one
        and we can combine results from tor/nzb searches in one task
        Return 0 if not found, 1 if already snatched, 2 if we found it
    """
    match = find_best_result(resultlist, book, searchtype, source)
    if match:
        score = match[0]
        # resultTitle = match[1]
        # newValueDict = match[2]
        # controlValueDict = match[3]
        # dlpriority = match[4]

        if score < CONFIG.get_int('MATCH_RATIO'):
            return 0
        return download_result(match, book)
    return 0


def find_best_result(resultlist, book, searchtype, source):
    """ resultlist: collated results from search providers
        book:       the book we want to find
        searchtype: book, magazine, shortbook, audiobook etc.
        source:     nzb, tor, rss, irc, direct
        return:     highest scoring match, or None if no match
    """
    # noinspection PyBroadException
    logger = logging.getLogger(__name__)
    fuzzlogger = logging.getLogger('special.fuzz')
    db = database.DBConnection()
    highest = None
    try:
        # '0': '', '1': '', '2': '', '3': '', '4': '', '5': '', '6': '', '7': '', '8': '', '9': '',
        dictrepl = {'...': '', '.': ' ', ' & ': ' ', ' = ': ' ', '?': '', '$': 's', ' + ': ' ', '"': '',
                    ',': ' ', '*': '', '(': '', ')': '', '[': '', ']': '', '#': '', '\'': '',
                    ':': '', '!': '', '-': ' ', r'\s\s': ' '}

        dic = {'...': '', '.': ' ', ' & ': ' ', ' = ': ' ', '?': '', '$': 's', ' + ': ' ', '"': '',
               ',': '', '*': '', ':': '.', ';': '', '\'': '', '-': ' '}

        if source == 'rss':
            author, title = get_searchterm(book, searchtype)
        else:
            author = unaccented(replace_all(book['authorName'], dic), only_ascii=False)
            title = unaccented(replace_all(
                re.sub(r"\s*\([^()]*#\s*\d+(?:\.\d+)?\)\s*$", "", book['bookName']),
                dic), only_ascii=False)

        if 'short' in searchtype and '(' in title:
            title = title.split('(')[0].strip()

        # Goodreads appends series/position metadata to the displayed title.
        # It is not part of the work title and should not lower a valid ebook's
        # score (e.g. Elantris (Elantris #1) versus Elantris).
        title = re.sub(r"\s*\([^()]*#\s*\d+(?:\.\d+)?\)\s*$", "", title).strip()

        if book['library'] == 'AudioBook':
            reject_list = get_list(CONFIG['REJECT_AUDIO'], ',')
            maxsize = CONFIG.get_int('REJECT_MAXAUDIO')
            minsize = CONFIG.get_int('REJECT_MINAUDIO')
            auxinfo = 'AudioBook'

        else:  # elif book['library'] == 'eBook':
            reject_list = get_list(CONFIG['REJECT_WORDS'], ',')
            maxsize = CONFIG.get_int('REJECT_MAXSIZE')
            minsize = CONFIG.get_int('REJECT_MINSIZE')
            auxinfo = 'eBook'

        # Language tags that appear in release names, mapped to the set of
        # IMP_PREFLANG values each one satisfies.  Only unambiguous indicators:
        # two-letter codes (en, fr, de ...) are too common as English words.
        _LANG_TO_PREFLANG = {
            'english': {'en', 'eng', 'english'},
            'eng': {'en', 'eng', 'english'},
            'french': {'fr', 'fre', 'fra', 'french'},
            'fre': {'fr', 'fre', 'fra', 'french'},
            'fra': {'fr', 'fre', 'fra', 'french'},
            'german': {'de', 'ger', 'deu', 'german'},
            'ger': {'de', 'ger', 'deu', 'german'},
            'deu': {'de', 'ger', 'deu', 'german'},
            'spanish': {'es', 'spa', 'spanish'},
            'spa': {'es', 'spa', 'spanish'},
            'italian': {'it', 'ita', 'italian'},
            'ita': {'it', 'ita', 'italian'},
            'swedish': {'sv', 'swe', 'swedish'},
            'swe': {'sv', 'swe', 'swedish'},
            'norwegian': {'no', 'nor', 'norwegian'},
            'nor': {'no', 'nor', 'norwegian'},
            'danish': {'da', 'dan', 'danish'},
            'dan': {'da', 'dan', 'danish'},
            'dutch': {'nl', 'dut', 'nld', 'dutch'},
            'dut': {'nl', 'dut', 'nld', 'dutch'},
            'nld': {'nl', 'dut', 'nld', 'dutch'},
            'portuguese': {'pt', 'por', 'portuguese'},
            'por': {'pt', 'por', 'portuguese'},
            'russian': {'ru', 'rus', 'russian'},
            'rus': {'ru', 'rus', 'russian'},
            'polish': {'pl', 'pol', 'polish'},
            'pol': {'pl', 'pol', 'polish'},
            'czech': {'cs', 'cze', 'ces', 'czech'},
            'cze': {'cs', 'cze', 'ces', 'czech'},
            'ces': {'cs', 'cze', 'ces', 'czech'},
            'finnish': {'fi', 'fin', 'finnish'},
            'fin': {'fi', 'fin', 'finnish'},
            'hungarian': {'hu', 'hun', 'hungarian'},
            'hun': {'hu', 'hun', 'hungarian'},
            'turkish': {'tr', 'tur', 'turkish'},
            'tur': {'tr', 'tur', 'turkish'},
            'japanese': {'ja', 'jpn', 'japanese'},
            'jpn': {'ja', 'jpn', 'japanese'},
            'chinese': {'zh', 'chi', 'zho', 'chinese'},
            'chi': {'zh', 'chi', 'zho', 'chinese'},
            'zho': {'zh', 'chi', 'zho', 'chinese'},
            'korean': {'ko', 'kor', 'korean'},
            'kor': {'ko', 'kor', 'korean'},
            'arabic': {'ar', 'ara', 'arabic'},
            'ara': {'ar', 'ara', 'arabic'},
            'romanian': {'ro', 'ron', 'romanian'},
            'ron': {'ro', 'ron', 'romanian'},
            'greek': {'el', 'ell', 'greek'},
            'ell': {'el', 'ell', 'greek'},
        }
        preflang_lower = {v.strip().lower() for v in get_list(CONFIG['IMP_PREFLANG'], ',') if v.strip()}
        check_lang = preflang_lower and 'all' not in preflang_lower

        if source == 'nzb':
            prefix = 'nzb'
        else:  # rss and direct providers return same names as torrents
            prefix = 'tor_'

        logger.debug(f'Searching {len(resultlist)} {source} results for best {auxinfo} match')
        matches = []
        ignored_messages = []
        expected_language = _expected_book_language(db, book) if auxinfo == 'eBook' else ''
        for res in resultlist:
            result_title = unaccented(replace_all(res[f"{prefix}title"], dictrepl),
                                      only_ascii=False).strip()
            result_title = ' '.join(result_title.split())  # remove extra whitespace
            only_title = result_title.replace(author, '')
            if not only_title or only_punctuation(only_title):
                book_match = fuzz.token_set_ratio(title, result_title, processor=default_process)
            else:
                book_match = fuzz.token_set_ratio(title.replace(author, ''), only_title, processor=default_process)
            title_only_result = 'booksearch' in res and res['booksearch'] == 'bibliotik'
            if title_only_result:
                # bibliotik only returns book title, not author name
                fuzzlogger.debug("bibliotik, ignoring author fuzz")
                author_match = 100
            else:
                author_match = fuzz.token_set_ratio(author, result_title, processor=default_process)

            fuzzlogger.debug(f"{source.upper()} author/book Match: {author_match}/{book_match} {result_title} "
                             f"at {res[prefix + 'prov']}")

            rejected = False
            if auxinfo == 'eBook' and (ebook_volume_conflict(book.get('bookName', ''), res[f"{prefix}title"])
                    or ebook_graphic_volume_unverified(book.get('bookName', ''), res[f"{prefix}title"])):
                rejected = True
                logger.debug('Rejecting ebook result without compatible requested format/volume identity')
            if auxinfo == 'eBook':
                guard_author_match = 0 if title_only_result else author_match
                extra_words = weak_author_extra_title_words(
                    result_title,
                    author=author,
                    title=title,
                    subtitle=book.get('bookSub', ''),
                    author_match=guard_author_match,
                    match_ratio=CONFIG.get_int('MATCH_RATIO'),
                    format_words=CONFIG['EBOOK_TYPE'],
                    prefer_words=CONFIG['PREFER_WORDS'],
                )
                if extra_words:
                    rejected = True
                    logger.debug(
                        f"Rejecting {result_title}, weak author match ({round(guard_author_match, 2)}%) and extra "
                        f"title words [{', '.join(extra_words)}]"
                    )
                result_language = res.get(f"{prefix}lang") or res.get('tor_lang') or ''
                if not rejected and _ebook_result_language_mismatch(result_language, expected_language):
                    rejected = True
                    logger.debug(
                        f"Rejecting {result_title}, language {result_language} does not match expected "
                        f"{expected_language}"
                    )

            url = res[f"{prefix}url"]
            if not url:
                rejected = True
                logger.debug(f"Rejecting {result_title}, no URL found")

            if (not rejected and source == 'direct' and res.get('tor_prov') == 'annas'
                    and _anna_failure_blocks(db, url, auxinfo, author, title)):
                # This content/manual block is mandatory even if the general
                # configurable failed-source blacklist has been disabled.
                rejected = True
                logger.debug('Rejecting Anna file with a non-retryable failure')

            if not rejected and CONFIG.get_bool('BLACKLIST_FAILED'):
                cmd = "SELECT * from wanted WHERE NZBurl=? and Status='Failed'"
                args = (url,)
                if res.get('tor_type', '') == 'irc':
                    cmd += " and NZBTitle=?"
                    args += (res['tor_title'],)
                blacklisted = db.match(cmd, args)
                if blacklisted:
                    if _failed_source_retryable(blacklisted, auxinfo, author, title):
                        logger.debug(f"Allowing retry of {res[prefix + 'title']}, previous failure was "
                                     f"retryable at {blacklisted['NZBprov']}")
                    else:
                        logger.debug(f"Rejecting {res[prefix + 'title']}, url blacklisted (Failed) at "
                                     f"{blacklisted['NZBprov']}")
                        rejected = True
                if not rejected:
                    blacklisted = db.match("SELECT * from wanted WHERE NZBprov=? and NZBtitle=? "
                                           "and Status='Failed'",
                                           (res[f"{prefix}prov"], res[f"{prefix}title"]))
                    if blacklisted:
                        if _failed_source_retryable(blacklisted, auxinfo, author, title):
                            logger.debug(f"Allowing retry of {res[prefix + 'title']}, previous title failure was "
                                         f"retryable at {blacklisted['NZBprov']}")
                        else:
                            logger.debug(f"Rejecting {res[prefix + 'title']}, title blacklisted (Failed) at "
                                         f"{blacklisted['NZBprov']}")
                            rejected = True
                if not rejected and auxinfo == 'AudioBook':
                    failed_title = _audiobook_failed_source_blocks_result(
                        db, book['bookid'], auxinfo, res[f"{prefix}title"], res[f"{prefix}size"])
                    if failed_title:
                        logger.debug(f"Rejecting {res[prefix + 'title']}, normalized audiobook title "
                                     f"blacklisted (Failed audiobook source) at {failed_title['NZBprov']}")
                        rejected = True

            if not rejected and auxinfo == 'AudioBook':
                failed_title = _audiobook_failed_source_blocks_result(
                    db, book['bookid'], auxinfo, res[f"{prefix}title"], res[f"{prefix}size"])
                if failed_title:
                    logger.debug(f"Rejecting {res[prefix + 'title']}, normalized audiobook title "
                                 f"blacklisted (Helper-rejected audiobook source) at {failed_title['NZBprov']}")
                    rejected = True

            if not rejected and CONFIG.get_bool('BLACKLIST_PROCESSED'):
                cmd = "SELECT * from wanted WHERE NZBurl=?"
                args = (url,)
                if res.get('tor_type', '') == 'irc':
                    cmd += " and NZBTitle=?"
                    args += (res['tor_title'],)
                blacklisted = db.match(cmd, args)
                if blacklisted:
                    if _failed_source_retryable(blacklisted, auxinfo, author, title):
                        logger.debug(f"Allowing retry of {res[prefix + 'title']}, previous processed-list match "
                                     f"was retryable at {blacklisted['NZBprov']}")
                    else:
                        logger.debug(f"Rejecting {res[prefix + 'title']}, url blacklisted ({blacklisted['Status']}) "
                                     f"at {blacklisted['NZBprov']}")
                        rejected = True
                if not rejected:
                    blacklisted = db.match('SELECT * from wanted WHERE NZBprov=? and NZBtitle=?',
                                           (res[f"{prefix}prov"], res[f"{prefix}title"]))
                    if blacklisted:
                        if _failed_source_retryable(blacklisted, auxinfo, author, title):
                            logger.debug(f"Allowing retry of {res[prefix + 'title']}, previous processed-list title "
                                         f"match was retryable at {blacklisted['NZBprov']}")
                        else:
                            logger.debug(
                                f"Rejecting {res[prefix + 'title']}, title blacklisted ({blacklisted['Status']}) "
                                f"at {blacklisted['NZBprov']}")
                            rejected = True
                if not rejected and auxinfo == 'AudioBook':
                    processed_titles = db.select("SELECT NZBtitle,NZBprov,Status,NZBsize from wanted WHERE BookID=? "
                                                 "and AuxInfo=? and NZBprov=? and Status='Processed'",
                                                 (book['bookid'], auxinfo, res[f"{prefix}prov"]))
                    result_title_key = _audiobook_failed_title_key(res[f"{prefix}title"])
                    for processed_title in processed_titles:
                        if result_title_key and result_title_key == _audiobook_failed_title_key(
                                processed_title['NZBtitle']) and _audiobook_size_matches(
                                processed_title['NZBsize'], res[f"{prefix}size"]):
                            logger.debug(f"Rejecting {res[prefix + 'title']}, normalized audiobook title "
                                         f"blacklisted (Processed audiobook source) at "
                                         f"{processed_title['NZBprov']}")
                            rejected = True
                            break

            if not rejected and source == 'rss':
                if searchtype in ['book', 'shortbook'] and 'E' not in res['types']:
                    rejected = True
                    ignore_msg = f"Ignoring {res[prefix + 'prov']} for eBook"
                    if ignore_msg not in ignored_messages:
                        ignored_messages.append(ignore_msg)
                        logger.debug(ignore_msg)
                if 'audio' in searchtype and 'A' not in res['types']:
                    rejected = True
                    ignore_msg = f"Ignoring {res[prefix + 'prov']} for AudioBook"
                    if ignore_msg not in ignored_messages:
                        ignored_messages.append(ignore_msg)
                        logger.debug(ignore_msg)
                if 'mag' in searchtype and 'M' not in res['types']:
                    rejected = True
                    ignore_msg = f"Ignoring {res[prefix + 'prov']} for Magazine"
                    if ignore_msg not in ignored_messages:
                        ignored_messages.append(ignore_msg)
                        logger.debug(ignore_msg)

            if not rejected:
                if source == 'irc':
                    if not url.startswith('!'):
                        rejected = True
                elif res[prefix + 'prov'] in ['zlibrary', 'soulseek']:
                    if '^' not in url:
                        rejected = True
                elif res[prefix + 'prov'] == 'webshare':
                    rejected = not valid_ident(url)
                elif res[prefix + 'prov'] == 'annas':
                    # annas gives us an id in hex, verify we got hex digits
                    try:
                        _ = int(url, 16)
                    except ValueError:
                        rejected = True
                elif not url.startswith('http') and not url.startswith('magnet'):
                    rejected = True
                if rejected:
                    logger.debug(f"Rejecting {res[prefix + 'title']}, invalid URL [{url}]")

            if not rejected:
                for word in reject_list:
                    if _reject_word_matches(word, result_title, author, title):
                        rejected = True
                        logger.debug(f"Rejecting {result_title}, contains {word}")
                        break

            if not rejected and check_lang:
                title_words = get_list(title.lower())
                author_words = get_list(author.lower())
                for word in get_list(result_title.lower()):
                    if word in title_words or word in author_words:
                        continue
                    mapped = _LANG_TO_PREFLANG.get(word)
                    if mapped and not mapped.intersection(preflang_lower):
                        rejected = True
                        logger.debug(f"Rejecting {result_title}, language '{word}' "
                                     f"not in preferred languages")
                        break

            if not rejected:
                result_words = set(get_list(result_title.lower()))
                ebook_types = {t.lower() for t in get_list(CONFIG['EBOOK_TYPE'])}
                audio_types = {t.lower() for t in get_list(CONFIG['AUDIOBOOK_TYPE'])}
                format_tokens = result_words & (ebook_types | audio_types)
                if format_tokens:
                    if auxinfo == 'eBook' and format_tokens <= audio_types:
                        rejected = True
                        logger.debug(f"Rejecting {result_title}, format tokens are audiobook types")
                    elif auxinfo == 'AudioBook' and format_tokens <= ebook_types:
                        rejected = True
                        logger.debug(f"Rejecting {result_title}, format tokens are ebook types")

            size_temp = check_int(res[f"{prefix}size"], 1000)  # Need to cater for when this is NONE (Issue 35)
            size = round(float(size_temp) / 1048576, 2)

            if not rejected and maxsize and size > maxsize:
                rejected = True
                logger.debug(f"Rejecting {result_title}, too large ({size}Mb)")

            if not rejected and minsize and size < minsize:
                rejected = True
                logger.debug(f"Rejecting {result_title}, too small ({size}Mb)")

            if not rejected:
                min_seeders = CONFIG.get_int('MIN_SEEDERS')
                seeders = check_int(res.get('seeders', -1), -1)
                if min_seeders and seeders >= 0 and seeders < min_seeders:
                    rejected = True
                    logger.debug(f"Rejecting {result_title}, only {seeders} seeders (minimum {min_seeders})")

            if not rejected:
                bookid = book['bookid']

                if source == 'nzb':
                    mode = res.get('nzbmode', '')  # nzb, torznab
                else:
                    mode = res.get('tor_type', '')  # torrent, magnet, nzb(from rss), direct, irc

                control_value_dict = {"NZBurl": url}
                new_value_dict = {
                    "NZBprov": res[f"{prefix}prov"],
                    "BookID": bookid,
                    "NZBdate": now(),  # when we asked for it
                    "NZBsize": size,
                    "NZBtitle": res[f"{prefix}title"],  # was resultTitle,
                    "NZBmode": mode,
                    "AuxInfo": auxinfo,
                    "Label": res.get('label', ''),
                    "Status": "Matched"
                }
                if source == 'irc':
                    new_value_dict['NZBprov'] = res['tor_feed']
                    new_value_dict['NZBtitle'] = res[f"{prefix}title"]

                if author_match >= CONFIG.get_int('MATCH_RATIO'):
                    score = book_match
                else:
                    score = (book_match + author_match) / 2  # as a percentage
                # lose a point for each unwanted word in the title so we get the closest match
                # but for rss ignore anything at the end in square braces [keywords, genres etc]
                if source == 'rss':
                    wordlist = get_list(result_title.rsplit('[', 1)[0].lower())
                else:
                    wordlist = get_list(result_title.lower())
                words = [x for x in wordlist if x not in get_list(author.lower())]
                words = [x for x in words if x not in get_list(title.lower())]
                typelist = ''

                if new_value_dict['AuxInfo'] == 'eBook':
                    words = [x for x in words if x not in get_list(CONFIG['EBOOK_TYPE'])]
                    typelist = get_list(CONFIG['EBOOK_TYPE'])
                elif new_value_dict['AuxInfo'] == 'AudioBook':
                    words = [x for x in words if x not in get_list(CONFIG['AUDIOBOOK_TYPE'])]
                    typelist = get_list(CONFIG['AUDIOBOOK_TYPE'])

                # Don't treat wanted language as noise, and ignore separator "words" (#3100)
                preferred_tags = {w for w, langs in _LANG_TO_PREFLANG.items() if langs & preflang_lower}
                words = [x for x in words if x not in preferred_tags and x not in ('by', '/', '-')]

                score -= len(words)
                # A stored subtitle is optional only for an exact complete
                # author + primary-title result. All guards above still use
                # the original full book, including edition/volume/language.
                if exact_primary_result(book, res[f"{prefix}title"], typelist):
                    primary_language = expected_language or _expected_book_language(db, book)
                    result_language = res.get(f"{prefix}lang") or res.get('tor_lang') or ''
                    if not _ebook_result_language_mismatch(result_language, primary_language):
                        score = max(score, 100)
                # prioritise titles that include the ebook types we want
                # add more points for booktypes nearer the left in the list
                # eg if epub, mobi, pdf  add 3 points if epub found, 2 for mobi, 1 for pdf
                booktypes = [x for x in wordlist if x in typelist]
                if booktypes:
                    typelist = list(reversed(typelist))
                    for item in booktypes:
                        for i in [i for i, x in enumerate(typelist) if x == item]:
                            score += i + 1

                # now do the same for words in the "preferred words" list"
                preferwords = get_list(CONFIG['PREFER_WORDS'])
                if preferwords:
                    preferwords = list(reversed(preferwords))
                    for word in wordlist:
                        for i in [i for i, x in enumerate(preferwords) if x == word]:
                            score += i + 1

                # now do the same for words in preferred language list, not weighted, 1 point if match
                if preferred_tags:
                    for word in wordlist:
                        if word in preferred_tags:
                            score += 1
                            break

                matches.append([score, new_value_dict, control_value_dict, res['priority'],
                                check_int(res.get('seeders', 0), 0)])

        if matches:
            highest = max(matches, key=lambda s: (weighted_score(s), check_int(s[3], 0),
                                                   check_int(s[4], 0)))
            score = highest[0]
            new_value_dict = highest[1]
            # controlValueDict = highest[2]
            dlpriority = highest[3]

            if score < CONFIG.get_int('MATCH_RATIO'):
                logger.info(
                    f"Nearest match ({round(score, 2)}%): {new_value_dict['NZBtitle']} using {searchtype} search for "
                    f"{book['authorName']} {book['bookName']}")
            else:
                logger.info(
                    f"Best match ({round(score, 2)}%): {new_value_dict['NZBtitle']} using {searchtype} search, "
                    f"{new_value_dict['NZBprov']} priority {dlpriority}")
        else:
            logger.debug(f"No {source} found for [{book['searchterm']}] using searchtype {searchtype}")
    except Exception:
        logger.error(f'Unhandled exception in find_best_result: {traceback.format_exc()}')

    db.close()
    return highest


def weighted_score(s):
    # priority is already 0-100-ish per provider; normalize it down to a modest bonus
    priority_bonus = (check_int(s[3], 0) / 100) * CONFIG.get_int('PRIORITY_WEIGHT')
    return check_int(s[0], 0) + priority_bonus


def download_result(match, book, failure_details=None):
    """ match:  best result from search providers
        book:   book we are downloading (needed for reporting author name)
        return: 0 if failed to snatch
                1 if already snatched
                2 if we snatched it
    """
    # noinspection PyBroadException
    logger = logging.getLogger(__name__)
    db = database.DBConnection()
    try:
        new_value_dict = match[1]
        control_value_dict = match[2]

        # It's possible to get book and wanted tables "Snatched" status out of sync
        # for example if a user marks a book as "Wanted" after a search task snatches it and before postprocessor runs
        # so check status in both tables here
        snatched = db.match("SELECT BookID from wanted WHERE BookID=? and AuxInfo=? and Status='Snatched'",
                            (new_value_dict["BookID"], new_value_dict["AuxInfo"]))
        if snatched:
            logger.debug(
                f"{new_value_dict['AuxInfo']} {book['authorName']} {book['bookName']} "
                f"already marked snatched in wanted table")
            return 1  # someone else already found it

        if new_value_dict["AuxInfo"] == 'eBook':
            snatched = db.match("SELECT BookID from books WHERE BookID=? and Status='Snatched'",
                                (new_value_dict["BookID"],))
        else:
            snatched = db.match("SELECT BookID from books WHERE BookID=? and AudioStatus='Snatched'",
                                (new_value_dict["BookID"],))
        if snatched:
            logger.debug(
                f"{new_value_dict['AuxInfo']} {book['authorName']} {book['bookName']} "
                f"already marked snatched in book table")
            return 1  # someone else already found it

        db.upsert("wanted", new_value_dict, control_value_dict)
        label = new_value_dict.get('Label', '')
        if new_value_dict['NZBmode'] == 'direct':
            snatch, res = direct_dl_method(new_value_dict["BookID"], new_value_dict["NZBtitle"],
                                           control_value_dict["NZBurl"], new_value_dict["AuxInfo"],
                                           new_value_dict['NZBprov'])
        elif new_value_dict['NZBmode'] == 'irc':
            snatch, res = irc_dl_method(new_value_dict["BookID"], new_value_dict["NZBtitle"],
                                        control_value_dict["NZBurl"], new_value_dict["AuxInfo"],
                                        new_value_dict['NZBprov'])
        elif new_value_dict['NZBmode'] in ["torznab", "torrent", "magnet"]:
            snatch, res = tor_dl_method(new_value_dict["BookID"], new_value_dict["NZBtitle"],
                                        control_value_dict["NZBurl"], new_value_dict["AuxInfo"], label,
                                        new_value_dict['NZBprov'], book.get('authorName', ''),
                                        book.get('bookName', ''))
        elif new_value_dict['NZBmode'] == 'nzb':
            snatch, res = nzb_dl_method(new_value_dict["BookID"], new_value_dict["NZBtitle"],
                                        control_value_dict["NZBurl"], new_value_dict["AuxInfo"], label)
        else:
            res = f"Unhandled NZBmode [{new_value_dict['NZBmode']}] for {control_value_dict['NZBurl']}"
            logger.error(res)
            snatch = 0

        if snatch:
            logger.info(
                f"Downloading {new_value_dict['AuxInfo']} {new_value_dict['NZBtitle']} from "
                f"{new_value_dict['NZBprov']}")
            custom_notify_snatch(f"{new_value_dict['BookID']} {new_value_dict['AuxInfo']}")
            notify_snatch(notify_text(new_value_dict['NZBtitle'], CONFIG.disp_name(new_value_dict['NZBprov']),
                                      new_value_dict['AuxInfo']))
            # at this point we could add NZBprov to the blocklist with a short timeout, a second or two?
            # This would implement a round-robin search system. Blocklist with an incremental counter.
            # If number of active providers == number blocklisted, so no unblocked providers are left,
            # either sleep for a while, or unblock the one with the lowest counter.
            schedule_job(SchedulerCommand.START, target='PostProcessor')
            return 2  # we found it
        db.action("UPDATE wanted SET status='Failed',DLResult=? WHERE NZBurl=?",
                  (res, control_value_dict["NZBurl"]))
        if failure_details is not None and new_value_dict['NZBprov'] == 'annas':
            failure_details['anna_account_hold'] = anna_account_failure(res)
        return 0
    except Exception:
        logger.error(f'Unhandled exception in download_result: {traceback.format_exc()}')
        return 0
    finally:
        db.close()
