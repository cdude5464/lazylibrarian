#  This file is part of Lazylibrarian.
#  Lazylibrarian is free software, you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#  Lazylibrarian is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#  You should have received a copy of the GNU General Public License
#  along with Lazylibrarian.  If not, see <http://www.gnu.org/licenses/>.
import json
import logging
import os
import re
import string
import time
import traceback
from urllib.parse import quote, urlencode

import cherrypy
import requests
from rapidfuzz import fuzz
from rapidfuzz.utils import default_process
from requests.auth import HTTPBasicAuth, HTTPDigestAuth

from lazylibrarian import database
from lazylibrarian.common import get_readinglist, run_script, set_readinglist
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import get_directory
from lazylibrarian.formatter import get_list, unaccented
from lazylibrarian.importer import add_author_name_to_db, import_book, search_for
from lazylibrarian.librarysync import find_book_in_db

# calibredb custom_columns
# calibredb add_custom_column label name bool
# calibredb remove_custom_column --force label
# calibredb set_custom label id value
# calibredb search "#label":"false"  # returns list of ids (slow)


def calibre_server_request(endpoint, params=None, method='GET', data=None, timeout=15, with_library=False):
    """ Generic REST API client for Calibre Content Server.
        Enables seamless network communication with Calibre across Docker containers,
        LANs, or remote instances without requiring local calibredb CLI or direct database access. """
    logger = logging.getLogger(__name__)
    server = (CONFIG['CALIBRE_SERVER'] or '').strip().rstrip('/')
    if not server:
        return None, "No CALIBRE_SERVER configured"
    # CALIBRE_SERVER may carry a "#library" fragment (the calibredb --with-library convention).
    # In a REST URL everything after "#" is never sent to the server, which would silently
    # swallow the endpoint, so split the fragment off. The server ignores a library query
    # parameter, endpoints that take a library have it as the last path segment instead
    library = None
    if '#' in server:
        server, library = server.split('#', 1)
        server = server.rstrip('/')
        library = library.strip()
    if not server.startswith('http'):
        scheme = 'https://' if CONFIG.get_bool('HTTPS_ENABLED') else 'http://'
        server = f"{scheme}{server}"

    params = dict(params) if params else {}
    url = f"{server}/{endpoint.lstrip('/')}"
    if with_library and library:
        url += f"/{quote(library, safe='')}"
    if params:
        url += f"?{urlencode(params)}"

    headers = {'Accept': 'application/json, text/plain, */*'}
    auth = None
    if CONFIG['CALIBRE_USER'] and CONFIG['CALIBRE_PASS']:
        # Calibre Content Server serves HTTP Digest challenges when auth is enabled;
        # Basic auth gets rejected with "400 Unsupported authentication method"
        auth = HTTPDigestAuth(CONFIG['CALIBRE_USER'], CONFIG['CALIBRE_PASS'])

    try:
        r = requests.request(method, url, headers=headers, auth=auth, json=data, timeout=timeout)
        challenge = r.headers.get('WWW-Authenticate', '').lower() if r.status_code == 401 else ''
        if auth and challenge.startswith('basic'):
            # the server uses basic auth when it has ssl, or is started with --auth-mode basic.
            # Only send the password that way over https, and not on to wherever a redirect goes
            if not url.startswith('https://') or not r.url.startswith('https://'):
                return None, "HTTP 401: server wants basic auth, which needs an https CALIBRE_SERVER"
            auth = HTTPBasicAuth(CONFIG['CALIBRE_USER'], CONFIG['CALIBRE_PASS'])
            r = requests.request(method, url, headers=headers, auth=auth, json=data, timeout=timeout,
                                 allow_redirects=False)
        if r.status_code == 200:
            try:
                return r.json(), None
            except Exception:
                return r.text, None
        return None, f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        logger.debug(f"Calibre server API error for {url}: {e}")
        return None, str(e)


