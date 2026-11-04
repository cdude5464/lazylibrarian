# Biblioteka Narodowa (National Library of Poland) metadata source
# Adapted from lazylibrarian/dnb.py (Calibre-Web Automated DNB provider)
# SPDX-License-Identifier: GPL-3.0-or-later

# API documentation: https://data.bn.org.pl/docs/bibs
# example
# https://data.bn.org.pl/api/institutions/bibs.marcxml?author=Sapkowski&title=Krew%20elfow&limit=10

import contextlib
import datetime
import logging
import re
import traceback
import unicodedata
from queue import Queue
from urllib.parse import urlencode

# Two different iso639 libraries.
# The first library used languages, but does not support python 3.12
# The new library is recently updated and uses Lang
try:
    from iso639 import Lang
except (ImportError, ModuleNotFoundError):
    Lang = None
try:
    from iso639 import languages as iso_langs
except (ImportError, ModuleNotFoundError):
    iso_langs = None
try:
    from lxml import etree
except ImportError:
    etree = None

from rapidfuzz import fuzz
from rapidfuzz.utils import default_process

import lazylibrarian
from lazylibrarian import database
from lazylibrarian.blockhandler import BLOCKHANDLER
from lazylibrarian.bookdict import (
    add_author_books_to_db,
    add_bookdict_to_db,
    validate_bookdict,
    warn_about_bookdict,
)
from lazylibrarian.cache import fetch_url
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import DIRS, syspath
from lazylibrarian.formatter import (
    get_list,
    is_valid_isbn,
    plural,
    replace_all,
    strip_quotes,
    thread_name,
    unaccented,
)
from lazylibrarian.provider_utils import get_hashed_filename, is_in_cache, read_from_cache


