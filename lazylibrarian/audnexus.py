#  This file is part of LazyLibrarian.
#
#  LazyLibrarian is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  LazyLibrarian is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with LazyLibrarian.  If not, see <http://www.gnu.org/licenses/>.

"""
Audnexus (https://audnex.us) audiobook metadata enrichment.

Audnexus is a free API that returns rich audiobook metadata (narrators, series,
genres, cover, runtime, description) keyed on an Audible ASIN. It is used here
to fill in audiobook-specific fields - most importantly Narrator - that the
book-centric metadata providers (GoogleBooks / OpenLibrary / HardCover /
GoodReads) do not supply.

It is an enricher, not a search provider: it looks a book up by ASIN, it does
not search by title. The ASIN comes from the existing books.ASIN column (for
example captured from HardCover edition data or populated on author refresh).
Audnexus is region specific, so a book not available in one region is retried
in the next.
"""

import logging

from curl_cffi import requests

from lazylibrarian import database
from lazylibrarian.blockhandler import BLOCKHANDLER
from lazylibrarian.config2 import CONFIG
from lazylibrarian.formatter import check_int
from lazylibrarian.telemetry import TELEMETRY

BASE_URL = "https://api.audnex.us"
PROVIDER = "audnexus"
DEFAULT_REGIONS = ("us", "uk", "ca", "au")


class Audnexus:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.timeout = check_int(CONFIG.get_int("HTTP_TIMEOUT"), 30) or 30

    def get_book(self, asin, regions=DEFAULT_REGIONS):
        """
        Return normalized audiobook metadata for an Audible ASIN, or {} if the
        ASIN could not be resolved in any of the requested regions.
        """
        asin = (asin or "").strip()
        if not asin or BLOCKHANDLER.is_blocked(PROVIDER):
            return {}
        for region in regions:
            data = self._fetch(f"/books/{asin}", region)
            if data:
                TELEMETRY.record_usage_data("Metadata/Audnexus")
                return self._parse_book(data)
        self.logger.debug(f"Audnexus: no audiobook for ASIN {asin} in regions {regions}")
        return {}

    def _fetch(self, path, region):
        try:
            r = requests.get(
                f"{BASE_URL}{path}",
                params={"region": region},
                impersonate='chrome',
                timeout=self.timeout,
            )
        except requests.exceptions.RequestException as e:
            self.logger.debug(f"Audnexus request error for {path} ({region}): {e}")
            return None

        if r.status_code == 200:
            try:
                return r.json()
            except ValueError:
                self.logger.debug(f"Audnexus: invalid JSON for {path} ({region})")
                return None

        if r.status_code == 429:
            retry = check_int(r.headers.get("Retry-After", 0), 0) or 60
            BLOCKHANDLER.block_provider(PROVIDER, "rate limited", delay=retry)
            self.logger.debug(f"Audnexus rate limited, backing off for {retry}s")
            return None

        # 404 / REGION_UNAVAILABLE just means "not in this region" - try the next
        self.logger.debug(f"Audnexus {path} region={region} returned HTTP {r.status_code}")
        return None

    @staticmethod
    def _parse_book(data):
        def names(key):
            return [item.get("name", "").strip()
                    for item in (data.get(key) or []) if item.get("name")]

        series = data.get("seriesPrimary") or {}
        return {
            "asin": data.get("asin", ""),
            "title": data.get("title", ""),
            "authors": names("authors"),
            "narrators": names("narrators"),
            "series_name": series.get("name", ""),
            "series_position": series.get("position", ""),
            "genres": names("genres"),
            "description": data.get("description", "") or data.get("summary", ""),
            "publisher": data.get("publisherName", ""),
            "release_date": data.get("releaseDate", ""),
            "runtime_minutes": data.get("runtimeLengthMin"),
            "language": data.get("language", ""),
            "image": data.get("image", ""),
            "region": data.get("region", ""),
        }


def enrich_audiobook(bookid, db=None):
    """
    Fill audiobook-only fields (Narrator, BookGenre, BookDesc, BookImg) for an
    owned audiobook that has an ASIN, using Audnexus.

    Cheap early-out: does nothing unless the AUDNEXUS toggle is on, the book is
    an owned audiobook, it has an ASIN, and at least one of those fields is
    still empty. Each field is written only when empty, so it never overwrites a
    value that is already set. Returns True if it wrote anything.
    """
    if not CONFIG.get_bool("AUDNEXUS"):
        return False

    logger = logging.getLogger(__name__)
    close = db is None
    if close:
        db = database.DBConnection()
    try:
        row = db.match(
            "SELECT ASIN, Narrator, AudioStatus, AudioFile, BookGenre, BookDesc, BookImg, BookName "
            "FROM books WHERE BookID=?", (bookid,))
        if not row:
            return False
        # only owned audiobooks, with an ASIN, that are still missing at least
        # one field we can fill (narrator, genre, description or cover)
        owned_audio = (row["AudioFile"] and row["AudioFile"].strip()) or \
                      row["AudioStatus"] in ("Open", "Have")
        needs_enrich = (not row["Narrator"] or not row["BookGenre"] or not row["BookDesc"]
                        or not row["BookImg"] or row["BookImg"] == "images/nocover.png")
        if not owned_audio or not row["ASIN"] or not needs_enrich:
            return False

        data = Audnexus().get_book(row["ASIN"])
        if not data:
            return False

        updates = {}
        narrators = ", ".join(data.get("narrators") or [])
        if narrators and not row["Narrator"]:
            updates["Narrator"] = narrators
        if data.get("genres") and not row["BookGenre"]:
            updates["BookGenre"] = ", ".join(data["genres"])
        if data.get("description") and not row["BookDesc"]:
            updates["BookDesc"] = data["description"]
        if data.get("image") and (not row["BookImg"] or row["BookImg"] == "images/nocover.png"):
            updates["BookImg"] = data["image"]

        if not updates:
            return False
        cols = ", ".join(f"{k}=?" for k in updates)
        db.action(f"UPDATE books SET {cols} WHERE BookID=?", tuple(updates.values()) + (bookid,))
        logger.debug(f"Audnexus enriched {row['BookName']} ({row['ASIN']}): {list(updates)}")
        return True
    finally:
        if close:
            db.close()