def calibre_server_search(query):
    """ Search Calibre library via Content Server REST API.
        Query can be a free text search, title:"...", author:"...", or identifiers:goodreads:... / identifiers:isbn:...
        Returns a list of matching Calibre book IDs. """
    data, err = calibre_server_request('ajax/search', params={'query': query}, with_library=True)
    if data and isinstance(data, dict) and 'book_ids' in data:
        return data['book_ids'], None
    return [], err


def calibre_server_get_books():
    """ Fetch the entire Calibre library in a single REST API call via /ajax/books.
        Returns dict of {book_id: book_metadata_dict}. """
    data, err = calibre_server_request('ajax/books', with_library=True)
    if data and isinstance(data, dict):
        return data, None
    return {}, err


def calibre_server_get_book(book_id):
    """ Retrieve full book metadata from Calibre Content Server REST API """
    return calibre_server_request(f"ajax/book/{quote(str(book_id), safe='')}", with_library=True)


def calibre_list(col_read, col_toread):
    """ Get a list from calibre of all books in its library, including optional 'read' and 'toread' columns
        If success, return list of dicts {"title": "", "id": 0, "authors": ""}
        The "read" and "toread" columns are passed as column names so they can be per-user and may not be present.
        Can be true, false, or empty in which case not included in dict. We only use the "true" state
        If error, return error message (not a dict) """

    # 1. Try Calibre Content Server REST API first if configured
    if CONFIG.get_bool('CALIBRE_USE_SERVER') and CONFIG['CALIBRE_SERVER']:
        books_dict, _ = calibre_server_get_books()
        if books_dict:
            results = []
            for bid_str, bdata in books_dict.items():
                if isinstance(bdata, dict):
                    bid = int(bid_str) if str(bid_str).isdigit() else bid_str
                    item = {
                        'id': bid,
                        'title': bdata.get('title', ''),
                        # same separator as calibredb list, a comma reads as surname, forename
                        'authors': ' & '.join(bdata.get('authors', [])),
                        'identifiers': bdata.get('identifiers', {}),
                        'formats': bdata.get('formats', []),
                        'pubdate': bdata.get('pubdate', ''),
                    }
                    user_metadata = bdata.get('user_metadata', {})
                    if col_read and f'#{col_read}' in user_metadata:
                        val = user_metadata[f'#{col_read}'].get('#value#')
                        if val:
                            item[f'*{col_read}'] = val
                    if col_toread and f'#{col_toread}' in user_metadata:
                        val = user_metadata[f'#{col_toread}'].get('#value#')
                        if val:
                            item[f'*{col_toread}'] = val
                    results.append(item)
            if results:
                return results

    # 2. Try calibredb CLI binary
    fieldlist = 'title,authors'
    if col_read:
        fieldlist += f",*{col_read}"
    if col_toread:
        fieldlist += f",*{col_toread}"
    res, err, rc = calibredb("list", "", ['--for-machine', '--fields', fieldlist])
    if rc:
        ebook_dir = get_directory('eBook')
        meta_db = os.path.join(ebook_dir, 'metadata.db') if ebook_dir else ''
        if meta_db and os.path.isfile(meta_db):
            try:
                import sqlite3
                conn = sqlite3.connect(f"file:{meta_db}?mode=ro", uri=True)
                conn.row_factory = sqlite3.Row
                query = """SELECT b.id, b.title, a.name as authors
                           FROM books b
                           JOIN books_authors_link bal ON b.id = bal.book
                           JOIN authors a ON bal.author = a.id"""
                rows = conn.execute(query).fetchall()
                conn.close()
                return [{'id': r['id'], 'title': r['title'], 'authors': r['authors']} for r in rows]
            except Exception as e:
                logger = logging.getLogger(__name__)
                logger.error(f"Failed to read Calibre metadata.db: {e}")
        if res:
            return res
        return err
    logger = logging.getLogger(__name__)
    logger.debug(f"{res}")
    # Issue #2852: `calibredb list --for-machine` returned a complete, valid JSON array on a
    # large real-world library, but with extra bytes trailing after it (the exact content was
    # never pinned down across several debug rounds on the issue - only the "Extra data" symptom
    # was, at a shifting offset as the reporter's library changed size, consistent with something
    # genuinely appended after a valid array rather than a parse-position bug of ours). A plain
    # json.loads() rejects the whole response outright over that trailing content, and did so
    # uncaught here - contradicting this function's own documented "return an error message
    # (not a dict) on failure" contract, which is what turned this into an unhandled exception
    # instead of the graceful failure sync_calibre_list()'s caller already expects.
    decoder = json.JSONDecoder()
    try:
        data, end = decoder.raw_decode(res.strip())
    except json.JSONDecodeError as e:
        logger.error(f"calibredb list returned unparseable JSON: {e}")
        return str(e)
    trailing = res.strip()[end:].strip()
    if trailing:
        logger.warning(f"calibredb list returned {len(trailing)} byte(s) of unexpected data "
                       f"after its JSON list, ignored: {trailing[:200]!r}")
    return data


