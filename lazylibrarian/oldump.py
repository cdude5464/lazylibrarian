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

import contextlib
import gzip
import json
import logging
import os
import re
import shutil
import sqlite3
import time
from operator import itemgetter

from curl_cffi import requests

import lazylibrarian
from lazylibrarian import database
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import DIRS
from lazylibrarian.formatter import elapsed_time, format_author_name, get_list, thread_name

logger = logging.getLogger(__name__)

# How often (in downloaded bytes) to log download progress, and to check for a stop request.
DOWNLOAD_PROGRESS_STEP = 200 * 1024 * 1024
# How often (in indexed rows) to log indexing progress.
INDEX_PROGRESS_STEP = 500000
# How often (in indexed rows) to check for a stop request - much more frequent than the
# progress log above, since that can be minutes apart on a slow machine.
STOP_CHECK_STEP = 10000
# Commit transaction periodically during bulk ingest to prevent WAL bloat and ensure durability.
COMMIT_STEP = 50000

# Rough multiplier applied to the combined compressed download size to estimate the extra
# space the indexed sqlite database will need on top of the two dump files it's built from -
# not exact (depends on how many rows have usable ISBN/cover data), just enough to catch
# "this clearly won't fit" before committing to a multi-GB download.
DB_SIZE_ESTIMATE_MULTIPLIER = 2

AUTHORS_DUMP_URL = "https://openlibrary.org/data/ol_dump_authors_latest.txt.gz"
WORKS_DUMP_URL = "https://openlibrary.org/data/ol_dump_works_latest.txt.gz"


def _stop_requested():
    return lazylibrarian.STOPTHREADS and thread_name() == "OLDUMPUPDATE"


def _checkpoint(conn, mode='PASSIVE'):
    """ An explicit WAL checkpoint, replacing SQLite's own frequent small automatic ones
    (see init_dump_db's wal_autocheckpoint comment) with fewer, larger, controlled merges
    at our own commit boundaries. PASSIVE never blocks a reader/writer and merges only what
    it safely can; TRUNCATE (used once, after the whole import) forces a full merge and
    shrinks the WAL file back down, since an unbounded leftover WAL would slow every future
    lookup against this dump too, not just the import itself. """
    try:
        conn.execute(f"PRAGMA wal_checkpoint({mode});")
    except sqlite3.Error as e:
        logger.debug(f"WAL {mode} checkpoint failed (non-fatal, the next one will retry): {e}")


def get_remote_size(url):
    """HEAD request for url's Content-Length. Returns 0 if it can't be determined."""
    try:
        # requests has a dedicated .head() method for HEAD requests
        resp = requests.head(url, timeout=10, impersonate='chrome')
        # It automatically raises exceptions for 4xx/5xx status codes if needed,
        # but to match urllib behavior closely, we just read the headers.
        return int(resp.headers.get('Content-Length', 0))
    except Exception as e:
        logger.warning(f"Unable to check remote size for {url}: {e}")
        return 0


def _local_footprint(dump_dir):
    """Bytes already on disk from a previous run: complete or partial dump downloads, plus
    the sqlite database if it exists. Used to estimate the *additional* space a fresh run
    needs, not the total, since resumed downloads and an already-partly-built database don't
    need to be downloaded/built again."""
    total = 0
    for name in ('ol_dump_authors.txt.gz', 'ol_dump_authors.txt.gz.part',
                 'ol_dump_works.txt.gz', 'ol_dump_works.txt.gz.part'):
        src_path = os.path.join(dump_dir, name)
        if os.path.exists(src_path):
            total += os.path.getsize(src_path)
    db_path = get_dump_db_path()
    if os.path.exists(db_path):
        total += os.path.getsize(db_path)
    return total


