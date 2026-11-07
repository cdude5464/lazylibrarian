#  This file is part of Lazylibrarian.
#  Lazylibrarian is free software':'you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#  Lazylibrarian is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#  You should have received a copy of the GNU General Public License
#  along with Lazylibrarian.  If not, see <http://www.gnu.org/licenses/>.


import logging
import math
import os
import re
import threading
import time
import traceback

import lazylibrarian
from lazylibrarian.subtitle_search import primary_title
from lazylibrarian import database
from lazylibrarian.anna_download_policy import anna_file_retry_due
from lazylibrarian.blockhandler import BLOCKHANDLER
from lazylibrarian.config2 import CONFIG
from lazylibrarian.formatter import check_int, get_list, plural, thread_name
from lazylibrarian.providers import (
    iterate_over_direct_sites,
    iterate_over_irc_sites,
    iterate_over_rss_sites,
    iterate_over_torrent_sites,
    iterate_over_znab_sites,
)
from lazylibrarian.resultlist import _failed_source_retryable, download_result, find_best_result
from lazylibrarian.telemetry import TELEMETRY


def cron_search_book():
    logger = logging.getLogger(__name__)
    if 'SEARCHALLBOOKS' not in [n.name for n in list(threading.enumerate())]:
        search_book()
    else:
        logger.debug("SEARCHALLBOOKS is already running")


def good_enough(match):
    return bool(match and int(match[0]) >= CONFIG.get_int('MATCH_RATIO'))


def _has_comic_genre(book):
    """Whether a book's genre matches the configurable comic genre list.

    Splits the book's genre string on commas and compares each token against
    the configured terms, so 'comic' does not false-positive on 'Economics'."""
    genre = (book.get('genre') or '').lower()
    if not genre:
        return False
    comic_genres = [g.strip() for g in get_list(CONFIG['COMIC_GENRES'], ',') if g.strip()]
    if not comic_genres:
        return False
    genre_tokens = [g.strip() for g in genre.split(',') if g.strip()]
    for term in comic_genres:
        term_lower = term.lower()
        for token in genre_tokens:
            if term_lower == token or term_lower in token.split():
                return True
    return False


def _search_providers(book, searchtype, rss_resultlist):
    """ Search every provider mode for book, return the good enough matches """
    logger = logging.getLogger(__name__)
    searches = []
    if CONFIG.use_nzb():
        searches.append(('nzb', 'NZB', iterate_over_znab_sites))
    if CONFIG.use_tor():
        searches.append(('tor', 'Torrent', iterate_over_torrent_sites))
    if CONFIG.use_direct():
        searches.append(('direct', 'Direct', iterate_over_direct_sites))
    if CONFIG.use_irc():
        searches.append(('irc', 'IRC', iterate_over_irc_sites))
    matches = []
    for mode, name, iterate in searches:
        resultlist, nprov = iterate(book, searchtype)
        if not nprov:
            warn_mode(mode, searchtype)
        elif resultlist:
            match = find_best_result(resultlist, book, searchtype, mode)
            if not good_enough(match):
                logger.info(f"{name} search for {book['library']} {book['searchterm']} returned no results.")
            else:
                logger.info(f"Found {name} result: {searchtype} {round(match[0], 2)}%, {match[1]['NZBprov']} "
                            f"priority {match[3]}")
                matches.append(match)
    if CONFIG.use_rss() and rss_resultlist:
        match = find_best_result(rss_resultlist, book, searchtype, 'rss')
        if not good_enough(match):
            logger.info(f"RSS search for {book['library']} {book['searchterm']} returned no results.")
        else:
            logger.info(f"Found RSS result: {searchtype} {round(match[0], 2)}%, {match[1]['NZBprov']} "
                        f"priority {match[3]}")
            matches.append(match)
    return matches