def sync_calibre_list(col_read=None, col_toread=None, userid=None):
    """ Get the lazylibrarian bookid for each read/toread calibre book so we can map our id to theirs,
        and sync current/supplied user's read/toread or supplied read/toread columns to calibre database.
        Return message giving totals """
    logger = logging.getLogger(__name__)
    db = database.DBConnection()
    msg = ''
    try:
        username = ''
        readlist = []
        toreadlist = []
        if not userid:
            cookie = cherrypy.request.cookie
            if cookie and 'll_uid' in list(cookie.keys()):
                userid = cookie['ll_uid'].value
        if userid:
            res = db.match('SELECT UserName,CalibreRead,CalibreToRead,Perms from users where UserID=?',
                           (userid,))
            if res:
                username = res['UserName']
                if not col_read:
                    col_read = res['CalibreRead']
                if not col_toread:
                    col_toread = res['CalibreToRead']
                toreadlist = get_readinglist("ToRead", userid)
                readlist = get_readinglist("HaveRead", userid)
            else:
                return f"Error: Unable to get user column settings for {userid}"

        if not userid:
            return "Error: Unable to find current userid"

        if not col_read and not col_toread:
            return f"User {username} has no calibre columns set"

        # check user columns exist in calibre and create if not
        res = calibredb('custom_columns')
        columns = res[0].split('\n')
        custom_columns = []
        for column in columns:
            if column:
                custom_columns.append(column.split(' (')[0])

        if col_read not in custom_columns:
            added = calibredb('add_custom_column', [col_read, col_read, 'bool'])
            if "column created" not in added[0]:
                return added
        if col_toread not in custom_columns:
            added = calibredb('add_custom_column', [col_toread, col_toread, 'bool'])
            if "column created" not in added[0]:
                return added

        nomatch = 0
        readcol = ''
        toreadcol = ''
        map_ctol = {}
        map_ltoc = {}
        if col_read:
            readcol = f"*{col_read}"
        if col_toread:
            toreadcol = f"*{col_toread}"

        calibrelist = calibre_list(col_read, col_toread)
        if not isinstance(calibrelist, list):
            # got an error message from calibredb
            return f'"{calibrelist}"'

        for item in calibrelist:
            if toreadcol and toreadcol in item or readcol and readcol in item:
                authorname, _, added = add_author_name_to_db(item['authors'], refresh=False, addbooks=False,
                                                             reason=f"sync_calibre_list: {item['title']}",
                                                             title=item['title'])
                if authorname:
                    if authorname != item['authors']:
                        logger.debug(
                            f"Changed authorname for [{item['title']}] from [{item['authors']}] to [{authorname}]")
                        item['authors'] = authorname
                    bookid, mtype = find_book_in_db(authorname, item['title'], ignored=False, library='eBook',
                                                    reason=f"sync_calibre_list: {item['title']}")
                    if bookid and mtype == "Ignored":
                        logger.warning(
                            f"Book {item['title']} by {authorname} is marked Ignored in database, importing anyway")
                    if not bookid:
                        searchterm = f"{item['title']}<ll>{authorname}"
                        results = search_for(unaccented(searchterm, only_ascii=False))
                        if results:
                            result = results[0]
                            if result['author_fuzz'] > CONFIG.get_int('MATCH_RATIO') \
                                    and result['book_fuzz'] > CONFIG.get_int('MATCH_RATIO'):
                                logger.debug(
                                    f"Found ({round(result['author_fuzz'], 2)}% {round(result['book_fuzz'], 2)}%) "
                                    f"{result['authorname']}: {result['bookname']}")
                                bookid = result['bookid']
                                import_book(bookid, reason="Added by calibre sync")
                    if bookid:
                        # NOTE: calibre bookid is always an integer, lazylibrarian bookid is a string
                        # (goodreads could be used as an int, but googlebooks can't as it's alphanumeric)
                        # so convert all dict items to strings for ease of matching.
                        map_ctol[str(item['id'])] = str(bookid)
                        map_ltoc[str(bookid)] = str(item['id'])
                    else:
                        logger.warning(
                            f"Calibre Book [{item['title']}] by [{authorname}] is not in lazylibrarian database")
                        nomatch += 1
                else:
                    logger.warning(f"Calibre Author [{item['authors']}] not matched in lazylibrarian database")
                    nomatch += 1

        # Now check current users lazylibrarian read/toread against the calibre library, warn about missing ones
        # which might be books calibre doesn't have, or might be minor differences in author or title

        for idlist in [("Read", readlist), ("To_Read", toreadlist)]:
            booklist = idlist[1]
            for bookid in booklist:
                cmd = "SELECT AuthorID,BookName from books where BookID=?"
                book = db.match(cmd, (bookid,))
                if not book:
                    logger.error(f'Error finding bookid {bookid}')
                else:
                    cmd = "SELECT AuthorName from authors where AuthorID=?"
                    author = db.match(cmd, (book['AuthorID'],))
                    if not author:
                        logger.error(f"Error finding authorid {book['AuthorID']}")
                    else:
                        match = False
                        high = 0
                        highname = ''
                        for item in calibrelist:
                            if item['authors'] == author['AuthorName'] and item['title'] == book['BookName']:
                                logger.debug(f"Exact match for {idlist[0]} [{book['BookName']}]")
                                map_ctol[str(item['id'])] = str(bookid)
                                map_ltoc[str(bookid)] = str(item['id'])
                                match = True
                                break
                        if not match:
                            highid = ''
                            for item in calibrelist:
                                if item['authors'] == author['AuthorName']:
                                    n = fuzz.token_sort_ratio(item['title'], book['BookName'], processor=default_process)
                                    if n > high:
                                        high = n
                                        highname = item['title']
                                        highid = item['id']

                            if high > 95:
                                logger.debug(
                                    f"Found ratio match {round(high, 2)}% [{highname}] "
                                    f"for {idlist[0]} [{book['BookName']}]")
                                map_ctol[str(highid)] = str(bookid)
                                map_ltoc[str(bookid)] = str(highid)
                                match = True

                        if not match:
                            logger.warning(
                                f"No match for {idlist[0]} {book['BookName']} by {author['AuthorName']} "
                                f"in calibre database, closest match {round(high, 2)}% [{highname}]")
                            nomatch += 1

        logger.debug(f"BookID mapping complete, {username} match {len(map_ctol)}, nomatch {nomatch}")

        # now sync the lists
        if not userid:
            msg = "No userid found"
        else:
            last_read = []
            last_toread = []
            calibre_read = []
            calibre_toread = []

            cmd = "select SyncList from sync where UserID=? and Label=?"
            res = db.match(cmd, (userid, col_read))
            if res:
                last_read = get_list(res['SyncList'])
            res = db.match(cmd, (userid, col_toread))
            if res:
                last_toread = get_list(res['SyncList'])

            for item in calibrelist:
                itemid = str(item['id'])
                if toreadcol and toreadcol in item and item[toreadcol]:  # only if True
                    if itemid in map_ctol:
                        calibre_toread.append(map_ctol[itemid])
                    else:
                        logger.warning(
                            f"Calibre to_read book {item['authors']}:{item['title']} has no lazylibrarian bookid")
                if readcol and readcol in item and item[readcol]:  # only if True
                    if itemid in map_ctol:
                        calibre_read.append(map_ctol[itemid])
                    else:
                        logger.warning(
                            f"Calibre read book {item['authors']}:{item['title']} has no lazylibrarian bookid")

            logger.debug(f"Found {len(calibre_read)} calibre read, {len(calibre_toread)} calibre toread")
            logger.debug(f"Found {len(readlist)} lazylib read, {len(toreadlist)} lazylib toread")

            added_to_ll_toread = list(set(toreadlist) - set(last_toread))
            removed_from_ll_toread = list(set(last_toread) - set(toreadlist))
            added_to_ll_read = list(set(readlist) - set(last_read))
            removed_from_ll_read = list(set(last_read) - set(readlist))
            logger.debug(
                f"lazylibrarian changes to copy to calibre: {len(added_to_ll_toread)} {len(removed_from_ll_toread)}"
                f" {len(added_to_ll_read)} {len(removed_from_ll_read)}")

            added_to_calibre_toread = list(set(calibre_toread) - set(last_toread))
            removed_from_calibre_toread = list(set(last_toread) - set(calibre_toread))
            added_to_calibre_read = list(set(calibre_read) - set(last_read))
            removed_from_calibre_read = list(set(last_read) - set(calibre_read))
            logger.debug(
                f"calibre changes to copy to lazylibrarian: {len(added_to_calibre_toread)} "
                f"{len(removed_from_calibre_toread)} {len(added_to_calibre_read)} {len(removed_from_calibre_read)}")

            calibre_changes = 0
            for item in added_to_calibre_read:
                if item not in readlist:
                    readlist.append(item)
                    logger.debug(f"Lazylibrarian marked {item} as read")
                    calibre_changes += 1
            for item in added_to_calibre_toread:
                if item not in toreadlist:
                    toreadlist.append(item)
                    logger.debug(f"Lazylibrarian marked {item} as to_read")
                    calibre_changes += 1
            for item in removed_from_calibre_read:
                if item in readlist:
                    readlist.remove(item)
                    logger.debug(f"Lazylibrarian removed {item} from read")
                    calibre_changes += 1
            for item in removed_from_calibre_toread:
                if item in toreadlist:
                    toreadlist.remove(item)
                    logger.debug(f"Lazylibrarian removed {item} from to_read")
                    calibre_changes += 1
            if calibre_changes:
                set_readinglist("ToRead", userid, toreadlist)
                set_readinglist("HaveRead", userid, readlist)

            ll_changes = 0
            for item in added_to_ll_toread:
                if item in map_ltoc:
                    res, err, rc = calibredb('set_custom', [col_toread, map_ltoc[item], 'true'], [])
                    if rc:
                        msg = "calibredb set_custom error: "
                        if err:
                            logger.error(msg + err)
                        elif res:
                            logger.error(msg + res)
                        else:
                            logger.error(msg + str(rc))
                    else:
                        ll_changes += 1
                else:
                    logger.warning(f"Unable to set calibre {col_toread} true for {item}")
            for item in removed_from_ll_toread:
                if item in map_ltoc:
                    res, err, rc = calibredb('set_custom', [col_toread, map_ltoc[item], ''], [])
                    if rc:
                        msg = "calibredb set_custom error: "
                        if err:
                            logger.error(msg + err)
                        elif res:
                            logger.error(msg + res)
                        else:
                            logger.error(msg + str(rc))
                    else:
                        ll_changes += 1
                else:
                    logger.warning(f"Unable to clear calibre {col_toread} for {item}")

            for item in added_to_ll_read:
                if item in map_ltoc:
                    res, err, rc = calibredb('set_custom', [col_read, map_ltoc[item], 'true'], [])
                    if rc:
                        msg = "calibredb set_custom error: "
                        if err:
                            logger.error(msg + err)
                        elif res:
                            logger.error(msg + res)
                        else:
                            logger.error(msg + str(rc))
                    else:
                        ll_changes += 1
                else:
                    logger.warning(f"Unable to set calibre {col_read} true for {item}")

            for item in removed_from_ll_read:
                if item in map_ltoc:
                    res, err, rc = calibredb('set_custom', [col_read, map_ltoc[item], ''], [])
                    if rc:
                        msg = "calibredb set_custom error: "
                        if err:
                            logger.error(msg + err)
                        elif res:
                            logger.error(msg + res)
                        else:
                            logger.error(msg + str(rc))
                    else:
                        ll_changes += 1
                else:
                    logger.warning(f"Unable to clear calibre {col_read} for {item}")

            # store current sync list as comparison for next sync
            control_value_dict = {"UserID": userid, "Label": col_read}
            new_value_dict = {"Date": str(time.time()), "Synclist": ', '.join(readlist)}
            db.upsert("sync", new_value_dict, control_value_dict)
            control_value_dict = {"UserID": userid, "Label": col_toread}
            new_value_dict = {"Date": str(time.time()), "Synclist": ', '.join(toreadlist)}
            db.upsert("sync", new_value_dict, control_value_dict)

            msg = f"{username} sync updated: {ll_changes} calibre, {calibre_changes} lazylibrarian"

    except Exception as e:
        logger.error(f"{e}: {traceback.format_exc()}")

    db.close()
    return msg