def check_disk_space(dump_dir):
    """Preflight check, run before any download starts: estimate how much additional disk
    space this sync needs (remaining downloads + sqlite indexing) and compare against what's
    actually free. Returns (ok, estimated_needed_bytes, free_bytes). Logs a clear estimate
    either way so the numbers are visible in the log even when there's enough room."""
    authors_size = get_remote_size(AUTHORS_DUMP_URL)
    works_size = get_remote_size(WORKS_DUMP_URL)
    dump_total = authors_size + works_size
    estimated_total = dump_total + int(dump_total * DB_SIZE_ESTIMATE_MULTIPLIER)
    already_local = _local_footprint(dump_dir)
    estimated_needed = max(0, estimated_total - already_local)
    free = shutil.disk_usage(dump_dir).free

    def mb(n):
        return n // (1024 * 1024)

    logger.info(f"OpenLibrary dump space estimate: ~{mb(estimated_total)} MB total "
                f"(downloads + indexed database), ~{mb(already_local)} MB already on disk, "
                f"~{mb(estimated_needed)} MB additional needed, {mb(free)} MB free in {dump_dir}")
    return estimated_needed <= free, estimated_needed, free


def get_dump_dir():
    dump_dir = CONFIG['OL_DUMP_DIR']
    if not dump_dir:
        cache_base = DIRS.CACHEDIR if DIRS.CACHEDIR else os.path.join(DIRS.DATADIR, 'cache')
        dump_dir = os.path.join(cache_base, 'openlibrary_dump')
    if not os.path.exists(dump_dir):
        os.makedirs(dump_dir, exist_ok=True)
    return dump_dir

def get_dump_db_path():
    return os.path.join(get_dump_dir(), 'ol_catalog.sqlite3')

def has_column(cursor, table, column):
    columns = cursor.execute(f'PRAGMA table_info({table})').fetchall()
    if not columns:  # no such table
        return False
    return any(item[1] == column for item in columns)

def set_global_ol_counters():
    db_path = get_dump_db_path()
    if not os.path.exists(db_path):
        return
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    author_count = cur.execute("SELECT count(*) from ol_authors").fetchone()
    works_count = cur.execute("SELECT count(*) from ol_works").fetchone()
    lazylibrarian.OL_AUTHORS = author_count[0]
    lazylibrarian.OL_WORKS = works_count[0]
    conn.close()