def warn_mode(mode, search_type=None):
    # A search may skip every provider in a mode because none supports its media.
    # Count configured providers here, including blocked ones, so real outages
    # still warn even when another provider only supports a different media type.
    if search_type and mode in ['tor', 'direct']:
        dltype = 'A' if 'audio' in search_type else 'E'
        names = ['KAT', 'TPB', 'TDL', 'LIME', 'ABB'] if mode == 'tor' else ['BOK', 'ANNA', 'SLSK']
        compatible = any(CONFIG.get_bool(name) and dltype in CONFIG[f'{name}_DLTYPES']
                         for name in names)
        if mode == 'direct' and not compatible:
            compatible = any(provider.get_bool('ENABLED') and dltype in provider['DLTYPES']
                             for provider in CONFIG.providers('GEN'))
        if not compatible:
            return
    # don't nag. Show warning messages no more than every 20 mins
    logger = logging.getLogger(__name__)
    timenow = int(time.time())
    if mode == 'rss':
        if check_int(lazylibrarian.TIMERS['NO_RSS_MSG'], 0) + 1200 < timenow:
            lazylibrarian.TIMERS['NO_RSS_MSG'] = timenow
        else:
            return
    elif mode == 'nzb':
        if check_int(lazylibrarian.TIMERS['NO_NZB_MSG'], 0) + 1200 < timenow:
            lazylibrarian.TIMERS['NO_NZB_MSG'] = timenow
        else:
            return
    elif mode == 'tor':
        if check_int(lazylibrarian.TIMERS['NO_TOR_MSG'], 0) + 1200 < timenow:
            lazylibrarian.TIMERS['NO_TOR_MSG'] = timenow
        else:
            return
    elif mode == 'irc':
        if check_int(lazylibrarian.TIMERS['NO_IRC_MSG'], 0) + 1200 < timenow:
            lazylibrarian.TIMERS['NO_IRC_MSG'] = timenow
        else:
            return
    elif mode == 'direct':
        if check_int(lazylibrarian.TIMERS['NO_DIRECT_MSG'], 0) + 1200 < timenow:
            lazylibrarian.TIMERS['NO_DIRECT_MSG'] = timenow
        else:
            return
    else:
        return
    logger.warning(f'No {mode} providers are available. Check config and blocklist')


def retryable_anna_history_candidates(book, due_only=False):
    """Recover previously matched sources without requiring a fresh HTML search."""
    if book.get("library") != "eBook" or not book.get("bookid"):
        return []
    db = None
    try:
        db = database.DBConnection()
        current = db.match("SELECT Status FROM books WHERE BookID=?", (book["bookid"],))
        if not current or current["Status"] != "Wanted":
            return []
        rows = db.select(
            "SELECT * FROM wanted WHERE BookID=? AND NZBprov='annas' "
            "AND NZBmode='direct' AND AuxInfo='eBook' ORDER BY rowid DESC LIMIT 50",
            (book["bookid"],))
        results, seen = [], set()
        formats = {value.strip().lower() for value in CONFIG["EBOOK_TYPE"].split(",")}
        for row in rows:
            identifier = str(row["NZBurl"] or "").lower()
            if identifier in seen:
                continue
            seen.add(identifier)
            if row["Status"] != "Failed" or not re.fullmatch(r"[0-9a-f]{32}", identifier):
                continue
            if due_only and not anna_file_retry_due(row):
                continue
            failures = db.select(
                "SELECT * FROM wanted WHERE lower(NZBurl)=? AND Status='Failed'",
                (identifier,))
            # A deliberate block or genuine content failure must not be
            # resurrected through an older retryable row for the same payload.
            if not failures or not all(_failed_source_retryable(item, "eBook") for item in failures):
                continue
            title = row["NZBtitle"] or ""
            extension = os.path.splitext(title)[1].lstrip(".").lower()
            try:
                size = float(row["NZBsize"])
            except (TypeError, ValueError):
                continue
            if extension not in formats or not math.isfinite(size) or size <= 0:
                continue
            results.append({
                "bookid": book["bookid"], "tor_prov": "annas", "tor_type": "direct",
                "tor_title": title, "tor_url": identifier,
                "tor_size": int(size * 1048576), "tor_extn": extension,
                "priority": CONFIG["ANNA_DLPRIORITY"],
            })
            if len(results) == 3:
                break
        return results
    except Exception:
        logging.getLogger(__name__).warning("Could not inspect historical Anna source evidence")
        return []
    finally:
        if db is not None:
            db.close()