def calibre_test():
    # 1. Test Calibre Content Server REST API if configured
    if CONFIG.get_bool('CALIBRE_USE_SERVER') and CONFIG['CALIBRE_SERVER']:
        info, err = calibre_server_request('ajax/library-info')
        if not info or not isinstance(info, dict):
            res = f"Calibre Content Server REST API communication failed: {err or 'No response'}"
            if CONFIG['IMP_CALIBREDB']:
                # calibredb doesn't go through the REST api, so it can still work
                res += f"\n{calibredb_test()}"
            return res

        default_lib = info.get('default_library', 'default')
        libs = list(info.get('library_map', {}).values())

        search_res, err = calibre_server_request('ajax/search', params={'query': 'id:>0'}, with_library=True)
        res = f"Calibre Content Server REST API ok. Default library: '{default_lib}', Libraries: {libs}"
        if search_res and isinstance(search_res, dict):
            res += f"\nDatabase READ ok ({search_res.get('total_num', 0)} books found)"
        else:
            # eg a #library that isn't in the library map
            res += f"\nDatabase READ failed: {err or 'No response'}"
        if CONFIG['IMP_CALIBREDB']:
            cres, cerr, crc = calibredb('--version')
            if not crc:
                vernum = cres.split('(calibre ')[1].split(')')[0] if '(calibre ' in cres else cres.strip()
                res += f"\ncalibredb CLI ok, version {vernum}"
        return res

    # 2. calibredb CLI binary test
    return calibredb_test()