def init_dump_db(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    # journal_mode=OFF + synchronous=MEMORY (the previous settings here) have no protection
    # at all against an unclean interruption - a killed process or container restart mid
    # write can leave the file genuinely corrupted ("database disk image is malformed"),
    # not just missing its most recent transaction. Confirmed live, twice, this session:
    # this exact file corrupted after being interrupted by a container restart, on this
    # host, where restarts happen often enough for that to matter. WAL + synchronous=NORMAL
    # is the same durability tradeoff the main lazylibrarian.db already uses elsewhere in
    # this codebase (see database.py) - safe against a killed process, still fast enough for
    # bulk loading since it only fsyncs at WAL checkpoints rather than every write.
    cur.execute("PRAGMA journal_mode = WAL;")
    cur.execute("PRAGMA synchronous = NORMAL;")
    cur.execute("PRAGMA cache_size = -65536;")  # 64MB cache (low memory footprint safe for Pi and low-RAM devices)
    cur.execute("PRAGMA temp_store = MEMORY;")
    # philborman, RPi4, 2026-09 (!1847/!1900): a 35-minute import on a laptop SSD takes over
    # 24 hours on a Raspberry Pi - a disproportion far beyond raw storage speed alone. SQLite's
    # default wal_autocheckpoint (1000 pages, ~4MB) auto-fires a WAL checkpoint - which merges
    # back into the main db file with scattered, random writes, not sequential ones - roughly
    # every 4MB written. Over a 15M+ row import that is thousands of forced checkpoints, and
    # random writes are exactly what SD-card/eMMC storage handles catastrophically worse than
    # an SSD (100-1000x slower), while sequential WAL appends themselves stay fast on either.
    # Raised, not disabled outright: disabling auto-checkpoint entirely would let the WAL file
    # itself grow to gigabytes for the whole import, risking exactly the disk-space exhaustion
    # philborman already hit once on this same task (2026-08-25). Explicit PASSIVE checkpoints
    # at our own COMMIT_STEP boundary below replace the frequent automatic ones with far fewer,
    # larger, still-bounded merges instead.
    cur.execute("PRAGMA wal_autocheckpoint = 100000;")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ol_authors (
            author_id TEXT PRIMARY KEY,
            author_name TEXT COLLATE NOCASE
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ol_works (
            work_id TEXT PRIMARY KEY,
            author_id TEXT,
            title TEXT COLLATE NOCASE,
            first_publish_year TEXT,
            cover_i TEXT,
            FOREIGN KEY(author_id) REFERENCES ol_authors(author_id)
        );
    """)

    # schema changes
    for column in ['birth_date', 'death_date', 'bio', 'photos']:
        if not has_column(cur, 'ol_authors', column):
            cur.execute(f"ALTER TABLE ol_authors ADD COLUMN {column} TEXT")

    # There is no data in the works dump file for isbn, asin, publisher, rating, language
    # language and isbn are available for some books using search.json?author=author_id
    for column in ['contributors', 'genres','subtitle','description']:
        if not has_column(cur, 'ol_works', column):
            cur.execute(f"ALTER TABLE ol_works ADD COLUMN {column} TEXT")

    cur.execute("DROP INDEX IF EXISTS idx_ol_authors_name;")
    cur.execute("DROP INDEX IF EXISTS idx_ol_works_author;")
    cur.execute("DROP INDEX IF EXISTS idx_ol_works_title;")

    conn.commit()
    return conn

def download_dump_file(url, local_path):
    """Download url to local_path, skipping the download if a same-size file already
    exists (e.g. left over from a previous run that got interrupted after completing
    this stage). If a `local_path.part` staging file is left over from a run that was
    interrupted mid-download, resumes it with an HTTP Range request instead of
    restarting from byte zero - these dumps are several GB compressed, and a plain
    restart after every interruption (network blip, container restart, OOM) could
    make the download never finish on a slow or flaky connection. Falls back to a
    full restart if the server doesn't honour the Range request (returns 200 instead
    of 206) or the partial file turns out larger than the current remote copy (a new
    dump was published mid-download). Returns True if local_path ends up complete and
    usable."""

    remote_size = get_remote_size(url)
    stopped = False
    if remote_size and os.path.exists(local_path) and os.path.getsize(local_path) == remote_size:
        logger.info(f"{os.path.basename(local_path)} already fully downloaded ({remote_size} bytes), skipping")
        return True

    partial_path = f"{local_path}.part"
    resume_from = 0
    mode = 'wb'
    if os.path.exists(partial_path):
        partial_size = os.path.getsize(partial_path)
        if remote_size and partial_size < remote_size:
            resume_from = partial_size
            mode = 'ab'
        elif partial_size:
            # Either no remote_size to compare against, or the partial file is already
            # as big as (or bigger than) the current remote copy - can't trust it, start over.
            os.remove(partial_path)

    headers = {}
    if resume_from:
        headers['Range'] = f'bytes={resume_from}-'
        logger.info(f"Resuming {os.path.basename(local_path)} from byte {resume_from} "
                   f"({resume_from * 100 // remote_size}% already downloaded)")
    else:
        logger.info(f"Downloading {url} -> {local_path}...")

    try:
        # requests.get automatically follows redirects and handles the request
        resp = requests.get(url, headers=headers, stream=True, impersonate='chrome')
        # Raise an exception for HTTP errors (4xx or 5xx codes)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        # e.response holds the response object where we can check the status code
        if resume_from and e.response.status_code == 416:
            # Range not satisfiable - our partial file is already complete/stale, restart clean.
            logger.warning(f"Server rejected resume of {os.path.basename(local_path)}, restarting from scratch")
            with contextlib.suppress(OSError):
                os.remove(partial_path)
            return download_dump_file(url, local_path)
        logger.error(f"HTTP error downloading {url}: {e}")
        return False
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Network connection error downloading {url}: {e}")
        return False
    except requests.exceptions.RequestException as e:
        # This catches any other requests-specific issues (e.g., Timeouts)
        logger.error(f"Unexpected requests error downloading {url}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error downloading {url}: {e}")
        return False

    if str(resp.status_code).startswith('2'):  # 200, 206
        if resume_from and resp.status_code != 206:
            # Server ignored the Range header and is sending the whole file again - can't
            # append what we already have on top of that, so restart the file cleanly.
            logger.warning(f"Server didn't honour resume for {os.path.basename(local_path)} "
                           f"(status {resp.status_code}), restarting from scratch")
            resume_from = 0
            mode = 'wb'
        downloaded = resume_from
        next_log_at = downloaded + DOWNLOAD_PROGRESS_STEP
        stopped = False
        chunk_size = 1024 * 1024
        with open(partial_path, mode) as out:
            for chunk in resp.iter_content(chunk_size=chunk_size):
                if _stop_requested():
                    logger.debug(f"STOPTHREADS Aborting {os.path.basename(local_path)} download "
                                 f"at {downloaded // chunk_size} MB, will resume next run")
                    stopped = True
                    break
                if not chunk:
                    break
                out.write(chunk)
                downloaded += len(chunk)
                if downloaded >= next_log_at:
                    if remote_size:
                        logger.info(f"{os.path.basename(local_path)}: {downloaded // chunk_size} MB "
                                   f"({downloaded * 100 // remote_size}%)")
                    else:
                        logger.info(f"{os.path.basename(local_path)}: {downloaded // chunk_size} MB")
                    next_log_at = downloaded + DOWNLOAD_PROGRESS_STEP

    if stopped:
        return False

    downloaded_size = os.path.getsize(partial_path)
    if remote_size and downloaded_size != remote_size:
        logger.error(f"Download of {url} incomplete: got {downloaded_size} bytes, expected {remote_size} "
                     f"- left as {partial_path} to resume next run")
        return False

    os.replace(partial_path, local_path)
    logger.info(f"{os.path.basename(local_path)} download complete ({downloaded_size} bytes)")
    return True


def update_openlibrary_dump():
    """Scheduled (or manually-triggered, see webServe.force_openlibrary_dump) task to
    download and stream OpenLibrary author & work dumps into local SQLite database.
    Safe to interrupt and re-run: already-complete downloads are skipped, an
    interrupted download resumes via HTTP Range rather than restarting, and indexing
    uses INSERT OR REPLACE so re-processing a file is idempotent."""
    if not CONFIG['OL_USE_DUMP']:
        logger.debug("OpenLibrary local dump importing disabled in configuration")
        return

    lazylibrarian.OL_UPDATING = True
    incoming_threadname = thread_name()
    thread_name('OLDUMPUPDATE')
    dump_dir = get_dump_dir()
    db_path = get_dump_db_path()
    logger.info(f"Starting OpenLibrary Bulk Dump Sync -> {db_path}")

    jobdb = database.DBConnection()
    logger.debug(f"Storing start time for {thread_name()}")
    start_time = time.time()
    jobdb.upsert("jobs", {"Start": start_time}, {"Name": thread_name()})

    conn = None
    try:
        space_ok, needed, free = check_disk_space(dump_dir)
        if not space_ok:
            logger.error(f"Aborting OpenLibrary dump sync: estimated ~{needed // (1024 * 1024)} MB "
                         f"needed but only {free // (1024 * 1024)} MB free in {dump_dir} - free up space "
                         f"or point OL_DUMP_DIR somewhere with more room, then try again")
            return

        conn = init_dump_db(db_path)
        cur = conn.cursor()

        # 1. Ingest Authors Dump
        authors_gz = os.path.join(dump_dir, 'ol_dump_authors.txt.gz')
        if not download_dump_file(AUTHORS_DUMP_URL, authors_gz):
            logger.error("Aborting OpenLibrary dump sync: authors download failed or incomplete")
            return

        logger.info("Indexing OpenLibrary Authors into local database...")
        batch = []
        indexed = 0
        authors_stopped = False
        with gzip.open(authors_gz, 'rt', encoding='utf-8', errors='ignore') as f:
            for line in f:
                parts = line.strip().split('\t')
                if len(parts) >= 5:
                    key = parts[1].split('/')[-1]
                    try:
                        data = json.loads(parts[4])
                        name = data.get('name', '')
                        if key and name:
                            birth_date = data.get('birth_date', '')
                            death_date = data.get('death_date', '')
                            bio = data.get('bio', '')
                            if bio and isinstance(bio, dict):
                                bio = bio.get('value', '')
                            photos = data.get('photos', '')
                            if photos and isinstance(photos, list):
                                photos = photos[0]
                            batch.append((key, name, birth_date, death_date, bio, str(photos)))
                    except Exception as e:
                        logger.debug(f"Exception: {e}")
                if len(batch) >= STOP_CHECK_STEP:
                    cur.executemany("INSERT OR REPLACE INTO ol_authors (author_id, author_name, birth_date, death_date, bio, photos) VALUES (?, ?, ?, ?, ?, ?)", batch)
                    indexed += len(batch)
                    batch = []
                    if indexed % COMMIT_STEP == 0:
                        conn.commit()
                    if indexed % INDEX_PROGRESS_STEP < STOP_CHECK_STEP:
                        logger.info(f"Imported {indexed} authors so far...")
                    if _stop_requested():
                        logger.debug(f"STOPTHREADS Aborting author importing at {indexed} rows, "
                                     f"will re-import (idempotent) next run")
                        authors_stopped = True
                        break

        if batch and not authors_stopped:
            cur.executemany("INSERT OR REPLACE INTO ol_authors (author_id, author_name, birth_date, death_date, bio, photos) VALUES (?, ?, ?, ?, ?, ?)", batch)
            indexed += len(batch)
        conn.commit()
        logger.info(f"Imported {indexed} authors total{' (stopped early)' if authors_stopped else ''}")

        if authors_stopped:
            return

        # 2. Ingest Works Dump
        works_gz = os.path.join(dump_dir, 'ol_dump_works.txt.gz')
        if not download_dump_file(WORKS_DUMP_URL, works_gz):
            logger.error("Aborting OpenLibrary dump sync: works download failed or incomplete")
            return

        logger.info("Importing OpenLibrary Works into local database...")
        batch = []
        indexed = 0
        works_stopped = False
        with gzip.open(works_gz, 'rt', encoding='utf-8', errors='ignore') as f:
            for line in f:
                parts = line.strip().split('\t')
                if len(parts) >= 5:
                    key = parts[1].split('/')[-1]
                    try:
                        data = json.loads(parts[4])
                        title = data.get('title', '')
                        authors = data.get('authors', [])
                        author_id = ''
                        if authors:
                            try:
                                a_ref = authors[0].get('author', {}).get('key', '')
                            except AttributeError:
                                a_ref = authors[0].get('author', {})
                            if a_ref:
                                author_id = a_ref.split('/')[-1]
                        try:
                            description = data.get('description', '').get('value', '')
                        except AttributeError:
                            description = ''
                        subtitle = data.get('subtitle', '')
                        genres = data.get('subjects', '')
                        if genres:
                            genres = ','.join(genres)
                        secondaries = []
                        if len(authors) > 1:
                            others = authors[1:]
                            for author in others:
                                try:
                                    a_ref = author.get('author', {}).get('key', '')
                                except AttributeError:
                                    a_ref = author.get('author', {})
                                if a_ref:
                                    secondaries.append(a_ref.split('/')[-1])
                        contributors = ','.join(secondaries)

                        covers = data.get('covers', [])
                        cover_i = str(covers[0]) if covers else ''
                        # 'created' is when this record was catalogued into OpenLibrary, not
                        # when the book was published - OL's own dump was largely bulk-imported
                        # from old MARC catalogs around 2009, so using 'created' silently stamps
                        # a huge fraction of works with a meaningless ~2009 "publish year". The
                        # real field is 'first_publish_date' (format varies - plain year, or a
                        # fuller date like "March 1989" - extract the first 4-digit run either
                        # way rather than assuming a fixed format).
                        first_publish_date = ''
                        year_match = re.search(r'\d{4}', data.get('first_publish_date', '') or '')
                        if year_match:
                            first_publish_date = year_match.group(0)
                        if key and title and author_id:
                            batch.append((key, author_id, title, first_publish_date, cover_i, contributors, genres, subtitle, description))
                    except Exception as e:
                        logger.debug(f"Exception: {e}")

                if len(batch) >= STOP_CHECK_STEP:
                    cur.executemany("""INSERT OR REPLACE INTO ol_works (work_id, author_id, title, first_publish_year, cover_i,
                                        contributors, genres, subtitle, description) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", batch)
                    indexed += len(batch)
                    batch = []
                    if indexed % COMMIT_STEP == 0:
                        conn.commit()
                    if indexed % INDEX_PROGRESS_STEP < STOP_CHECK_STEP:
                        logger.info(f"Imported {indexed} works so far...")
                    if _stop_requested():
                        logger.debug(f"STOPTHREADS Aborting works importing at {indexed} rows, "
                                     f"will re-import (idempotent) next run")
                        works_stopped = True
                        break

        if batch and not works_stopped:
            cur.executemany("""INSERT OR REPLACE INTO ol_works (work_id, author_id, title, first_publish_year, cover_i,
                                contributors, genres, subtitle, description) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", batch)
            indexed += len(batch)
        conn.commit()
        logger.info(f"Imported {indexed} works total{' (stopped early)' if works_stopped else ''}")
        if works_stopped:
            logger.info("OpenLibrary Bulk Dump importing stopped (shutdown requested).")
        else:
            logger.info("OpenLibrary Bulk Dump indexing started.")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ol_authors_name ON ol_authors(author_name);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ol_works_author ON ol_works(author_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ol_works_title ON ol_works(title);")
            logger.info("OpenLibrary Bulk Dump indexing complete.")
            author_count = cur.execute("SELECT count(*) from ol_authors").fetchone()
            works_count = cur.execute("SELECT count(*) from ol_works").fetchone()
            lazylibrarian.OL_AUTHORS = author_count[0]
            lazylibrarian.OL_WORKS = works_count[0]

    except Exception as e:
        logger.error(f"Error updating OpenLibrary bulk dump: {e}")
    finally:
        if conn:
            conn.close()
        finish_time = time.time()
        lazylibrarian.OL_UPDATING = False
        logger.debug(f"Storing finish time for {thread_name()}")
        jobdb.upsert("jobs", {"Finish": finish_time}, {"Name": thread_name()})
        jobdb.close()
        timestr = elapsed_time(finish_time - start_time)
        logger.debug(f"{thread_name()} completed in {timestr}")
        thread_name(incoming_threadname)


def query_local_dump_authorid_of_book(author_name, title):
    """Search local dump database for author ID by name and book title."""
    if lazylibrarian.OL_UPDATING or not CONFIG['OL_USE_DUMP']:
        logger.debug(f"Not querying local dump for {author_name}:{title}{': updating' if lazylibrarian.OL_UPDATING else ': disabled'}")
        return None

    logger.debug(f"Query local dump for {author_name}:{title}")
    db_path = get_dump_db_path()
    if not os.path.exists(db_path):
        return None
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cmd = ('SELECT ol_authors.author_id, author_name FROM ol_authors,ol_works WHERE '
               'ol_authors.author_id = ol_works.author_id and author_name = ? COLLATE NOCASE '
               'and title = ? COLLATE NOCASE')
        cur.execute(cmd, (author_name, title))
        res = cur.fetchone()
        conn.close()
        if res:
            logger.debug(f"Local dump returning {res[0]}:{res[1]}")
            return {'authorid': res[0], 'authorname': res[1]}
    except Exception as e:
        logger.error(f"Local dump bookauthor query error: {e}")
    return None


def query_local_dump_pubdate(author_name, title):
    """ Look up a book's first_publish_year in the local OpenLibrary dump by author name +
    title. Purely local (no network call, no rate limit, no daily quota) - worth trying before
    any of the remote pubdate fallbacks (GoodReads/HardCover/GoogleBooks), not just as a last
    resort, whenever OL_USE_DUMP is enabled and the dump has already been synced. Returns a
    4-digit year string, or '' if not found / no dump available. """
    if lazylibrarian.OL_UPDATING or not CONFIG['OL_USE_DUMP']:
        logger.debug(f"Not querying local dump for {author_name}:{title}{': updating' if lazylibrarian.OL_UPDATING else ': disabled'}")
        return ''

    db_path = get_dump_db_path()
    if not os.path.exists(db_path):
        return ''
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cmd = ("SELECT ol_works.first_publish_year FROM ol_authors, ol_works WHERE "
               "ol_authors.author_id = ol_works.author_id AND "
               "author_name = ? COLLATE NOCASE AND title = ? COLLATE NOCASE AND "
               "first_publish_year IS NOT NULL AND first_publish_year != ''")
        cur.execute(cmd, (author_name, title))
        res = cur.fetchone()
        conn.close()
        if res and res[0]:
            logger.debug(f"Local dump pubdate for {author_name}:{title} -> {res[0]}")
            return res[0]
    except Exception as e:
        logger.error(f"Local dump pubdate query error: {e}")
    return ''


def query_local_dump_author_info(author_id):
    """Search local dump database for author by ID."""
    if lazylibrarian.OL_UPDATING or not CONFIG['OL_USE_DUMP']:
        logger.debug(f"Not querying local dump for {author_id}{': updating' if lazylibrarian.OL_UPDATING else ': disabled'}")
        return {}

    logger.debug(f"Query local dump info for {author_id}")
    db_path = get_dump_db_path()
    if not os.path.exists(db_path):
        return {}
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT author_id, author_name, birth_date, death_date, bio, photos FROM ol_authors WHERE author_id = ?", (author_id,))
        res = cur.fetchone()
        books = cur.execute("SELECT count(*) as counter FROM ol_works WHERE author_id = ?", (author_id,)).fetchone()
        conn.close()
        if res:
            d = {
            'authorid': res[0],
            'authorlink': '/'.join([CONFIG['OL_URL'], "authors", res[0]]),
            'authorimg': res[5],
            'authorborn': res[2],
            'authordeath': res[3],
            'about': res[4],
            'totalbooks': str(books[0]),
            'authorname': format_author_name(res[1], postfix=get_list(CONFIG.get_csv('NAME_POSTFIX')))
            }
            logger.debug(f"Local dump returning {d}")
            return d
    except Exception as e:
        logger.error(f"Local dump authorid query error: {e}")
    return {}

def query_local_dump_authorid(author_name, full=False):
    """Search local dump database for author ID by name """
    if lazylibrarian.OL_UPDATING or not CONFIG['OL_USE_DUMP']:
        logger.debug(f"Not querying local dump for {author_name}{': updating' if lazylibrarian.OL_UPDATING else ': disabled'}")
        return None

    logger.debug(f"Query local dump authorid for {author_name}")
    db_path = get_dump_db_path()
    if not os.path.exists(db_path):
        return None
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT author_id, author_name FROM ol_authors WHERE author_name = ? COLLATE NOCASE", (author_name,))
        res = cur.fetchall()
        if not res:
            conn.close()
            return None

        # Return the one with the most books
        authors = []
        for auth in res:
            books = cur.execute("SELECT count(*) as counter FROM ol_works WHERE author_id = ?", (auth[0],)).fetchone()
            authors.append((auth[0], auth[1], books[0]))
        conn.close()
        authors = sorted(authors, key=itemgetter(2), reverse=True)
        if full:
            logger.debug(f"Local dump returning {authors}")
            return authors
        logger.debug(f"Local dump returning {authors[0][0]}:{authors[0][1]}")
        return {'authorid': authors[0][0], 'authorname': authors[0][1]}
    except Exception as e:
        logger.error(f"Local dump author query error: {e}")
    return None

def query_local_dump_books(author_id):
    """Query local dump database for all works belonging to an author ID."""
    if lazylibrarian.OL_UPDATING or not CONFIG['OL_USE_DUMP']:
        logger.debug(f"Not querying local dump for {author_id}{': updating' if lazylibrarian.OL_UPDATING else ': disabled'}")
        return []

    logger.debug(f"Query local dump books for {author_id}")
    db_path = get_dump_db_path()
    if not os.path.exists(db_path):
        return []
    docs = []
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT work_id, title, first_publish_year, cover_i, contributors, genres, subtitle, description FROM ol_works WHERE author_id = ?", (author_id,))
        rows = cur.fetchall()
        conn.close()
        for r in rows:
            # make it look like the results from search.json
            docs.append({
                'key': f"/works/{r[0]}",
                'title': r[1],
                'first_publish_year': r[2],
                'cover_i': r[3],
                'contributors': r[4],
                'genres': r[5],
                'subtitle': r[6],
                'description': r[7],
                'author_key': [author_id]
            })
    except Exception as e:
        logger.error(f"Local dump books query error: {e}")
    logger.debug(f"Local dump returning {len(docs)}")
    return docs