def _download_candidate_matches(matches, book, direct_pool=None):
    """Try normal matches and at most three distinct Anna files this cycle.

    Reuse fetched results, but rerun the normal matcher after each failure so
    current manual/content blocks still apply. Only download_result writes a
    wanted row, so unattempted alternatives never become orphan Matched rows.
    """
    logger = logging.getLogger(__name__)
    matches = list(matches)
    attempted = set()
    anna_attempts = 0
    anna_account_hold = False
    while matches:
        try:
            highest = max(matches, key=lambda s: (weighted_score(s), check_int(s[3], 0)))
        except TypeError:
            highest = max(matches, key=lambda s: (str(s[0]), str(s[3])))
        matches.remove(highest)
        is_anna = highest[1].get('NZBprov') == 'annas' and highest[1].get('NZBmode') == 'direct'
        if is_anna:
            identity = str(highest[2].get('NZBurl') or '').lower()
            if (identity in attempted or anna_attempts >= 3 or anna_account_hold
                    or BLOCKHANDLER.is_blocked('annas')):
                continue
            db = database.DBConnection()
            try:
                field = 'AudioStatus' if book['library'] == 'AudioBook' else 'Status'
                state = db.match(f'SELECT {field} FROM books WHERE BookID=?', (book['bookid'],))
            finally:
                db.close()
            if not state or state[field] != 'Wanted':
                return 1  # A concurrent grab or user status change ends this request.
            attempted.add(identity)
            anna_attempts += 1
        logger.info(f"Requesting {book['library']} download: {round(highest[0], 2)}% "
                    f"{highest[1]['NZBprov']}: {highest[1]['NZBtitle']}")
        failure_details = {}
        result = (download_result(highest, book, failure_details=failure_details)
                  if is_anna else download_result(highest, book))
        if result > 0:
            return result
        anna_account_hold = anna_account_hold or failure_details.get('anna_account_hold', False)
        if (is_anna and direct_pool and anna_attempts < 3 and not anna_account_hold
                and not BLOCKHANDLER.is_blocked('annas')):
            pool, context, searchtype = direct_pool
            remaining = [item for item in pool if item.get('tor_prov') == 'annas'
                         and str(item.get('tor_url') or '').lower() not in attempted]
            alternative = find_best_result(remaining, context, searchtype, 'direct') if remaining else None
            if good_enough(alternative):
                matches.append(alternative)
        if matches:
            TELEMETRY.record_usage_data('SearchBook/RetryNextCandidate')
            logger.info(f"Download attempt failed; trying next validated candidate ({len(matches)} remaining)")
    return 0