def calibredb_test():
    logger = logging.getLogger(__name__)
    res, err, rc = calibredb('--version')
    if rc:
        msg = "calibredb communication failed: "
        if err:
            return msg + err
        return msg + res

    if '(calibre ' in res:
        # extract calibredb version number
        vernum = res.split('(calibre ')[1]
        if ')' in vernum:
            vernum = vernum.split(')')[0]
        res = f"calibredb ok, version {vernum}"

        # get a list of categories and counters from the database in CSV format
        cats, err, rc = calibredb('list_categories', ['-ic'])
        logger.debug(f"Calibredb list_categories {cats}")
        cnt = 0
        if not len(cats):
            res += '\nDatabase READ Failed'
        else:
            for entry in cats.split('\n'):
                words = entry.split(',')
                if len(words) >= 2:  # Filter out header and footer
                    item_count = words[2]
                    if item_count.strip('b').strip("'").isdigit():
                        cnt += int(item_count)
        if cnt:
            res += '\nDatabase READ ok'
            wrt, err, rc = calibredb('add', ['--authors', 'LazyLibrarian', '--title', 'dummy', '--empty'], [])
            logger.debug(f"Calibredb add  {wrt}")
            # Answer should look like "Added book ids: bookID" (string may be translated!)
            # or "add Integration status: True Added book ids: bookID"
            try:
                calibre_id = wrt.rsplit(": ", 1)[1].split("\n", 1)[0].strip()
            except IndexError:
                res += '\nDatabase WRITE Failed'
                return res

            # Try to fetch the added book and delete it
            if not calibre_id.isdigit():
                res += '\nDatabase WRITE Failed'
                return res
            if vernum.startswith('2'):
                _, err, rc = calibredb('remove', [calibre_id], [])
            else:
                rmv, err, rc = calibredb('remove', ['--permanent', calibre_id], [])
            if not rc:
                res += '\nDatabase WRITE ok'
            else:
                res += '\nDatabase WRITE2 Failed: '
        else:
            res += '\nDatabase READ Failed or database is empty'
    else:
        res = 'calibredb Failed'
    return res