class BN:
    def __init__(self):
        return

    __bnname__ = "Biblioteka Narodowa"
    __bnid__ = "bn"

    logger = logging.getLogger(__name__)
    searchinglogger = logging.getLogger('special.searching')
    active = True

    # Configuration defaults, same meaning as in dnb.py
    cfg_guess_series = True
    cfg_append_edition_to_title = False
    cfg_fetch_subjects = 2  # Both DBN and non-DBN subjects
    cfg_skip_series_starting_with_publishers_name = True
    # Publishers' imprint series, not real book series
    cfg_unwanted_series_names = [
        r'^Seria z ', r'^Kanon na koniec wieku', r'^Kolekcja Gazety Wyborczej', r'^Biblioteka Gazety Wyborczej',
        r'^Lektura', r'^Klasyka', r'^Kieszonkowa', r'^Fantastyka$', r'^Kryminał$', r'^Literatura faktu$',
        r'^Proza$', r'^Powieść$', r'^Mistrzowie Literatury', r'^Nowy Kanon', r'^Bestseller', r'^Seria kryminalna',
    ]
    # Each results page holds up to 100 records, stop paging an author search after this many pages.
    # Pages come oldest record first, so a low limit loses an author's newest books
    cfg_max_pages = 50
    # BN 'language' filter values, keyed by what IMP_PREFLANG may hold for that language
    BN_LANGUAGES = {
        'polski': ['pl', 'pol', 'polish', 'polski'],
        'angielski': ['en', 'eng', 'en-us', 'en-gb', 'english'],
        'niemiecki': ['de', 'ger', 'deu', 'german'],
        'francuski': ['fr', 'fre', 'fra', 'french'],
        'hiszpański': ['es', 'spa', 'spanish'],
        'włoski': ['it', 'ita', 'italian'],
        'rosyjski': ['ru', 'rus', 'russian'],
        'ukraiński': ['uk', 'ukr', 'ukrainian'],
        'czeski': ['cs', 'cze', 'ces', 'czech'],
    }
    # Relator terms ($e) or codes ($4) BN uses for the writer of a book
    AUTHOR_RELATORS = ('autor', 'aut', 'tekst', 'scenariusz')
    # Longest author name tried when splitting free text into title and author
    cfg_max_author_words = 3

    QUERYURL = 'https://data.bn.org.pl/api/institutions/bibs.marcxml?%s'
    BOOKURL = ('https://katalogi.bn.org.pl/discovery/search?query=any,contains,%s'
               '&vid=48OMNIS_NLOP:48OMNIS_NLOP')
    NS = {'marc21': 'http://www.loc.gov/MARC21/slim'}

    def _search(self, query: str, generic_cover: str = "", start=0, limit=10) -> tuple[list, bool, int]:
        """ Return a list of meta records, whether the results came from cache,
            and the sinceId to fetch the next page from (0 if no more pages) """
        try:
            if not self.active:
                return [], False, 0

            val = []
            in_cache = 0
            next_start = 0

            # Parse query for special identifiers
            bnid = None
            isbn = ''
            title = ''
            author = ''

            # Check if query contains special identifiers
            free_text = False
            if query.startswith('bn-id:'):
                bnid = query.replace('bn-id:', '').strip()
            elif query.startswith('isbn:'):
                isbn = query.replace('isbn:', '').strip()
            elif '<ll>' in query:
                title, author = query.split('<ll>')
                # eg the api findBook sends 'title<ll>' with no author, that is free text too
                free_text = not author.strip()
            else:
                # Free text, may hold title and author words in any order
                title = query
                free_text = True

            # Query variations get increasingly fuzzy, use the first one that finds anything.
            # Free text has no single right variation, so merge the results of all of them,
            # without paging as sinceId only applies to one query
            queries = self._create_query_variations(bnid, isbn, author, title)
            # Filter on the server, BN holds many translations that would only be dropped later
            language = '' if bnid or isbn else self._bn_language()
            seen = set()
            for params in queries:
                try:
                    if language:
                        params['language'] = language
                    results, cached = self._execute_query(params, start=0 if free_text else start, limit=limit)
                    in_cache += cached
                    if not results:
                        continue

                    if not free_text and len(results) >= limit:
                        last_id = self._api_id(self._controlfield(results[-1], '001'))
                        if last_id:
                            next_start = last_id + 1

                    for record in results:
                        record_id = self._controlfield(record, '001')
                        if record_id:
                            if record_id in seen:
                                continue
                            seen.add(record_id)
                        book_data = self._parse_marc21_record(record)
                        if book_data:
                            meta_record = self._create_meta_record(book_data, generic_cover)
                            if meta_record:
                                val.append(meta_record)
                    if not free_text:
                        break

                except Exception as e:
                    self.logger.warning(f"BN search error: {e}")
                    continue

            return val, bool(in_cache), next_start

        except Exception as e:
            self.logger.error(f"BN search failed for query '{query}': {e}")
            return [], False, 0

    def _create_query_variations(self, bnid=None, isbn=None, authors=None, title=None):
        """Create API query parameter variations with increasing fuzziness"""
        queries = []

        if bnid:
            queries.append({'id': self._api_id(bnid)})
        elif isbn:
            # BN does not match isbn-10 against isbn-13, try both
            for isbn_form in self._isbn_forms(isbn):
                queries.append({'isbnIssn': isbn_form})
        else:
            # BN also matches title words in series statements, so a series suffix
            # like 'Krew elfów (Wiedźmin, #3)' finds translations instead of the book
            if title:
                title = re.sub(r'\s*\([^)]*\)\s*$', '', title).strip() or title
            if title and authors:
                query_author = " ".join(authors.split())
                title_tokens = title.split()
                if title_tokens:
                    queries.append({'author': query_author, 'title': " ".join(title_tokens)})
                # Polish joiner removal for fuzzy matching
                polish_tokens = self._strip_polish_joiners(title_tokens)
                if polish_tokens and polish_tokens != title_tokens:
                    queries.append({'author': query_author, 'title': " ".join(polish_tokens)})
            elif title:
                title_tokens = title.split()
                if title_tokens:
                    queries.append({'title': " ".join(title_tokens)})
                    # BN needs every title word in the title, so try each split of free text
                    # like "Najstarszy Paolini" into title and a short author name
                    for i in range(1, len(title_tokens)):
                        if len(title_tokens) - i <= self.cfg_max_author_words:
                            queries.append({'title': " ".join(title_tokens[:i]),
                                            'author': " ".join(title_tokens[i:])})
                        if i <= self.cfg_max_author_words:
                            queries.append({'author': " ".join(title_tokens[:i]),
                                            'title': " ".join(title_tokens[i:])})
                    if len(title_tokens) <= self.cfg_max_author_words:
                        queries.append({'author': " ".join(title_tokens)})
                polish_tokens = self._strip_polish_joiners(title_tokens)
                if polish_tokens and polish_tokens != title_tokens:
                    queries.append({'title': " ".join(polish_tokens)})
            elif authors:
                author_tokens = authors.split()
                if author_tokens:
                    queries.append({'author': " ".join(author_tokens)})

        return queries

    def _execute_query(self, params, start=0, limit=10):
        """Query BN bibs API, return list of MARC21 records and whether they came from cache"""
        if not etree:
            self.logger.error('BN query unavailable: lxml module missing')
            return [], False
        headers = {
            'Accept': 'application/xml, text/xml',
            'Accept-Language': 'en-US,en;q=0.9,pl;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive'
        }

        self.logger.debug(f'BN Query: {params}')

        # BN only matches composed characters, but LL stores author names decomposed,
        # eg 'Ż' as 'Z' plus a combining dot, which finds a fraction of an author's books
        params = {key: unicodedata.normalize('NFC', value) if isinstance(value, str) else value
                  for key, value in params.items()}
        params['limit'] = limit
        if start:
            params['sinceId'] = start
        query_url = self.QUERYURL % urlencode(params)
        self.logger.debug(f'BN Query URL: {query_url}')
        try:
            cache_location = DIRS.get_cachedir('XMLCache')
            filename = query_url
            hashfilename, myhash = get_hashed_filename(cache_location, filename)
            # CACHE_AGE is in days, so get it to seconds
            expire_older_than = CONFIG.get_int('CACHE_AGE') * 24 * 60 * 60
            valid_cache = is_in_cache(expire_older_than, hashfilename, myhash)
            if valid_cache:
                lazylibrarian.CACHE_HIT += 1
                self.logger.debug(f"CacheHandler: Returning CACHED response {hashfilename}")
                source, ok = read_from_cache(hashfilename)
                if not ok:
                    return [], False
                xml_data = etree.XML(source)
            else:
                lazylibrarian.CACHE_MISS += 1
                if BLOCKHANDLER.is_blocked('BN'):
                    return [], False

                content, ok = fetch_url(query_url, headers=headers, raw=True)
                if not ok:
                    self.logger.error(f'BN query error: {content}')
                    if 'status 429' in str(content) or 'status 503' in str(content):
                        BLOCKHANDLER.block_provider_backoff('BN', str(content))
                    return [], False

                xml_data = etree.XML(content)
                self.logger.debug(f"CacheHandler: Storing xml {hashfilename}")
                with open(syspath(hashfilename), "wb") as cachefile:
                    cachefile.write(content)

            records = xml_data.xpath("./collection/marc21:record", namespaces=self.NS)
            self.logger.info(f'BN found {len(records)} records')
            return records, valid_cache
        except Exception as e:
            self.logger.error(f'BN query error: {e}')
            self.logger.error(f'{traceback.format_exc()}')
            return [], False  # Return empty list, not None

    def _parse_marc21_record(self, record):
        """Parse MARC21 XML record into book data"""
        ns = self.NS

        book = {
            'series': None,
            'series_index': None,
            'pubdate': None,
            'languages': [],
            'title': None,
            'authors': [],
            'comments': None,
            'bnid': None,
            'isbn': None,
            'isbns': [],
            'edition': None,
            'subjects_dbn': [],
            'subjects_non_dbn': [],
            'publisher_name': None,
            'publisher_location': None,
        }

        # Leader position 6 is the type of record, 7 the bibliographic level.
        # Only keep monographs that are text or spoken word (audiobooks),
        # skip serials, articles, music, film, maps etc.
        with contextlib.suppress(IndexError, AttributeError):
            leader = record.xpath("./marc21:leader", namespaces=ns)[0].text
            if leader[6] not in ('a', 'i') or leader[7] != 'm':
                return None

        # Extract BN record number
        book['bnid'] = self._controlfield(record, '001')
        if not book['bnid']:
            return None

        # Extract publisher info from field 264/260
        # (before title, as series cleaning needs the publisher name)
        self._extract_publisher_info(record, book, ns)

        # Extract title from field 245
        self._extract_title_and_series(record, book, ns)

        # Extract series from fields 800/830 if not in title
        if not book['series']:
            self._extract_series(record, book, ns)

        # Extract authors from fields 100/700
        self._extract_authors(record, book, ns)

        # Extract ISBN from field 020
        self._extract_isbn(record, book, ns)

        # Extract subjects
        self._extract_subjects(record, book, ns)

        # Extract languages from field 041/008
        self._extract_languages(record, book, ns)

        # Extract comments from field 520
        self._extract_comments(record, book, ns)

        # Extract edition from field 250
        self._extract_edition(record, book, ns)

        # Apply series guessing if enabled
        if self.cfg_guess_series and (not book['series'] or not book['series_index']):
            self._guess_series_from_title(book)

        return book

    def _controlfield(self, record, tag):
        """Return the text of a MARC21 controlfield or empty string"""
        try:
            return record.xpath(f"./marc21:controlfield[@tag='{tag}']", namespaces=self.NS)[0].text.strip()
        except (IndexError, AttributeError):
            return ''

    @staticmethod
    def _api_id(bnid):
        """Convert BN record number (b0000005382027) to the numeric id the api uses (5382027)"""
        try:
            return int(str(bnid).lstrip('bB'))
        except ValueError:
            return 0

    @staticmethod
    def _strip_isbd(text):
        """Remove trailing ISBD punctuation BN keeps in subfields, eg 'Krew elfów /' or 'Warszawa :'"""
        if text:
            text = re.sub(r'[\s/:;,=+]+$', '', text.strip())
            # Remove a trailing full stop, but not from an abbreviation or initial like 'T.' or 'Bd.'
            if text.endswith('.') and not re.search(r'(\b\w{1,2}|\.\w+)\.$', text):
                text = text[:-1]
        return text

    def _extract_title_and_series(self, record, book, ns):
        """Extract title and series from MARC21 field 245"""
        for field in record.xpath("./marc21:datafield[@tag='245']", namespaces=ns):

            # Get main title (subfield a)
            code_a = []
            for i in field.xpath("./marc21:subfield[@code='a']", namespaces=ns):
                code_a.append(self._strip_isbd(i.text))

            # Get part numbers (subfield n)
            code_n = []
            code_n_text = []
            for i in field.xpath("./marc21:subfield[@code='n']", namespaces=ns):
                code_n_text.append(self._strip_isbd(i.text))
                match = re.search(r"(\d+([,\.]\d+)?)", i.text.strip())
                if match:
                    code_n.append(match.group(1))

            # Get part names (subfield p)
            code_p = []
            for i in field.xpath("./marc21:subfield[@code='p']", namespaces=ns):
                code_p.append(self._strip_isbd(i.text))

            title_parts = code_a

            # Handle series extraction. As in DNB, $a is a series when $p names the part, eg
            # 'Saga o wiedźminie. $n T. 1, $p Krew elfów'. Without $p, $n is a part of a
            # multi-volume edition, eg 'Ostatnie życzenie. $n Cz. 1', so it belongs to the title
            if code_a and code_n_text and not code_p:
                title_parts = ['. '.join(code_a + code_n_text)]
            elif code_a and code_n:
                title_parts = [code_p[-1]]

                # Build series name
                series_parts = [code_a[0]]
                for i in range(min(len(code_p), len(code_n)) - 1):
                    series_parts.append(code_p[i])

                for i in range(min(len(series_parts), len(code_n) - 1)):
                    series_parts[i] += ' ' + code_n[i]

                book['series'] = ' - '.join(series_parts)
                book['series'] = self._clean_series(book['series'], book['publisher_name'])

                if code_n:
                    book['series_index'] = code_n[-1]

            # Add subtitle (subfield b)
            try:
                subtitle = self._strip_isbd(field.xpath("./marc21:subfield[@code='b']", namespaces=ns)[0].text)
                title_parts.append(subtitle)
            except (IndexError, AttributeError):
                pass

            book['title'] = " : ".join(title_parts)

    def _extract_series(self, record, book, ns):
        """Extract series from MARC21 fields 490 (series statement), 800 (author/title series)
           and 830 (uniform title series). 490 is the name printed in the book, eg 'Dziedzictwo',
           where 800 often has the original name, eg 'Inheritance'. A 490 naming the author,
           eg 'Świat Dysku / Terry Pratchett', is the author's series, without it usually
           a publisher's series like 'Nowa Fantastyka'"""
        candidates = []
        for tag, code in [('490', 'a'), ('800', 't'), ('830', 'a')]:
            for field in record.xpath(f"./marc21:datafield[@tag='{tag}']", namespaces=ns):
                try:
                    series = field.xpath(f"./marc21:subfield[@code='{code}']", namespaces=ns)[0].text
                except (IndexError, AttributeError):
                    continue
                if not series or (tag == '490' and ' / ' not in series):
                    continue
                # strip the statement of responsibility, eg 'Saga o wiedźminie / Sapkowski A.'
                series = self._strip_isbd(series.split(' / ')[0])
                series = self._clean_series(series, book['publisher_name'])
                if not series:
                    continue
                series_index = None
                with contextlib.suppress(IndexError, AttributeError):
                    volume = field.xpath("./marc21:subfield[@code='v']", namespaces=ns)[0].text
                    match = re.search(r"(\d+([,\.]\d+)?)", volume)
                    if match:
                        series_index = match.group(1).replace(',', '.')
                candidates.append((tag, series, series_index))
        if not candidates:
            return

        tag, series, series_index = candidates[0]
        # Some editions print the series differently, eg 'Dziedzictwa księga druga' with no
        # volume number, prefer the catalogue's numbered series then
        if tag == '490' and series_index is None:
            for other_tag, other_series, other_index in candidates[1:]:
                if other_tag != '490' and other_index is not None:
                    series, series_index = other_series, other_index
                    break
        book['series'] = series
        book['series_index'] = series_index

    def _extract_authors(self, record, book, ns):
        """Extract authors from MARC21 fields 100/700"""
        # BN gives the role in relator term $e (eg 'Autor', 'Tekst', 'Ilustracje') or a code in $4.
        # Field 100 is the main entry, but can be an illustrator while the writer is in a 700
        writers, others, unspecified = [], [], []
        for field in record.xpath("./marc21:datafield[@tag='100' or @tag='700']", namespaces=ns):
            relators = [self._strip_isbd(i.text).lower() for i in field.xpath(
                "./marc21:subfield[@code='e' or @code='4']", namespaces=ns) if i.text]
            names = [self._strip_isbd(i.text) for i in field.xpath(
                "./marc21:subfield[@code='a']", namespaces=ns) if i.text]
            if any(relator in self.AUTHOR_RELATORS for relator in relators):
                writers.extend(names)
            elif field.get('tag') == '100':
                others.extend(names)
            elif not relators:
                unspecified.extend(names)

        # Fall back to a main entry with another role, then to people with no role given,
        # never to translators or editors
        book['authors'] = self._uniq(writers or others or unspecified)

    def _extract_publisher_info(self, record, book, ns):
        """Extract publisher information from MARC21 field 264 (RDA) or 260 (older records)"""
        for field in record.xpath("./marc21:datafield[@tag='264' and @ind2='1'] | "
                                  "./marc21:datafield[@tag='260']", namespaces=ns):
            # Publisher location (subfield a)
            if not book['publisher_location']:
                location_parts = []
                for i in field.xpath("./marc21:subfield[@code='a']", namespaces=ns):
                    location_parts.append(self._strip_isbd(i.text))
                if location_parts:
                    book['publisher_location'] = ' '.join(location_parts).strip('[]')

            # Publisher name (subfield b)
            if not book['publisher_name']:
                with contextlib.suppress(IndexError, AttributeError):
                    name = field.xpath("./marc21:subfield[@code='b']", namespaces=ns)[0].text
                    book['publisher_name'] = self._strip_isbd(name).strip('"[]')

            # Publication date (subfield c)
            if not book['pubdate']:
                try:
                    pubdate = field.xpath("./marc21:subfield[@code='c']", namespaces=ns)[0].text.strip()
                    match = re.search(r"(\d{4})", pubdate)
                    if match:
                        year = match.group(1)
                        book['pubdate'] = datetime.datetime(int(year), 1, 1, 12, 30, 0)
                except (IndexError, AttributeError):
                    pass

    @staticmethod
    def _extract_isbn(record, book, ns):
        """Extract ISBN from MARC21 field 020"""
        for i in record.xpath("./marc21:datafield[@tag='020']/marc21:subfield[@code='a']", namespaces=ns):
            try:
                isbn_regex = (r"(?:ISBN(?:-1[03])?:? )?(?=[-0-9 ]{17}|[-0-9X ]{13}|"
                              r"[0-9X]{10})(?:97[89][- ]?)?[0-9]{1,5}[- ]?(?:[0-9]+[- ]?){2}[0-9X]")
                match = re.search(isbn_regex, i.text.strip())
                if match:
                    isbn = re.sub(r'[- ]', '', match.group())
                    if not book['isbn']:
                        book['isbn'] = isbn
                    # a record can list several isbns, eg for different bindings
                    book['isbns'].append(isbn)
            except AttributeError:
                pass

    def _extract_subjects(self, record, book, ns):
        """Extract subjects from MARC21 fields 600-655, BN's own descriptors are marked $2 DBN"""
        for f in range(600, 656):
            if f == 648:  # chronological terms, eg '1901-2000', are no use as genres
                continue
            for field in record.xpath(f"./marc21:datafield[@tag='{f}']", namespaces=ns):
                try:
                    subject = self._strip_isbd(field.xpath("./marc21:subfield[@code='a']",
                                                           namespaces=ns)[0].text)
                except (IndexError, AttributeError):
                    continue
                if not subject or subject.startswith("(") or len(subject) < 2:
                    continue
                vocab = [i.text for i in field.xpath("./marc21:subfield[@code='2']", namespaces=ns)]
                if 'DBN' in vocab:
                    book['subjects_dbn'].append(subject)
                else:
                    book['subjects_non_dbn'].extend(re.split(',|;', subject))

    def _extract_languages(self, record, book, ns):
        """Extract languages from MARC21 field 041, or field 008 if there is no 041"""
        lang_codes = [i.text.strip() for i in record.xpath(
            "./marc21:datafield[@tag='041']/marc21:subfield[@code='a']", namespaces=ns) if i.text]
        if not lang_codes:
            # 008 positions 35-37 hold the language code
            fixed = self._controlfield(record, '008')
            if len(fixed) >= 38 and fixed[35:38].strip(' |'):
                lang_codes = [fixed[35:38]]

        raw_languages = []
        for lang_code in lang_codes:
            # Convert ISO code to English language name
            isodata = None
            with contextlib.suppress(Exception):
                if Lang:
                    isodata = Lang(lang_code)
                elif iso_langs:
                    isodata = iso_langs.get(part2b=lang_code)

            if isodata and isodata.name:
                language_name = isodata.name
            else:
                language_name = lang_code if lang_code else "Unknown"

            if language_name and language_name != "Unknown":
                raw_languages.append(language_name)
            else:
                self.logger.warning(f"Unknown language code from BN: {lang_code}")

        book['languages'] = raw_languages

    @staticmethod
    def _extract_comments(record, book, ns):
        """Extract summary from MARC21 field 520"""
        summary = [i.text.strip() for i in record.xpath(
            "./marc21:datafield[@tag='520']/marc21:subfield[@code='a']", namespaces=ns) if i.text]
        if summary:
            book['comments'] = '<br>'.join(summary)

    def _extract_edition(self, record, book, ns):
        """Extract edition from MARC21 field 250"""
        with contextlib.suppress(IndexError, AttributeError):
            book['edition'] = self._strip_isbd(record.xpath(
                "./marc21:datafield[@tag='250']/marc21:subfield[@code='a']", namespaces=ns)[0].text)

    def _create_meta_record(self, book_data, generic_cover):
        """Create MetaRecord from parsed book data"""
        if not book_data.get('title') or not book_data.get('authors'):
            return None

        # Apply edition to title if configured
        title = book_data['title']
        if self.cfg_append_edition_to_title and book_data.get('edition'):
            title = f"{title} : {book_data['edition']}"

        # Clean author names, BN gives 'Surname, Forename'
        authors = [re.sub(r"^(.+), (.+)$", r"\2 \1", author) for author in book_data['authors']]

        # BN has no cover service, covers are found later using the isbn
        cover_url = generic_cover

        # Build publisher string
        publisher_parts = []
        if book_data.get('publisher_location'):
            publisher_parts.append(book_data['publisher_location'])
        if book_data.get('publisher_name'):
            publisher_parts.append(book_data['publisher_name'])
        publisher = " ; ".join(publisher_parts) if publisher_parts else ""

        # Select subjects based on configuration
        tags = []
        if self.cfg_fetch_subjects == 0:  # Only DBN
            tags = self._uniq(book_data['subjects_dbn'])
        elif self.cfg_fetch_subjects == 1:  # DBN if available, else non-DBN
            tags = self._uniq(book_data['subjects_dbn']) if book_data['subjects_dbn'] else (
                self._uniq(book_data['subjects_non_dbn']))
        elif self.cfg_fetch_subjects == 2:  # Both DBN and non-DBN
            tags = self._uniq(book_data['subjects_dbn'] + book_data['subjects_non_dbn'])
        elif self.cfg_fetch_subjects == 3:  # Non-DBN if available, else DBN
            tags = self._uniq(book_data['subjects_non_dbn']) if book_data['subjects_non_dbn'] else (
                self._uniq(book_data['subjects_dbn']))
        elif self.cfg_fetch_subjects == 4:  # Only non-DBN
            tags = self._uniq(book_data['subjects_non_dbn'])
        # cfg_fetch_subjects == 5: No subjects

        # Build identifiers
        identifiers = {}
        if book_data.get('bnid'):
            identifiers['bn-id'] = book_data['bnid']
        if book_data.get('isbn'):
            identifiers['isbn'] = book_data['isbn']
            identifiers['isbns'] = book_data.get('isbns', [])

        try:
            seriesindex = float(book_data.get('series_index', 0)) if book_data.get('series_index') else 0
        except Exception:
            seriesindex = 0

        return {
            "id": book_data.get('bnid', ''),
            "title": title,
            "authors": authors,
            "url": self.BOOKURL % book_data.get('bnid', ''),
            "source": {
                "id": self.__bnid__,
                "description": self.__bnname__,
                "link": "https://katalogi.bn.org.pl/",
            },
            "cover": cover_url,
            "description": book_data.get('comments') or '',
            "series": book_data.get('series') or '',
            "series_index": seriesindex,
            "identifiers": identifiers,
            "publisher": publisher,
            "publishedDate": book_data['pubdate'].strftime('%Y-%m-%d') if book_data.get('pubdate') else '',
            "languages": book_data.get('languages', []),
            "tags": tags,
        }

    def _clean_series(self, series, publisher_name):
        """Clean up series"""
        if not series:
            return None

        # Series must contain at least one character
        if not re.search(r'\S', series):
            return None

        # Skip series starting with publisher name if configured
        if self.cfg_skip_series_starting_with_publishers_name and publisher_name:
            if publisher_name.lower() == series.lower():
                return None

            match = re.search(r'^(\w\w\w\w+)', publisher_name)
            if match:
                pubcompany = match.group(1)
                if re.search(r'^\W*' + pubcompany, series, flags=re.IGNORECASE):
                    return None

        # Check against unwanted series patterns
        for pattern in self.cfg_unwanted_series_names:
            try:
                if re.search(pattern, series, flags=re.IGNORECASE):
                    return None
            except Exception:
                pass

        return series

    @staticmethod
    def _strip_polish_joiners(wordlist):
        """Remove Polish joiners from list of words"""
        tokens = []
        for word in wordlist:
            if word.lower() not in ('i', 'oraz', 'a', 'albo', 'lub', 'czyli', 'w', 'we', 'z', 'ze', 'o', 'na',
                                    'do', 'od'):
                tokens.append(word)
        return tokens

    def _guess_series_from_title(self, book):
        """Try to extract Series and Series Index from a book's title"""
        if not book.get('title'):
            return

        title = book['title']
        parts = title.split(' (')
        if len(parts) == 2:
            indexpart = parts[1]
            textpart = parts[0]

            # Clean textpart
            match = re.match(r"^[\s\-–—:]*(.+?)[\s\-–—:]*$", textpart)
            if match:
                textpart = match.group(1)

            # Extract series and index
            try:
                series, series_index = indexpart.split(')', 1)[0].rsplit(' ', 1)
                series = self._clean_series(series, book.get('publisher_name'))
                if series and series_index and series_index[-1].isdigit():
                    book['series'] = series
                    book['series_index'] = series_index
                    book['title'] = textpart
            except (IndexError, ValueError):
                pass

    @staticmethod
    def _uniq(list_with_duplicates):
        """Remove duplicates from a list while preserving order"""
        unique_list = []
        for item in list_with_duplicates:
            if item not in unique_list:
                unique_list.append(item)
        return unique_list

    def get_author_books(self, authorid=None, authorname=None, bookstatus="Skipped",
                         audiostatus="Skipped", entrystatus='Active', refresh=False, reason='bn.get_author_books'):
        if not CONFIG['BN_API']:
            self.logger.warning('BN API not enabled, check config')
            return
        if not etree or (not Lang and not iso_langs):
            self.logger.warning('Required modules missing, lxml and/or iso639')
            return

        db = database.DBConnection()
        auth_id = authorid
        entryreason = reason
        auth_name = authorname
        try:
            if authorid:
                res = db.match('SELECT AuthorName from authors WHERE Authorid=?', (authorid, ))
                if res:
                    auth_name = res['AuthorName']
            else:
                auth_name, auth_id = lazylibrarian.importer.get_preferred_author(authorname)

            self.logger.debug(f'[{auth_id}:{auth_name}] Now processing books with BN API')
            # Artist is loading
            db.action("UPDATE authors SET Status='Loading' WHERE AuthorID=?", (auth_id,))

            results = self._author_results(auth_name)
            if not results and len(auth_name.split()) > 1:
                # BN needs exact diacritics, a name stored as eg 'Stanislaw Lem' finds nothing
                results = self._author_results(auth_name, auth_name.split()[-1])
            if not results:
                self.logger.warning(f"No results from BN for {auth_name}")
                return

            # results only hold this author's books, but find_results looks up the authorid by exact
            # name, which misses eg BN's 'Łukasz Orbitowski' stored as 'Lukasz Orbitowski'
            for item in results:
                item['authorid'] = auth_id
                item['authorname'] = auth_name

            resultqueue = Queue()
            resultqueue.put(results)
            _ = add_author_books_to_db(resultqueue, bookstatus, audiostatus, entrystatus, entryreason,
                                       auth_id, None, self.get_bookdict_for_bookid, cache_hits=0)

        except Exception:
            self.logger.error(f'Unhandled exception in bn_get_author_books: {traceback.format_exc()}')
        finally:
            db.action("UPDATE authors SET Status=? WHERE AuthorID=?", (entrystatus, auth_id,))
            db.close()

    def _author_results(self, auth_name, query_name=None):
        """ Search BN for an author, keep only books they wrote. BN also returns books where
            they wrote the afterword, created the characters, edited or translated """
        resultqueue = Queue()
        self.find_results(f"<ll>{query_name or auth_name}", resultqueue)
        results = resultqueue.get()
        wanted = self._comparable_name(auth_name)
        return [item for item in results if fuzz.token_sort_ratio(
            self._comparable_name(item['authorname']), wanted, processor=default_process) >= 90]

    @staticmethod
    def _comparable_name(name):
        """ Name without diacritics. unaccented() drops 'ł' as it has no separate accent
            to strip, which turns 'Łukasz Orbitowski' into 'ukasz Orbitowski' """
        return unaccented(name.translate({0x141: 'L', 0x142: 'l'}))

    def _bn_language(self):
        """ Return the BN language filter for IMP_PREFLANG, or empty string if the
            preferred languages are not exactly one language BN can filter on """
        languages = set()
        for pref in get_list(CONFIG['IMP_PREFLANG']):
            pref = pref.lower()
            if pref == 'all':
                return ''
            for language, names in self.BN_LANGUAGES.items():
                if pref in names:
                    languages.add(language)
                    break
            else:
                return ''  # eg 'Unknown', or a language we can't name for BN
        return languages.pop() if len(languages) == 1 else ''

    @staticmethod
    def _isbn_forms(isbn):
        """ Return the isbn and its isbn-10 or isbn-13 equivalent if there is one """
        forms = [isbn]
        if len(isbn) == 13 and isbn.startswith('978'):
            total = sum((10 - i) * int(digit) for i, digit in enumerate(isbn[3:12]))
            check = (11 - total % 11) % 11
            forms.append(isbn[3:12] + ('X' if check == 10 else str(check)))
        elif len(isbn) == 10:
            core = '978' + isbn[:9]
            total = sum(int(digit) * (3 if i % 2 else 1) for i, digit in enumerate(core))
            forms.append(core + str((10 - total % 10) % 10))
        return forms

    def get_bookdict_for_bookid(self, bookid=None):
        results, in_cache, _ = self._search(f"bn-id:{bookid}", start=0, limit=5)
        # shouldn't need many results as based on bookid
        bookdict = None
        for bk in results:
            bookdict = self._book_dict(bk)
            if bookdict and bookdict['bookid'] == bookid:
                break
        return bookdict, in_cache

    def add_bookid_to_db(self, bookid=None, bookstatus=None, audiostatus=None, reason='bn.add_bookid_to_db'):
        # Find details on a book from provider using bookid
        # Ensure author in database, add book to database using provided or default statuses and reason
        if not CONFIG['BN_API']:
            self.logger.warning('BN API not enabled, check config')
            return False
        if not etree or (not Lang and not iso_langs):
            self.logger.warning('Required modules missing, lxml and/or iso639')
            return False
        if not bookstatus:
            bookstatus = CONFIG['NEWBOOK_STATUS']
        if not audiostatus:
            audiostatus = CONFIG['NEWAUDIO_STATUS']

        bookdict, _ = self.get_bookdict_for_bookid(bookid)
        if not bookdict or bookdict['bookid'] != bookid:
            self.logger.debug(f'BookID {bookid} not found at BN')
            return False

        authorname = bookdict.get('authorname')
        if authorname:
            auth_name, auth_id = lazylibrarian.importer.get_preferred_author(authorname)
            db = database.DBConnection()
            res = db.match('SELECT authorid from authors WHERE authorname=?', (auth_name,))
            if res:
                bookdict['authorid'] = res['authorid']
            else:
                authorname, authorid, _ = lazylibrarian.importer.add_author_name_to_db(author=auth_name,
                                                                                       refresh=False,
                                                                                       addbooks=False,
                                                                                       reason=f"BN add {bookid}:{bookdict['bookname']}",
                                                                                       title=bookdict['bookname'])
                if authorname:
                    bookdict['authorname'] = authorname
                    bookdict['authorid'] = authorid
            db.close()
        # validate bookdict, reject if unwanted or incomplete
        bookdict, rejected = validate_bookdict(bookdict)
        if rejected:
            if reason.startswith("Series:") or 'bookname' not in bookdict or 'authorname' not in bookdict:
                self.logger.error(f"Rejected {bookid}:{rejected}")
                return False
            for reject in rejected:
                if reject[0] == 'name':
                    self.logger.error(f"Rejected {bookid}:{rejected}")
                    return False
        # show any non-fatal warnings
        warn_about_bookdict(bookdict)
        # Use the author ID we already have from the book data
        # This avoids an author search that can return the wrong author
        authorid = bookdict.get('authorid')

        if authorid:
            # Add book to database using bookdict
            bookdict['status'] = bookstatus
            bookdict['audiostatus'] = audiostatus
            bookdict['reason'] = f"[{thread_name()}] {reason}"
            res = add_bookdict_to_db(bookdict)
            lazylibrarian.importer.update_totals(authorid)
            return res
        return False

    def find_results(self, searchterm=None, queue=None):
        # callers wait on the queue, so always put a result list on it
        if not CONFIG['BN_API']:
            self.logger.warning('BN API not enabled, check config')
            queue.put([])
            return False
        if not etree or (not Lang and not iso_langs):
            self.logger.warning('Required modules missing, lxml and/or iso639')
            queue.put([])
            return False
        try:
            resultlist = []
            resultcount = 0
            ignored = 0
            no_author_count = 0
            title = ''
            authorname = ''

            searchisbns = []
            if is_valid_isbn(searchterm):
                # BN stores isbns without hyphens or spaces
                searchisbn = re.sub(r'[^0-9X]', '', searchterm.upper())
                searchisbns = self._isbn_forms(searchisbn)
                searchterm = f'isbn: {searchisbn}'

            if '<ll>' in searchterm:  # special token separates title from author
                title, authorname = searchterm.split('<ll>')

            # strip all ascii and non-ascii quotes/apostrophes
            searchterm = strip_quotes(searchterm)

            fullterm = searchterm.replace('<ll>', ' ')
            self.logger.debug(f'Now searching BN with searchterm: {fullterm}')
            # max limit = 100 per search, the api pages using the id to start from
            start = 0
            limit = 100
            pages = 0
            next_page = True
            while next_page:
                results, in_cache, start = self._search(searchterm, start=start, limit=limit)
                pages += 1
                self.logger.debug(f"Search page {pages} returned {len(results)}")
                for item in results:
                    book = self._book_dict(item)
                    if not book['authorname']:
                        self.logger.debug('Skipped a result without authorfield.')
                        no_author_count += 1
                        continue
                    if not book['bookname']:
                        self.logger.debug('Skipped a result without title.')
                        continue

                    valid_langs = get_list(CONFIG['IMP_PREFLANG'])
                    if "All" not in valid_langs:  # don't care about languages, accept all
                        try:
                            # skip if no language in valid list -
                            booklangs = get_list(book['booklang'])
                            if not booklangs:
                                booklangs = ['Unknown']
                            valid = False
                            for lang in booklangs:
                                if lang in valid_langs:
                                    valid = True
                                    break
                            if not valid:
                                self.logger.debug(f"Skipped {book['bookname']} with language {booklangs}")
                                ignored += 1
                                continue
                        except KeyError:
                            ignored += 1
                            self.logger.debug(f"Skipped {book['bookname']} where no language is found")
                            continue

                    if authorname:
                        author_fuzz = fuzz.token_sort_ratio(book['authorname'], authorname, processor=default_process)
                    else:
                        author_fuzz = fuzz.token_sort_ratio(book['authorname'], fullterm, processor=default_process)

                    if title:
                        if title.endswith(')'):
                            title = title.rsplit('(', 1)[0]
                        book_fuzz = fuzz.token_set_ratio(book['bookname'].lower(), title, processor=default_process)
                        # lose a point for each extra word in the fuzzy matches so we get the closest match
                        words = len(get_list(book['bookname']))
                        words -= len(get_list(title))
                        book_fuzz -= abs(words)
                    else:
                        book_fuzz = fuzz.token_set_ratio(book['bookname'].lower(), fullterm, processor=default_process)
                    isbn_fuzz = 0
                    # BN also returns other editions linked to the isbn, only score the exact match
                    if searchisbns:
                        book_isbns = book['identifiers'].get('isbns', []) if book['identifiers'] else []
                        if set(searchisbns) & set(book_isbns + [book['bookisbn']]):
                            isbn_fuzz = 100
                    highest_fuzz = max((author_fuzz + book_fuzz) / 2, isbn_fuzz)

                    dic = {':': '.', '"': '', '\'': ''}
                    bookname = replace_all(book['bookname'], dic)

                    bookname = unaccented(bookname, only_ascii=False)

                    author_id = ''
                    if book['authorname']:
                        db = database.DBConnection()
                        match = db.match('SELECT AuthorID FROM authors WHERE AuthorName=?', (book['authorname'],))
                        if match:
                            author_id = match['AuthorID']
                        db.close()

                    resultlist.append({
                        'authorname': book['authorname'],
                        'authorid': author_id,
                        'bookid': book['bookid'],
                        'bookname': bookname,
                        'booksub': book['booksub'],
                        'bookisbn': book['bookisbn'],
                        'bookpub': book['bookpub'],
                        'bookdate': book['bookdate'],
                        'booklang': book['booklang'],
                        'booklink': book['booklink'],
                        'bookrate': float(book['bookrate']),
                        'bookrate_count': book['bookrate_count'],
                        'bookimg': book['bookimg'],
                        'bookpages': book['bookpages'],
                        'bookgenre': book['bookgenre'],
                        'bookdesc': book['bookdesc'],
                        'author_fuzz': author_fuzz,
                        'book_fuzz': book_fuzz,
                        'isbn_fuzz': isbn_fuzz,
                        'highest_fuzz': highest_fuzz,
                        'contributors': book['contributors'],
                        'series': book['series'],
                        'source': 'BN'
                    })

                    resultcount += 1

                if not start:
                    next_page = False
                elif pages >= self.cfg_max_pages:
                    self.logger.debug(f"Stopping BN search after {pages} pages")
                    next_page = False

            self.logger.debug(
                f"Returning {resultcount} {plural(resultcount, 'result')} for {searchterm}")

            self.logger.debug(f"Removed {ignored} unwanted language {plural(ignored, 'result')}")
            self.logger.debug(f"Removed {no_author_count} {plural(no_author_count, 'book')} with no author")
            queue.put(resultlist)
            return resultcount > 0

        except Exception:
            self.logger.error(f'Unhandled exception in BN.find_results: {traceback.format_exc()}')
            queue.put([])
            return False

    @staticmethod
    def _book_dict(item):
        """ Return all the book info we need as a dictionary or default value if no key """
        mydict = {}
        for val, idx, default in [
            ('bookid', 'id', ''),
            ('authorname', 'authors', ''),
            ('bookname', 'title', ''),
            ('identifiers', 'identifiers', ''),
            ('booklang', 'languages', ''),
            ('bookpub', 'publisher', ''),
            ('booksub', 'subtitle', ''),
            ('bookdate', 'publishedDate', '0000'),
            ('bookrate', 'averageRating', 0),
            ('bookrate_count', 'ratingsCount', 0),
            ('bookpages', 'pageCount', 0),
            ('series_name', 'series', ''),
            ('series_index', 'series_index', ''),
            ('bookdesc', 'description', 'Not available'),
            ('booklink', 'url', ''),
            ('bookimg', 'cover', 'images/nocover.png'),
            ('bookgenre', 'tags', '')
        ]:
            try:
                mydict[val] = item[idx]
            except KeyError:
                mydict[val] = default

        # massage into a standard layout across all providers
        if mydict['bookname'] and ':' in mydict['bookname']:
            title, subtitle = mydict['bookname'].split(':', 1)
            mydict['bookname'] = title.strip()
            mydict['booksub'] = subtitle.strip()

        if isinstance(mydict['booklang'], list):
            mydict['booklang'] = ','.join(mydict['booklang'])
        if isinstance(mydict['bookgenre'], list):
            if lazylibrarian.GRGENRES:
                genre_limit = lazylibrarian.GRGENRES.get('genreLimit', 3)
            else:
                genre_limit = 3
            mydict['bookgenre'] = ','.join(mydict['bookgenre'][:genre_limit])

        mydict['contributors'] = []
        authornames = mydict['authorname']
        if len(authornames) > 1:
            for authorname in authornames[1:]:
                authorname, _ = lazylibrarian.importer.get_preferred_author(authorname)
                mydict['contributors'].append(["", " ".join(authorname.split())])
        mydict['authorname'], _ = lazylibrarian.importer.get_preferred_author(authornames[0])

        mydict['bookisbn'] = ''
        if mydict['identifiers'] and 'isbn' in mydict['identifiers']:
            mydict['bookisbn'] = mydict['identifiers']['isbn']

        mydict['series'] = []
        if mydict['series_name']:
            # no series_id from bn, so use bookid. BN only gives one series per book.
            # we can merge the series together in the database by matching series_name where series_id starts with 'BN'
            # so the series id becomes the bookid of the first book in the series added to the database.
            # BN often has no volume numbers, eg for Świat Dysku, so keep the series without one
            mydict['series'] = [(mydict['series_name'], f"BN{mydict['bookid']}", mydict['series_index'] or '')]
        mydict['source'] = 'BN'
        return mydict