def search_book(books=None, library=None):
    """
    books is a list of new books to add, or None for backlog search
    library is "eBook" or "AudioBook" or None to search all book types
    """
    TELEMETRY.record_usage_data('Search/Book')
    # Only search the requested format. Previously `library` was only used in log messages, so every
    # per-format caller (web UI, API type=, GoodReads/HardCover sync, wishlist) searched both formats
    # whenever a book was Wanted in both, doubling the queries sent to every provider.
    only = library.lower() if isinstance(library, str) else ''
    search_ebook = only != 'audiobook'
    search_audio = only != 'ebook'
    logger = logging.getLogger(__name__)
    searchinglogger = logging.getLogger('special.searching')
    searchinglogger.debug(f"search_book: {books}")
    db = database.DBConnection()
    # noinspection PyBroadException
    try:
        threadname = thread_name()
        if "SEARCH" not in threadname:
            if not books:
                thread_name("SEARCHALLBOOKS")
                threadname = "SEARCHALLBOOKS"
            else:
                thread_name("SEARCHBOOKS")

        if 'SEARCHALL' in threadname or 'API-SEARCH' in threadname or 'FORCE-SEARCH' in threadname:
            force = True
        else:
            force = False

        logger.debug(f"Storing start time for {thread_name()}")
        db.upsert("jobs", {"Start": time.time()}, {"Name": thread_name()})
        searchlist = []
        searchbooks = []

        if not books:
            # We are performing a backlog search
            cmd = ("SELECT BookID, AuthorName, Bookname, BookSub, BookAdded, books.Status, AudioStatus, "
                   "BookGenre, OtherTitles from books,authors WHERE (books.Status='Wanted' OR AudioStatus='Wanted') "
                   "and books.AuthorID = authors.AuthorID order by BookAdded desc")
            results = db.select(cmd)
            for terms in results:
                searchbooks.append(terms)
        else:
            # The user has added new books
            if library:
                logger.debug(f"Searching for {len(books)} {plural(len(books), library)}")
                searchinglogger.debug(f"{books}")
            for book in books:
                if book['bookid'] not in ['booklang', 'library', 'ignored']:
                    cmd = ("SELECT BookID, AuthorName, BookName, BookSub, books.Status, AudioStatus, "
                           "BookGenre, OtherTitles from books,authors WHERE BookID=? AND books.AuthorID = authors.AuthorID")
                    results = db.select(cmd, (book['bookid'],))
                    if results:
                        for terms in results:
                            searchbooks.append(terms)
                    else:
                        logger.debug(f"SearchBooks - BookID {book['bookid']} is not in the database")

        if len(searchbooks) == 0:
            logger.debug("No books to search for")
            db.upsert("jobs", {"Finish": time.time()}, {"Name": thread_name()})
            return

        nprov = CONFIG.total_active_providers()
        if nprov == 0:
            msg = "SearchBooks - No providers to search"
            blocked = BLOCKHANDLER.number_blocked()
            if blocked:
                msg += f" (there {plural(blocked, 'is')} {blocked} in blocklist)"
            else:
                msg += " (check you have some enabled)"
            logger.debug(msg)
            db.upsert("jobs", {"Finish": time.time()}, {"Name": thread_name()})
            return

        modelist = []
        if CONFIG.use_nzb():
            modelist.append('nzb')
        if CONFIG.use_tor():
            modelist.append('tor')
        if CONFIG.use_direct():
            modelist.append('direct')
        if CONFIG.use_rss():
            modelist.append('rss')
        if CONFIG.use_irc():
            modelist.append('irc')

        if not library:
            library = 'item'

        logger.info(
            f"Searching {nprov} {plural(nprov, 'provider')} {str(modelist)} for {len(searchbooks)} "
            f"{plural(len(searchbooks), library)}")
        logger.info(
            f"Provider Blocklist contains {BLOCKHANDLER.number_blocked()} "
            f"{plural(BLOCKHANDLER.number_blocked(), 'entry')}")

        for searchbook in searchbooks:
            if lazylibrarian.STOPTHREADS and thread_name() == "SEARCHALLBOOKS":
                logger.debug("STOPTHREADS Aborting SEARCHALLBOOKS")
                break

            # searchterm is only used for display purposes
            searchterm = ''
            if searchbook['AuthorName']:
                searchterm = searchbook['AuthorName']
            else:
                logger.warning(f"No AuthorName for {searchbook['BookID']}")

            if searchbook['BookName']:
                if len(searchterm):
                    searchterm += ' '
                searchterm += searchbook['BookName']
            else:
                logger.warning(f"No BookName for {searchbook['BookID']}")

            if searchbook['BookSub']:
                if len(searchterm):
                    searchterm += ': '
                searchterm += searchbook['BookSub']

            # titles of other translations, eg the Czech one of a Slovak book, see dbk.get_author_books
            other_titles = searchbook['OtherTitles'] if 'OtherTitles' in searchbook.keys() else ''
            other_titles = [title for title in (other_titles or '').splitlines() if title.strip()]

            if search_ebook and searchbook['Status'] == "Wanted":
                cmd = "SELECT BookID from wanted WHERE BookID=? and AuxInfo='eBook' and Status='Snatched'"
                snatched = db.match(cmd, (searchbook["BookID"],))
                if snatched:
                    logger.warning(
                        f"eBook {searchbook['AuthorName']} {searchbook['BookName']} "
                        f"already marked snatched in wanted table")
                else:
                    searchlist.append(
                        {"bookid": searchbook['BookID'],
                         "bookName": searchbook['BookName'],
                         "bookSub": searchbook['BookSub'],
                         "authorName": searchbook['AuthorName'],
                         "library": "eBook",
                         "searchterm": searchterm,
                         "otherTitles": other_titles,
                         "genre": (searchbook['BookGenre'] if 'BookGenre' in searchbook.keys() else '')})

            if search_audio and searchbook['AudioStatus'] == "Wanted":
                cmd = "SELECT BookID from wanted WHERE BookID=? and AuxInfo='AudioBook' and Status='Snatched'"
                snatched = db.match(cmd, (searchbook["BookID"],))
                if snatched:
                    logger.warning(
                        f"AudioBook {searchbook['AuthorName']} {searchbook['BookName']} "
                        f"already marked snatched in wanted table")
                else:
                    searchlist.append(
                        {"bookid": searchbook['BookID'],
                         "bookName": searchbook['BookName'],
                         "bookSub": searchbook['BookSub'],
                         "authorName": searchbook['AuthorName'],
                         "library": "AudioBook",
                         "searchterm": searchterm,
                         "otherTitles": other_titles,
                         "genre": (searchbook['BookGenre'] if 'BookGenre' in searchbook.keys() else '')})

        # only get rss results once per run, as they are not search specific
        rss_resultlist = None
        if CONFIG.use_rss():
            rss_resultlist, nprov, dltypes = iterate_over_rss_sites()
            if not nprov or (library == 'Audiobook' and 'A' not in dltypes) or \
                    (library == 'eBook' and 'E' not in dltypes) or \
                    (library is None and ('E' in dltypes or 'A' in dltypes)):
                warn_mode('rss')

        book_count = 0
        for book in searchlist:
            if lazylibrarian.STOPTHREADS and thread_name() == "SEARCHALLBOOKS":
                logger.debug("STOPTHREADS Aborting SEARCHALLBOOKS")
                break
            do_search = True
            if CONFIG.get_bool('DELAYSEARCH') and not force:
                res = db.match('SELECT * FROM failedsearch WHERE BookID=? AND Library=?',
                               (book['bookid'], book['library']))
                if not res:
                    logger.debug(f"SearchDelay: {book['library']} {book['bookid']} has not failed before")
                else:
                    skipped = check_int(res['Count'], 0)
                    interval = check_int(res['Interval'], 0)
                    if skipped < interval:
                        logger.debug(f"SearchDelay: {book['library']} {book['bookid']} not due ({skipped}/{interval})")
                        db.action("UPDATE failedsearch SET Count=? WHERE BookID=? AND Library=?",
                                  (skipped + 1, book['bookid'], book['library']))
                        do_search = False
                    else:
                        logger.debug(
                            f"SearchDelay: {book['library']} {book['bookid']} due this time ({skipped}/{interval})")

            matches = []
            direct_pool = None
            searchtype = 'audio' if book['library'] == 'AudioBook' else 'book'
            if (not do_search and book['library'] == 'eBook' and CONFIG.get_bool('ANNA')
                    and not BLOCKHANDLER.is_blocked('annas')):
                # A known file becoming eligible again must not wait behind an
                # unrelated multi-day "no search results" backoff. This lane
                # checks cached exact MD5s only; it makes no provider searches.
                due = retryable_anna_history_candidates(book, due_only=True)
                if due:
                    match = find_best_result(due, book, searchtype, 'direct')
                    if good_enough(match):
                        matches.append(match)
                        direct_pool = (due, dict(book), searchtype)
            if do_search:
                # first attempt, try author/title in category "book"
                if book['library'] == 'AudioBook':
                    searchtype = 'audio'
                else:
                    searchtype = 'book'

                if CONFIG.use_nzb():
                    resultlist, nprov = iterate_over_znab_sites(book, searchtype)
                    if not nprov:
                        warn_mode('nzb')
                    elif resultlist:
                        match = find_best_result(resultlist, book, searchtype, 'nzb')
                        if not good_enough(match):
                            logger.info(f"NZB search for {book['library']} {book['searchterm']} returned no results.")
                        else:
                            logger.info(
                                f"Found NZB result: {searchtype} {round(match[0], 2)}%, {match[1]['NZBprov']} "
                                f"priority {match[3]}")
                            matches.append(match)

                if CONFIG.use_tor():
                    resultlist, nprov = iterate_over_torrent_sites(book, searchtype)
                    if not nprov:
                        warn_mode('tor', searchtype)
                    elif resultlist:
                        match = find_best_result(resultlist, book, searchtype, 'tor')
                        if not good_enough(match):
                            logger.info(
                                f"Torrent search for {book['library']} {book['searchterm']} returned no results.")
                        else:
                            logger.info(
                                f"Found Torrent result: {searchtype} {round(match[0], 2)}%, {match[1]['NZBprov']} "
                                f"priority {match[3]}")
                            matches.append(match)

                if CONFIG.use_direct():
                    resultlist, nprov = iterate_over_direct_sites(book, searchtype)
                    if not nprov:
                        warn_mode('direct', searchtype)
                    elif resultlist:
                        match = find_best_result(resultlist, book, searchtype, 'direct')
                        if not good_enough(match):
                            logger.info(
                                f"Direct search for {book['library']} {book['searchterm']} returned no results.")
                        else:
                            logger.info(
                                f"Found Direct result: {searchtype} {round(match[0], 2)}%, "
                                f"{match[1]['NZBprov']} priority {match[3]}")
                            matches.append(match)
                            direct_pool = (list(resultlist), dict(book), searchtype)

                if CONFIG.use_irc():
                    resultlist, nprov = iterate_over_irc_sites(book, searchtype)
                    if not nprov:
                        warn_mode('irc')
                    elif resultlist:
                        match = find_best_result(resultlist, book, searchtype, 'irc')
                        if not good_enough(match):
                            logger.info(f"IRC search for {book['library']} {book['searchterm']} returned no results.")
                        else:
                            logger.info(
                                f"Found IRC result: {searchtype} {round(match[0], 2)}%, {match[1]['NZBprov']} "
                                f"priority {match[3]}")
                            matches.append(match)

                if CONFIG.use_rss() and rss_resultlist:
                    match = find_best_result(rss_resultlist, book, searchtype, 'rss')
                    if not good_enough(match):
                        logger.info(f"RSS search for {book['library']} {book['searchterm']} returned no results.")
                    else:
                        logger.info(
                            f"Found RSS result: {searchtype} {round(match[0], 2)}%, "
                            f"{match[1]['NZBprov']} priority {match[3]}")
                        matches.append(match)

                # if you can't find the book, try author/title without any "(extended details, series etc)"
                if not matches and ('(' in book['bookName'] or primary_title(book)):
                    if CONFIG.use_nzb():
                        resultlist, nprov = iterate_over_znab_sites(book, f"short{searchtype}")
                        if not nprov:
                            warn_mode('nzb')
                        elif resultlist:
                            match = find_best_result(resultlist, book, searchtype, 'nzb')
                            if not good_enough(match):
                                logger.info(
                                    f"NZB short search for {book['library']} {book['searchterm']} returned no results.")
                            else:
                                logger.info(
                                    f"Found NZB result: {searchtype} {round(match[0], 2)}%, {match[1]['NZBprov']} "
                                    f"priority {match[3]}")
                                matches.append(match)

                    if CONFIG.use_tor():
                        resultlist, nprov = iterate_over_torrent_sites(book, f"short{searchtype}")
                        if not nprov:
                            warn_mode('tor', searchtype)
                        elif resultlist:
                            match = find_best_result(resultlist, book, searchtype, 'tor')
                            if not good_enough(match):
                                logger.info(
                                    f"Torrent short search for {book['library']} {book['searchterm']} "
                                    f"returned no results.")
                            else:
                                logger.info(
                                    f"Found Torrent result: {searchtype} {round(match[0], 2)}%, {match[1]['NZBprov']} "
                                    f"priority {match[3]}")
                                matches.append(match)

                    if CONFIG.use_direct():
                        resultlist, nprov = iterate_over_direct_sites(book, f"short{searchtype}")
                        if not nprov:
                            warn_mode('direct', searchtype)
                        elif resultlist:
                            match = find_best_result(resultlist, book, searchtype, 'direct')
                            if not good_enough(match):
                                logger.info(
                                    f"Direct short search for {book['library']} {book['searchterm']} "
                                    f"returned no results.")
                            else:
                                logger.info(
                                    f"Found Direct result: {searchtype} {round(match[0], 2)}%, {match[1]['NZBprov']} "
                                    f"priority {match[3]}")
                                matches.append(match)
                                direct_pool = (list(resultlist), dict(book), searchtype)

                    if CONFIG.use_irc():
                        resultlist, nprov = iterate_over_irc_sites(book, f"short{searchtype}")
                        if not nprov:
                            warn_mode('irc')
                        elif resultlist:
                            match = find_best_result(resultlist, book, searchtype, 'irc')
                            if not good_enough(match):
                                logger.info(
                                    f"IRC short search for {book['library']} {book['searchterm']} returned no results.")
                            else:
                                logger.info(
                                    f"Found IRC result: {searchtype} {round(match[0], 2)}%, "
                                    f"{match[1]['NZBprov']} priority {match[3]}")
                                matches.append(match)

                    if CONFIG.use_rss() and rss_resultlist:
                        match = find_best_result(rss_resultlist, book, searchtype, 'rss')
                        if not good_enough(match):
                            logger.info(
                                f"RSS short search for {book['library']} {book['searchterm']} returned no results.")
                        else:
                            logger.info(
                                f"Found RSS result: {searchtype} {round(match[0], 2)}%, {match[1]['NZBprov']} "
                                f"priority {match[3]}")
                            matches.append(match)

                # if you can't find the book under "books", you might find under general search
                # general search is the same as booksearch for torrents, irc and rss, no need to check again
                if not matches and CONFIG.use_nzb():
                    resultlist, nprov = iterate_over_znab_sites(book, f"general{searchtype}")
                    if not nprov:
                        warn_mode('nzb')
                    elif resultlist:
                        match = find_best_result(resultlist, book, searchtype, 'nzb')
                        if not good_enough(match):
                            logger.info(
                                f"NZB general search for {book['library']} {book['searchterm']} returned no results.")
                        else:
                            logger.info(
                                f"Found NZB result: {searchtype} {round(match[0], 2)}%, {match[1]['NZBprov']} "
                                f"priority {match[3]}")
                            matches.append(match)

                # if still not found, try general search again without any "(extended details, series etc)"
                # shortgeneral is the same as shortbook for torrents, irc and rss, no need to check again
                if not matches and CONFIG.use_nzb() and ('(' in book['searchterm'] or primary_title(book)):
                    resultlist, nprov = iterate_over_znab_sites(book, f"shortgeneral{searchtype}")
                    if not nprov:
                        warn_mode('nzb')
                    elif resultlist:
                        match = find_best_result(resultlist, book, searchtype, 'nzb')
                        if not good_enough(match):
                            logger.info(
                                f"NZB shortgeneral search for {book['library']} {book['searchterm']} "
                                f"returned no results.")
                        else:
                            logger.info(
                                f"Found NZB result: {searchtype} {round(match[0], 2)}%, "
                                f"{match[1]['NZBprov']} priority {match[3]}")
                            matches.append(match)

                # if still not found, try general search again with title only
                if not matches:
                    if CONFIG.use_nzb():
                        resultlist, nprov = iterate_over_znab_sites(book, f"title{searchtype}")
                        if not nprov:
                            warn_mode('nzb')
                        elif resultlist:
                            match = find_best_result(resultlist, book, searchtype, 'nzb')
                            if not good_enough(match):
                                logger.info(
                                    f"NZB title search for {book['library']} {book['searchterm']} returned no results.")
                            else:
                                logger.info(
                                    f"Found NZB result: {searchtype} {round(match[0], 2)}%, {match[1]['NZBprov']} "
                                    f"priority {match[3]}")
                                matches.append(match)

                    if CONFIG.use_tor():
                        resultlist, nprov = iterate_over_torrent_sites(book, f"title{searchtype}")
                        if not nprov:
                            warn_mode('tor', searchtype)
                        elif resultlist:
                            match = find_best_result(resultlist, book, searchtype, 'tor')
                            if not good_enough(match):
                                logger.info(
                                    f"Torrent title search for {book['library']} {book['searchterm']} "
                                    f"returned no results.")
                            else:
                                logger.info(
                                    f"Found Torrent result: {searchtype} {round(match[0], 2)}%, {match[1]['NZBprov']} "
                                    f"priority {match[3]}")
                                matches.append(match)

                    if CONFIG.use_direct():
                        resultlist, nprov = iterate_over_direct_sites(book, f"title{searchtype}")
                        if not nprov:
                            warn_mode('direct', searchtype)
                        elif resultlist:
                            match = find_best_result(resultlist, book, searchtype, 'direct')
                            if not good_enough(match):
                                logger.info(
                                    f"Direct title search for {book['library']} {book['searchterm']}"
                                    f" returned no results.")
                            else:
                                logger.info(
                                    f"Found Direct result: {searchtype} {round(match[0], 2)}%, {match[1]['NZBprov']} "
                                    f"priority {match[3]}")
                                matches.append(match)
                                direct_pool = (list(resultlist), dict(book), searchtype)

                    # irchighway says search results without both author and title will be
                    # silently rejected but that doesn't seem to be actioned...
                    if CONFIG.use_irc():
                        resultlist, nprov = iterate_over_irc_sites(book, f"title{searchtype}")
                        if not nprov:
                            warn_mode('irc')
                        elif resultlist:
                            match = find_best_result(resultlist, book, searchtype, 'irc')
                            if not good_enough(match):
                                logger.info(
                                    f"IRC title search for {book['library']} {book['searchterm']} returned no results.")
                            else:
                                logger.info(
                                    f"Found IRC result: {searchtype} {round(match[0], 2)}%, {match[1]['NZBprov']} "
                                    f"priority {match[3]}")
                                matches.append(match)

                    if CONFIG.use_rss():
                        match = find_best_result(rss_resultlist, book, searchtype, 'rss')
                        if not good_enough(match):
                            logger.info(
                                f"RSS title search for {book['library']} {book['searchterm']} returned no results.")
                        else:
                            logger.info(
                                f"Found RSS result: {searchtype} {round(match[0], 2)}%, {match[1]['NZBprov']} "
                                f"priority {match[3]}")
                            matches.append(match)

                # if still not found, try the titles of other translations, eg the Czech one of a
                # Slovak book. A match is still downloaded as this book
                for title in book.get('otherTitles', []):
                    if matches:
                        break
                    other = dict(book, bookName=title, bookSub='', searchterm=f"{book['authorName']} {title}")
                    logger.info(f"Trying {book['library']} {book['searchterm']} as {title}")
                    matches = _search_providers(other, searchtype, rss_resultlist)

                # if still not found and the book's genre suggests it is a graphic novel
                # or comic, also try comic provider categories
                if not matches and book.get('library') == 'eBook' and _has_comic_genre(book):
                    logger.info(
                        f"Genre [{book.get('genre', '')}] matches comic genres, "
                        f"trying comic categories for {book['searchterm']}")
                    if CONFIG.use_nzb():
                        resultlist, nprov = iterate_over_znab_sites(book, 'comic')
                        if not nprov:
                            logger.debug("No NZB providers have comic categories enabled")
                        elif resultlist:
                            match = find_best_result(resultlist, book, searchtype, 'nzb')
                            if good_enough(match):
                                logger.info(
                                    f"Found NZB comic result: {round(match[0], 2)}%, "
                                    f"{match[1]['NZBprov']} priority {match[3]}")
                                matches.append(match)
                    if CONFIG.use_tor():
                        resultlist, nprov = iterate_over_torrent_sites(book, 'comic')
                        if not nprov:
                            logger.debug("No torrent providers have comic categories enabled")
                        elif resultlist:
                            match = find_best_result(resultlist, book, searchtype, 'tor')
                            if good_enough(match):
                                logger.info(
                                    f"Found Torrent comic result: {round(match[0], 2)}%, "
                                    f"{match[1]['NZBprov']} priority {match[3]}")
                                matches.append(match)

            if (not matches and do_search and book["library"] == "eBook"
                    and CONFIG.get_bool("ANNA") and not BLOCKHANDLER.is_blocked("annas")):
                history = retryable_anna_history_candidates(book)
                if history:
                    match = find_best_result(history, book, searchtype, "direct")
                    if good_enough(match):
                        logger.info("Retrying a previously matched Anna source after current policy checks")
                        matches.append(match)
                        direct_pool = (history, dict(book), searchtype)


            if matches:
                result = _download_candidate_matches(matches, book, direct_pool)
                snatched = result > 0
                if result > 1:
                    book_count += 1
                if snatched:
                    db.action("DELETE from failedsearch WHERE BookID=? AND Library=?",
                              (book['bookid'], book['library']))
                elif CONFIG.get_bool('DELAYSEARCH'):
                    # Every candidate we tried failed to download (not "no results found" -
                    # this book had a match, it just wouldn't fetch). Previously the
                    # failedsearch record was deleted unconditionally whenever there was a
                    # match at all, silently clearing the backoff counter on every failed
                    # download and letting the next scheduled search retry immediately
                    # instead of backing off like the "no results" case does (Issue #3024).
                    res = db.match('SELECT * FROM failedsearch WHERE BookID=? AND Library=?',
                                   (book['bookid'], book['library']))
                    interval = check_int(res['Interval'], 0) if res else 0
                    db.upsert("failedsearch",
                             {'Count': 0, 'Interval': interval + 1, 'Time': time.time()},
                             {'BookID': book['bookid'], 'Library': book['library']})
            elif CONFIG.get_bool('DELAYSEARCH') and not force and do_search and len(modelist):
                res = db.match('SELECT * FROM failedsearch WHERE BookID=? AND Library=?',
                               (book['bookid'], book['library']))
                if res:
                    interval = check_int(res['Interval'], 0)
                else:
                    interval = 0

                db.upsert("failedsearch",
                          {'Count': 0, 'Interval': interval + 1, 'Time': time.time()},
                          {'BookID': book['bookid'], 'Library': book['library']})

            time.sleep(CONFIG.get_int('SEARCH_RATELIMIT'))

        logger.info(f"Search for Wanted items complete, found {book_count} {plural(book_count, 'book')}")

    except Exception:
        logger.error(f'Unhandled exception in search_book: {traceback.format_exc()}')
    finally:
        logger.debug(f"Storing finish time for {thread_name()}")
        db.upsert("jobs", {"Finish": time.time()}, {"Name": thread_name()})
        db.close()
        thread_name("WEBSERVER")

def weighted_score(s):
    # priority is already 0-100-ish per provider; normalize it down to a modest bonus
    priority_bonus = (check_int(s[3], 0) / 100) * CONFIG.get_int('PRIORITY_WEIGHT')
    return check_int(s[0], 0) + priority_bonus