def calibredb(cmd=None, prelib=None, postlib=None):
    """ calibre-server needs to be started with --enable-auth and needs user/password to add/remove books
        only basic features are available without auth. calibre_server should look like  http://address:port/#library
        default library is used if no #library in the url
        or calibredb can talk to the database file as long as there is no running calibre """

    logger = logging.getLogger(__name__)
    if not CONFIG['IMP_CALIBREDB']:
        return "No calibredb set in config", '', 1

    params = [CONFIG['IMP_CALIBREDB'], cmd]
    if CONFIG.get_bool('CALIBRE_USE_SERVER'):
        dest_url = CONFIG['CALIBRE_SERVER']
        if not dest_url.startswith('http'):
            if CONFIG.get_bool('HTTPS_ENABLED'):
                dest_url = 'https://' + dest_url
            else:
                dest_url = 'http://' + dest_url

        if CONFIG['CALIBRE_USER'] and CONFIG['CALIBRE_PASS']:
            params.extend(['--username', CONFIG['CALIBRE_USER'],
                           '--password', CONFIG['CALIBRE_PASS']])
    else:
        dest_url = get_directory('eBook')
    if prelib:
        params.extend(prelib)

    if cmd != "--version":
        params.extend(['--with-library', f'{dest_url}'])
    if postlib:
        params.extend(postlib)

    logger.debug(f"Run calibre: '{params}'")
    rc, res, err = run_script(params)
    logger.debug(f"calibredb rc {rc}")
    wsp = re.escape(string.whitespace)
    nres = re.sub(r'[' + wsp + ']', ' ', res)
    nerr = re.sub(r'[' + wsp + ']', ' ', err)
    logger.debug(f"calibredb res {len(nres)}[{nres}]")
    logger.debug(f"calibredb err {len(nerr)}[{nerr}]")

    if rc:
        if 'Errno 111' in err:
            logger.warning("calibredb returned Errno 111: Connection refused")
        elif 'Errno 13' in err:
            logger.warning("calibredb returned Errno 13: Permission denied")
        elif cmd == 'list_categories' and len(res):
            rc = 0  # false error return of 1 on v2.xx calibredb
    if 'already exist' in err:
        dest_url = err

    if rc:
        return res, err, rc
    return res, dest_url, 0


def delete_from_calibre(calibre_id):
    logger = logging.getLogger(__name__)
    if calibre_id:
        # the endpoint takes a list of ids, only ever send it one
        if CONFIG.get_bool('CALIBRE_USE_SERVER') and CONFIG['CALIBRE_SERVER'] and str(calibre_id).isdigit():
            res, err = calibre_server_request(f'cdb/delete-books/{calibre_id}', method='POST', with_library=True)
            if not err:
                logger.debug(f"Deleted calibre ID {calibre_id} via REST API")
                return True
        res, err, rc = calibredb('remove', [calibre_id])
        logger.debug(f"Delete result: {res} [{err}] {rc}")
        return rc == 0
    logger.debug("Missing calibre ID")
    return False


def get_calibre_id(data, try_filename=True):
    """ Get the Calibre ID for 'data', which may be a book or a magazine """
    logger = logging.getLogger(__name__)
    logger.debug(str(data))
    calibre_id = ''
    if not isinstance(data, dict):  # could be sqlite3 row
        try:
            data = dict(data)
        except ValueError:
            return ''
    if 'BookName' in data or 'BookFile' in data:  # it's a book
        author = data.get('AuthorName', '')
        title = data.get('BookName', '')
        fname = data.get('BookFile', '')
        isbn = data.get('BookIsbn', '') or data.get('ISBN', '')
        bookid = data.get('BookID', '')
    else:
        title = data.get('IssueDate', '')
        if title:  # it's a magazine issue
            author = data.get('Title', '')
            fname = data.get('IssueFile', '')
        else:  # assume it's a comic issue
            title = data.get('IssueID', '')
            author = data.get('ComicID', '')
            fname = data.get('IssueFile', '')
        isbn = ''
        bookid = ''

    if try_filename and fname:
        try:
            fname = os.path.dirname(fname)
            cid = fname.rsplit('(', 1)[1].split(')')[0]
            if cid.isdigit():
                calibre_id = cid
        except IndexError:
            calibre_id = ''

    # 1. Calibre Content Server REST API lookup (generic network API, no calibredb CLI or direct DB needed)
    if not calibre_id and CONFIG.get_bool('CALIBRE_USE_SERVER') and CONFIG['CALIBRE_SERVER']:
        # Match by ISBN if present
        if isbn:
            clean_isbn = re.sub(r'[^0-9X]', '', str(isbn).upper())
            if clean_isbn:
                bids, _ = calibre_server_search(f'isbn:{clean_isbn}')
                if bids:
                    calibre_id = str(bids[0])
                    logger.debug(f"Found Calibre ID {calibre_id} via ISBN {clean_isbn}")

        # Match by Goodreads ID if BookID is numeric
        if not calibre_id and bookid and str(bookid).isdigit():
            bids, _ = calibre_server_search(f'identifiers:goodreads:{bookid}')
            if bids:
                calibre_id = str(bids[0])
                logger.debug(f"Found Calibre ID {calibre_id} via goodreads:{bookid}")

        # Match by Title and Author
        if not calibre_id and title:
            safe_title = title.replace('"', '\\"')
            safe_author = author.replace('"', '\\"') if author else ''
            query = f'title:"{safe_title}"'
            if safe_author:
                query += f' author:"{safe_author}"'
            bids, _ = calibre_server_search(query)
            if bids:
                calibre_id = str(bids[0])
                logger.debug(f"Found Calibre ID {calibre_id} via title/author search")
            elif safe_author:
                bids, _ = calibre_server_search(f'title:"{safe_title}"')
                if bids and len(bids) == 1:
                    calibre_id = str(bids[0])
                    logger.debug(f"Found Calibre ID {calibre_id} via single title match")

    # 2. calibredb CLI search fallback
    if not calibre_id and CONFIG['IMP_CALIBREDB']:
        res, err, rc = calibredb('search', [f'author:"{author}" title:"{title}"'])
        if not rc and res:
            try:
                calibre_id = res.split(',')[0].strip()
            except IndexError:
                calibre_id = ''

    # 3. Direct metadata.db SQLite lookup fallback if local file path is configured
    if not calibre_id:
        ebook_dir = get_directory('eBook')
        meta_db = os.path.join(ebook_dir, 'metadata.db') if ebook_dir else ''
        if meta_db and os.path.isfile(meta_db):
            try:
                import sqlite3
                conn = sqlite3.connect(f"file:{meta_db}?mode=ro", uri=True)
                if author:
                    q = """SELECT b.id FROM books b
                           JOIN books_authors_link bal ON b.id = bal.book
                           JOIN authors a ON bal.author = a.id
                           WHERE b.title=? COLLATE NOCASE AND a.name=? COLLATE NOCASE LIMIT 1"""
                    row = conn.execute(q, (title, author)).fetchone()
                else:
                    row = conn.execute("SELECT id FROM books WHERE title=? COLLATE NOCASE LIMIT 1", (title,)).fetchone()
                conn.close()
                if row:
                    calibre_id = str(row[0])
            except Exception as e:
                logger.debug(f"Direct metadata.db lookup error: {e}")

    logger.debug(f'Calibre ID [{calibre_id}]')
    return calibre_id
