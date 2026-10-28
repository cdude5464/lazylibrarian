# Databáze knih (databazeknih.cz) metadata source
# Czech and Slovak book database. There is no public api, so this reads the web pages.
# SPDX-License-Identifier: GPL-3.0-or-later

# Pages used, ids are the number at the end of the page name, the rest is optional
# and the site redirects to the full name, eg /prehled-knihy/kniha-30482
#   https://www.databazeknih.cz/vyhledavani/knihy?q=krev+elfu&lang=cz     search for books
#   https://www.databazeknih.cz/search?q=80-85951-05-3                    isbn search, redirects to the book
#   https://www.databazeknih.cz/prehled-knihy/zaklinac-saga-krev-elfu-30482  book, with schema.org json-ld
#   https://www.databazeknih.cz/book-detail-more-info/30482               pages, original title, isbn
#   https://www.databazeknih.cz/search?in=authors&q=sapkowski             search for authors
#   https://www.databazeknih.cz/autori/andrzej-sapkowski-269              author, with schema.org json-ld
#   https://www.databazeknih.cz/vydane-knihy/andrzej-sapkowski-269?lang=sk  an author's books, 20 per page,
#                                                                         in Czech without lang
#   https://www.databazeknih.cz/serie/zaklinac-saga---7063                books in a series
# Each edition of a book has its own id. The author and series pages list one edition of each book.
# Czech and Slovak translations are separate books, with the same original title
# Author ids are plain numbers like GoodReads and HardCover ones, so LazyLibrarian stores them
# as DBK<number> to keep them apart in the lookups that match an id against every source column

import contextlib
import json
import logging
import re
import time
import traceback
from queue import Queue
from urllib.parse import urlencode

try:
    from iso639 import Lang
except (ImportError, ModuleNotFoundError):
    Lang = None

from bs4 import BeautifulSoup, Tag
from rapidfuzz import fuzz
from rapidfuzz.utils import default_process

import lazylibrarian
from lazylibrarian import database
from lazylibrarian.bookdict import (
    add_author_books_to_db,
    add_bookdict_to_db,
    validate_bookdict,
    warn_about_bookdict,
)
from lazylibrarian.cache import html_request
from lazylibrarian.config2 import CONFIG
from lazylibrarian.formatter import (
    format_author_name,
    get_list,
    is_valid_isbn,
    plural,
    replace_all,
    strip_quotes,
    thread_name,
    unaccented,
)


class DBK:
    def __init__(self):
        return

    __dbkname__ = "Databáze knih"
    __dbkid__ = "dbk"

    logger = logging.getLogger(__name__)
    active = True

    BASEURL = 'https://www.databazeknih.cz'
    BOOKURL = BASEURL + '/prehled-knihy/kniha-%s'
    MOREURL = BASEURL + '/book-detail-more-info/%s'
    SEARCHURL = BASEURL + '/vyhledavani/knihy?%s'
    ISBNURL = BASEURL + '/search?%s'
    AUTHORSEARCHURL = BASEURL + '/search?%s'
    AUTHORURL = BASEURL + '/autori/autor-%s'
    AUTHORBOOKSURL = BASEURL + '/vydane-knihy/autor-%s'
    SERIESURL = BASEURL + '/serie/serie-%s'

    # Search results pages hold 20 books, stop after this many pages
    cfg_max_search_pages = 3
    # An author's books, 20 per page
    cfg_max_author_pages = 25
    # Seconds between requests that are not in the cache, the site has no published limit
    cfg_request_delay = 1.0
    last_request = 0.0

    # Search 'lang' filter values, keyed by what IMP_PREFLANG may hold for that language
    DBK_LANGUAGES = {
        'cz': ['cs', 'cz', 'cze', 'ces', 'czech', 'čeština', 'cestina'],
        'sk': ['sk', 'slo', 'slk', 'slovak', 'slovenčina', 'slovencina'],
        'en': ['en', 'eng', 'en-us', 'en-gb', 'english'],
        'de': ['de', 'ger', 'deu', 'german'],
    }
    # Book language names as shown in 'Jazyk vydání', used when the json-ld has no inLanguage
    LANGUAGE_NAMES = {
        'český': 'Czech', 'slovenský': 'Slovak', 'anglický': 'English', 'německý': 'German',
        'polský': 'Polish', 'ruský': 'Russian', 'francouzský': 'French', 'španělský': 'Spanish',
        'italský': 'Italian', 'maďarský': 'Hungarian', 'ukrajinský': 'Ukrainian',
    }

    # ---------------------------------------------------------------- fetching

    def _fetch(self, url: str) -> tuple[str, bool]:
        """ Return the page at url as text and whether it came from cache, or empty string """
        if not self.active:
            return '', False
        # html_request does not say in advance if it will use the cache, so keep the delay
        # from the previous uncached request instead
        wait = self.cfg_request_delay - (time.time() - DBK.last_request)
        result, in_cache = html_request(url)
        if not in_cache:
            if wait > 0:
                time.sleep(wait)
            DBK.last_request = time.time()
        if not result:
            self.logger.debug(f'Databazeknih no result for {url}')
            return '', False
        if isinstance(result, bytes):
            result = result.decode('utf-8', errors='replace')
        return result, in_cache

    @staticmethod
    def _id_from_link(link: str) -> str:
        """ Return the number at the end of a page link like /prehled-knihy/krev-elfu-433?lang=cz """
        match = re.search(r'-(\d+)(?:[?#].*)?$', link or '')
        return match.group(1) if match else ''

    # ---------------------------------------------------------------- parsing

    @staticmethod
    def _json_ld(soup, wanted_type: str) -> dict:
        """ Return the schema.org json-ld block of the wanted type, eg Book or Person """
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string or '')
            except ValueError:
                continue
            for item in data if isinstance(data, list) else [data]:
                if isinstance(item, dict) and item.get('@type') == wanted_type:
                    return item
        return {}

    @staticmethod
    def _names(value) -> list:
        """ json-ld author and publisher can be an object, a list of objects or text """
        if not value:
            return []
        if not isinstance(value, list):
            value = [value]
        names = []
        for item in value:
            name = item.get('name', '') if isinstance(item, dict) else str(item)
            name = ' '.join(name.split())
            if name and name not in names:
                names.append(name)
        return names

    @staticmethod
    def _clean_author(name: str) -> str:
        """ The site marks pseudonyms with (p), eg 'Jason Dark (p)' """
        return ' '.join(re.sub(r'\s*\(p\)\s*$', '', name or '').split())

    @staticmethod
    def _language_name(code: str) -> str:
        if not code:
            return ''
        with contextlib.suppress(Exception):
            if Lang:
                return Lang(code).name
        return code

    def _parse_book(self, page: str, more: str = '') -> dict:
        """ Return a book dict in the standard layout from a book page and its more-info fragment """
        soup = BeautifulSoup(page, 'html.parser')
        data = self._json_ld(soup, 'Book')
        if not data:
            return {}

        bookid = self._id_from_link(data.get('url', ''))
        if not bookid:
            # pages without json-ld url still carry the id on the rating buttons
            tag = soup.find(attrs={'data-typeid': True})
            bookid = tag['data-typeid'] if tag else ''
        if not bookid:
            return {}

        authors = [self._clean_author(name) for name in self._names(data.get('author'))]
        bookname = ' '.join(str(data.get('name', '')).split())
        if not authors or not bookname:
            return {}

        # The page has the whole description, the json-ld one is cut short
        desc = ''
        left = soup.find(id='left')
        if left:
            para = left.find('p', class_='new2')
            if para:
                desc = para.get_text().strip()
        if not desc:
            desc = str(data.get('description', '')).strip()

        # Edition year and publisher are in the text under the rating, eg '1998 , Leonardo'
        bookdate = ''
        info = soup.find('div', class_='lineHeightMid')
        if info:
            match = re.search(r'\b(1\d{3}|20\d{2})\b', info.get_text(' '))
            if match:
                bookdate = match.group(1)

        rating = data.get('aggregateRating') or {}
        try:
            bookrate = round(float(rating.get('ratingValue', 0)), 2)
        except (TypeError, ValueError):
            bookrate = 0
        try:
            bookrate_count = int(rating.get('ratingCount', 0))
        except (TypeError, ValueError):
            bookrate_count = 0

        genres = data.get('genre') or []
        if isinstance(genres, str):
            genres = [genres]
        if lazylibrarian.GRGENRES:
            genre_limit = lazylibrarian.GRGENRES.get('genreLimit', 3)
        else:
            genre_limit = 3

        bookisbn = re.sub(r'[^0-9X]', '', str(data.get('isbn', '')).upper())
        booklang = self._language_name(data.get('inLanguage', ''))
        bookpages = 0

        if more:
            details = self._parse_more_info(more)
            # LazyLibrarian wants the first publication date, not this edition's
            if details.get('original_year'):
                bookdate = details['original_year']
            bookpages = details.get('pages', 0)
            if not bookisbn and details.get('isbn'):
                bookisbn = details['isbn']
            if not booklang and details.get('language'):
                booklang = details['language']

        bookimg = str(data.get('image', ''))
        if not bookimg or 'nobook' in bookimg or 'noimage' in bookimg:
            bookimg = 'images/nocover.png'

        bookdict = {
            'authorname': '',
            'authorid': '',
            'bookid': bookid,
            'bookname': bookname,
            'booksub': '',
            'bookisbn': bookisbn,
            'bookpub': ', '.join(self._names(data.get('publisher'))),
            'bookdate': bookdate or '0000',
            'booklang': booklang,
            'booklink': self.BOOKURL % bookid,
            'bookrate': bookrate,
            'bookrate_count': bookrate_count,
            'bookimg': bookimg,
            'bookpages': bookpages,
            'bookgenre': ','.join(' '.join(str(g).split()) for g in genres[:genre_limit]),
            'bookdesc': desc or 'Not available',
            'contributors': [],
            'series': self._parse_series(soup),
            'source': 'DBK',
        }
        if data.get('url'):
            bookdict['booklink'] = data['url']

        # massage into a standard layout across all providers
        if ':' in bookdict['bookname']:
            title, subtitle = bookdict['bookname'].split(':', 1)
            if title.strip() and subtitle.strip():
                bookdict['bookname'] = title.strip()
                bookdict['booksub'] = subtitle.strip()

        bookdict['authorname'], _ = lazylibrarian.importer.get_preferred_author(authors[0])
        for authorname in authors[1:]:
            authorname, _ = lazylibrarian.importer.get_preferred_author(authorname)
            bookdict['contributors'].append(["", authorname])
        return bookdict

    def _parse_series(self, soup) -> list:
        """ Return [(series name, series id, position)] from the series box of a book page.
            A book can be in several series, eg 'Zaklínač: sága' 1. díl and 'Zaklínač' 3. díl """
        series = []
        box = soup.find('div', class_='book_detail_serie_info')
        if not box:
            return series
        for link in box.find_all('a', href=re.compile(r'^/serie/')):
            series_id = self._id_from_link(link['href'])
            name = ' '.join((link.get('title') or link.get_text()).split())
            if not series_id or not name:
                continue
            # the part number follows the link, up to the next series link
            text = []
            for elem in link.parent.next_siblings:
                if isinstance(elem, Tag):
                    if elem.find('a', href=re.compile(r'^/serie/')):
                        break
                    text.append(elem.get_text(' '))
                else:
                    text.append(str(elem))
            match = re.search(r'(\d+(?:[.,]\d+)?)\.\s*díl', ' '.join(text))
            position = match.group(1).replace(',', '.') if match else ''
            series.append((name, f"DBK{series_id}", position))
        return series

    def _parse_more_info(self, more: str) -> dict:
        """ Return pages, original title and year, isbn and language from the book-detail-more-info fragment """
        soup = BeautifulSoup(more, 'html.parser')
        details = {}
        for row in soup.find_all('div', class_='book-details__row'):
            label = row.find('dt')
            value = row.find('dd')
            if not label or not value:
                continue
            label = label.get_text(' ').strip()
            text = ' '.join(value.get_text(' ').split())
            if label == 'Počet stran':
                match = re.search(r'\d+', text)
                if match:
                    details['pages'] = int(match.group())
            elif label == 'Originální název':
                # eg 'Krew elfów, 1994'
                details['original'] = text
                match = re.search(r'\b(1\d{3}|20\d{2})\s*$', text)
                if match:
                    details['original_year'] = match.group(1)
            elif label == 'ISBN':
                isbn = re.sub(r'[^0-9X]', '', text.split(',')[0].upper())
                if isbn:
                    details['isbn'] = isbn
            elif label == 'Jazyk vydání':
                name = text.split(',')[0].strip().lower()
                details['language'] = self.LANGUAGE_NAMES.get(name, '')
        return details

    def _parse_search(self, page: str) -> tuple[list, str]:
        """ Return [{bookid, bookname, authors, bookdate, bookimg, bookrate}] from a search results
            page, and the link to the next page or empty string """
        soup = BeautifulSoup(page, 'html.parser')
        results = []
        for link in soup.find_all('a', attrs={'type': 'book'}, href=re.compile(r'/prehled-knihy/')):
            bookid = self._id_from_link(link['href'])
            if not bookid:
                continue
            entry = link.find_parent('p') or link.parent
            bookdate = ''
            authors = []
            note = entry.find('span', class_='pozn') if entry else None
            if note:
                text = ' '.join(note.get_text(' ').split())
                match = re.match(r'^(\d{4})\s*,\s*(.*)$', text)
                if match:
                    bookdate = match.group(1)
                    text = match.group(2)
                authors = [self._clean_author(name) for name in text.split(',') if name.strip()]
            bookrate = 0
            square = entry.find('img', title=re.compile(r'^\d+%$')) if entry else None
            if square:
                # percent of the maximum rating, convert to a 5 star scale
                bookrate = round(int(square['title'].rstrip('%')) / 20, 2)
            bookimg = 'images/nocover.png'
            cover = entry.find('img', class_=re.compile('img_39')) if entry else None
            if cover and cover.get('src', '').startswith('http'):
                bookimg = cover['src']
            results.append({
                'bookid': bookid,
                'bookname': ' '.join(link.get_text(' ').split()),
                'authors': authors,
                'bookdate': bookdate,
                'bookimg': bookimg,
                'bookrate': bookrate,
            })
        return results, self._next_page(soup)

    @staticmethod
    def _next_page(soup) -> str:
        nxt = soup.find('a', rel='next')
        return nxt['href'] if nxt and nxt.get('href') else ''

    def _parse_book_list(self, page: str) -> tuple[list, str]:
        """ Return [(bookid, bookname, first publication year)] from an author's books page,
            and the link to the next page or empty string """
        soup = BeautifulSoup(page, 'html.parser')
        books = []
        for heading in soup.find_all('h3'):
            link = heading.find('a', href=re.compile(r'/prehled-knihy/'))
            if not link:
                continue
            bookid = self._id_from_link(link['href'])
            if not bookid:
                continue
            year = ''
            note = heading.find('span', class_='pozn')
            if note:
                text = ' '.join(note.get_text(' ').split())
                # eg '2011 (1. vydání 1994)', or '2002 (1. vydání)' when this is the first edition
                match = re.search(r'1\. vydání (\d{4})', text) or re.match(r'(\d{4})', text)
                if match:
                    year = match.group(1)
            books.append((bookid, ' '.join(link.get_text(' ').split()), year))
        return books, self._next_page(soup)

    def _parse_series_page(self, page: str) -> tuple[list, str]:
        """ Return [(position, bookid, bookname, authorname, year)] from a series page and the next page """
        soup = BeautifulSoup(page, 'html.parser')
        members = []
        for part in soup.find_all(attrs={'itemprop': 'hasPart'}):
            link = part.find('a', href=re.compile(r'/prehled-knihy/'), title=True)
            if not link:
                continue
            bookid = self._id_from_link(link['href'])
            position = ''
            pos = part.find(string=re.compile(r'\d+\.\s*v sérii'))
            if pos:
                position = re.search(r'(\d+)\.', pos).group(1)
            authorname = ''
            year = ''
            note = part.find('span', class_='pozn')
            if note:
                author = note.find('a')
                if author:
                    authorname = self._clean_author(author.get_text(' '))
                match = re.search(r'\b(\d{4})\b', note.get_text(' '))
                if match:
                    year = match.group(1)
            members.append((position, bookid, link['title'], authorname, year))
        return members, self._next_page(soup)

    # ---------------------------------------------------------------- lookups

    def _book_from_id(self, bookid: str, more: bool = True) -> tuple[dict, bool]:
        """ Return the standard bookdict for a databazeknih book id and whether it came from cache """
        page, in_cache = self._fetch(self.BOOKURL % bookid)
        if not page:
            return {}, False
        more_info = ''
        if more:
            more_info, more_cached = self._fetch(self.MOREURL % bookid)
            in_cache = in_cache and more_cached
        return self._parse_book(page, more_info), in_cache

    def _search_language(self) -> str:
        """ Return the search lang filter for IMP_PREFLANG, or empty string to use the site default """
        languages = set()
        for pref in get_list(CONFIG['IMP_PREFLANG']):
            pref = pref.lower()
            if pref == 'all':
                return ''
            for language, names in self.DBK_LANGUAGES.items():
                if pref in names:
                    languages.add(language)
                    break
        if languages == {'cz', 'sk'}:
            return 'czsk'
        return languages.pop() if len(languages) == 1 else ''

    def _search_books(self, query: str) -> list:
        """ Return search page entries for free text """
        params = {'q': query}
        language = self._search_language()
        if language:
            params['lang'] = language
        url = self.SEARCHURL % urlencode(params)
        results = []
        pages = 0
        while url and pages < self.cfg_max_search_pages:
            page, _ = self._fetch(url)
            if not page:
                break
            pages += 1
            # a search with a single match can redirect straight to the book
            book = self._parse_book(page)
            if book:
                results.append({'bookid': book['bookid'], 'bookname': book['bookname'],
                                'authors': [book['authorname']] + [c[1] for c in book['contributors']],
                                'bookdate': book['bookdate'], 'bookimg': book['bookimg'],
                                'bookrate': book['bookrate']})
                break
            entries, url = self._parse_search(page)
            results.extend(entries)
            if url and not url.startswith('http'):
                url = self.BASEURL + url
        return results

    def _find_author(self, authorname: str) -> str:
        """ Return the databazeknih id of the author with the closest name, or empty string """
        url = self.AUTHORSEARCHURL % urlencode({'in': 'authors', 'q': authorname})
        page, _ = self._fetch(url)
        if not page:
            return ''
        soup = BeautifulSoup(page, 'html.parser')
        # a search with a single match can redirect straight to the author
        person = self._json_ld(soup, 'Person')
        if person and person.get('url'):
            return self._id_from_link(person['url'])
        best_id = ''
        best_fuzz = 0
        wanted = self._comparable_name(authorname)
        for link in soup.find_all('a', href=re.compile(r'^/?autori/')):
            name = ' '.join(link.get_text(' ').split())
            if not name:
                continue
            score = fuzz.token_sort_ratio(self._comparable_name(name), wanted, processor=default_process)
            if score > best_fuzz:
                best_fuzz = score
                best_id = self._id_from_link(link['href'])
        return best_id if best_fuzz >= 90 else ''

    @staticmethod
    def author_id_from_text(text) -> str:
        """ Return the LazyLibrarian form of a databazeknih author id, DBK<number>, from a bare
            number, an id that already has the prefix or an author page link, or empty string """
        text = str(text or '').strip()
        if text.upper().startswith('DBK'):
            text = text[3:]
        if not text.isdigit():
            text = DBK._id_from_link(text.split('?')[0].rstrip('/'))
        return f"DBK{text}" if text else ''

    @staticmethod
    def _author_number(authorid) -> str:
        """ The number the site uses for an author, from DBK<number> """
        return DBK.author_id_from_text(authorid)[3:]

    def _parse_author(self, page: str) -> dict:
        """ Return the author dict in the standard layout from an author page, or empty dict """
        soup = BeautifulSoup(page, 'html.parser')
        person = self._json_ld(soup, 'Person')
        number = self._id_from_link(person.get('url', ''))
        authorname = self._clean_author(str(person.get('name', '')))
        if not number or not authorname:
            return {}
        authorimg = str(person.get('image', ''))
        if '/img/authors/' not in authorimg:
            # no photo, the site shows a placeholder
            authorimg = ''
        return {
            'authorid': f"DBK{number}",
            'authorlink': person['url'],
            'authorborn': str(person.get('birthDate', '')),
            'authordeath': str(person.get('deathDate', '')),
            'authorimg': authorimg,
            'about': ' '.join(str(person.get('description', '')).split()),
            'totalbooks': 0,
            'authorname': format_author_name(authorname, postfix=get_list(CONFIG.get_csv('NAME_POSTFIX'))),
        }

    @staticmethod
    def _comparable_name(name):
        """ Name without diacritics, unaccented() drops 'ł' as it has no separate accent """
        return unaccented(name.translate({0x141: 'L', 0x142: 'l'}))

    def _author_languages(self) -> list:
        """ Return the languages of an author's books page in IMP_PREFLANG order, eg ['sk', 'cz'],
            or an empty list for both without a preference. The page only has Czech and Slovak """
        languages = []
        for pref in get_list(CONFIG['IMP_PREFLANG']):
            pref = pref.lower()
            if pref == 'all':
                return []
            for language in ('cz', 'sk'):
                if pref in self.DBK_LANGUAGES[language] and language not in languages:
                    languages.append(language)
        return languages

    def _prefer_languages(self, books: list, languages: list, other_titles: dict | None = None) -> list:
        """ Keep one translation of each work from [(bookid, bookname, year)], in the first of the
            languages it was published in. Books without an original title, eg by Czech and
            Slovak authors, are all kept. other_titles gets {kept bookid: [titles of the
            translations left out]}, in the order of the languages """
        names = {'cz': 'Czech', 'sk': 'Slovak'}
        rank = {names[language]: position for position, language in enumerate(languages)}
        works = {}
        for book in books:
            if lazylibrarian.STOPTHREADS and thread_name() == "AUTHORUPDATE":
                break
            more, _ = self._fetch(self.MOREURL % book[0])
            details = self._parse_more_info(more) if more else {}
            key = unaccented(details.get('original', '')).lower() or f"id {book[0]}"
            works.setdefault(key, []).append((rank.get(details.get('language', ''), len(rank)), book))
        kept = []
        for translations in works.values():
            translations.sort(key=lambda item: item[0])
            book = translations[0][1]
            kept.append(book)
            titles = list(dict.fromkeys(other[1] for _, other in translations[1:] if other[1] != book[1]))
            if titles and other_titles is not None:
                other_titles[book[0]] = titles
        if len(kept) < len(books):
            self.logger.debug(f"Kept {len(kept)} of {len(books)} databazeknih books, "
                              f"one translation of each in {', '.join(languages)}")
        return kept

    def _author_books(self, dbk_author_id: str, prefer_language: bool = False,
                      other_titles: dict | None = None) -> list:
        """ Return [(bookid, bookname, year)] for all books of a databazeknih author in the
            preferred languages. With both Czech and Slovak, prefer_language keeps one
            translation of each work, in the language that comes first in IMP_PREFLANG,
            and other_titles gets the titles of the others, see _prefer_languages """
        languages = self._author_languages()
        books = []
        seen = set()
        # the czsk list has only one of a work's Czech and Slovak translations, mostly the
        # Czech one, so the preferred languages are listed one by one
        for lang in languages or ['czsk']:
            for book in self._author_book_list(dbk_author_id, lang):
                if book[0] not in seen:
                    seen.add(book[0])
                    books.append(book)
        if prefer_language and len(languages) > 1:
            books = self._prefer_languages(books, languages, other_titles)
        return books

    def _author_book_list(self, dbk_author_id: str, lang: str) -> list:
        """ Return [(bookid, bookname, year)] from an author's books pages in one site language """
        url = self.AUTHORBOOKSURL % dbk_author_id
        if lang != 'cz':
            # the short page name redirects to the full one and drops lang, the page lists
            # the Czech books and links to the others by the full name
            page, _ = self._fetch(url)
            match = re.search(rf'/vydane-knihy/([\w-]*-{re.escape(dbk_author_id)})\b', page or '')
            if match:
                url = f"{self.BASEURL}/vydane-knihy/{match.group(1)}?{urlencode({'lang': lang})}"
        books = []
        pages = 0
        while url and pages < self.cfg_max_author_pages:
            page, _ = self._fetch(url)
            if not page:
                break
            pages += 1
            entries, url = self._parse_book_list(page)
            books.extend(entries)
            if url and not url.startswith('http'):
                url = self.BASEURL + url
        if url:
            self.logger.debug(f"Stopping databazeknih author list after {pages} pages")
        return books

    # ---------------------------------------------------------------- provider interface

    def find_author_id(self, authorname=None, title=None, refresh=False):
        """ Return the author dict of the closest name match, or empty dict.
            The site's author search only matches names, so title is not used """
        if not CONFIG['DBK_API'] or not authorname:
            return {}
        number = self._find_author(authorname)
        if not number:
            self.logger.debug(f"No Databazeknih author id for {authorname}")
            return {}
        return self.get_author_info(authorid=f"DBK{number}", authorname=authorname, refresh=refresh)

    def get_author_info(self, authorid=None, authorname=None, refresh=False):
        """ Return name, link, image, dates and description of a databazeknih author, or empty dict """
        if not CONFIG['DBK_API']:
            return {}
        number = self._author_number(authorid)
        if not number:
            return self.find_author_id(authorname=authorname, refresh=refresh) if authorname else {}
        self.logger.debug(f"Getting Databazeknih author info for {authorid}:{authorname}")
        page, _ = self._fetch(self.AUTHORURL % number)
        author = self._parse_author(page) if page else {}
        if not author:
            self.logger.debug(f"Unable to read Databazeknih author {authorid}")
        return author

    def get_author_image(self, authorid=None, authorname=None, refresh=False):
        return self.get_author_info(authorid=authorid, authorname=authorname, refresh=refresh).get('authorimg', '')

    def get_author_books(self, authorid=None, authorname=None, bookstatus="Skipped",
                         audiostatus="Skipped", entrystatus='Active', refresh=False, reason='dbk.get_author_books'):
        if not CONFIG['DBK_API']:
            self.logger.warning('Databazeknih not enabled, check config')
            return

        db = database.DBConnection()
        auth_id = authorid
        auth_name = authorname
        try:
            dbk_author_id = ''
            if authorid:
                # importer passes the dbk_id, which is the AuthorID only if Databazeknih added the author
                res = db.match('SELECT AuthorID,AuthorName,dbk_id from authors WHERE AuthorID=? or dbk_id=?',
                               (authorid, authorid))
                if res:
                    auth_id = res['AuthorID']
                    auth_name = res['AuthorName']
                    dbk_author_id = res['dbk_id'] or ''
            else:
                auth_name, auth_id = lazylibrarian.importer.get_preferred_author(authorname)

            self.logger.debug(f'[{auth_id}:{auth_name}] Now processing books with Databazeknih')
            db.action("UPDATE authors SET Status='Loading' WHERE AuthorID=?", (auth_id,))

            # keep a stored id on refresh, the user may have linked it by hand
            if not dbk_author_id:
                dbk_author_id = self.author_id_from_text(self._find_author(auth_name))
                if dbk_author_id and auth_id:
                    db.action("UPDATE authors SET dbk_id=? WHERE AuthorID=?", (dbk_author_id, auth_id))
            if not dbk_author_id:
                self.logger.warning(f"Author {auth_name} not found at Databazeknih")
                return

            results = []
            cache_hits = 0
            other_titles = {}
            for bookid, bookname, year in self._author_books(self._author_number(dbk_author_id),
                                                             prefer_language=True, other_titles=other_titles):
                if lazylibrarian.STOPTHREADS and thread_name() == "AUTHORUPDATE":
                    break
                # skip the more-info request, the list already has the first publication year
                bookdict, in_cache = self._book_from_id(bookid, more=False)
                cache_hits += in_cache
                if not bookdict:
                    self.logger.debug(f"Unable to read databazeknih book {bookid} {bookname}")
                    continue
                if year:
                    bookdict['bookdate'] = year
                # the author page only lists their books, the site may spell the name differently
                bookdict['authorid'] = auth_id
                bookdict['authorname'] = auth_name
                bookdict['author_fuzz'] = 100
                bookdict['book_fuzz'] = 100
                bookdict['isbn_fuzz'] = 0
                bookdict['highest_fuzz'] = 100
                results.append(bookdict)

            if not results:
                self.logger.warning(f"No books from Databazeknih for {auth_name}")
                return

            resultqueue = Queue()
            resultqueue.put(results)
            _ = add_author_books_to_db(resultqueue, bookstatus, audiostatus, entrystatus, reason,
                                       auth_id, self.get_series_members, self.get_bookdict_for_bookid,
                                       cache_hits=cache_hits)
            # the translations left out are searched for when a download finds nothing,
            # the book may have been added under another source's id, so match on dbk_id
            for bookid, titles in other_titles.items():
                db.action("UPDATE books SET OtherTitles=? WHERE dbk_id=?", ('\n'.join(titles), bookid))
        except Exception:
            self.logger.error(f'Unhandled exception in dbk.get_author_books: {traceback.format_exc()}')
        finally:
            db.action("UPDATE authors SET Status=? WHERE AuthorID=?", (entrystatus, auth_id))
            db.close()

    def get_bookdict_for_bookid(self, bookid=None):
        bookdict, in_cache = self._book_from_id(str(bookid))
        if bookdict:
            bookdict['first_publish_year'] = bookdict['bookdate'][:4]
        return bookdict, in_cache

    def get_series_members(self, series_id=None, series_title='', queue=None, refresh=False):
        """ Return [(position, title, author_name, author_id, book_id, pubdate)] sorted on position.
            author_id is left empty, the author is found by name when the book is added """
        dbk_series_id = str(series_id or '').removeprefix('DBK')
        resultlist = []
        if dbk_series_id.isdigit():
            url = self.SERIESURL % dbk_series_id
            pages = 0
            while url and pages < self.cfg_max_author_pages:
                page, _ = self._fetch(url)
                if not page:
                    break
                pages += 1
                members, url = self._parse_series_page(page)
                for position, bookid, title, authorname, year in members:
                    if position and bookid:
                        resultlist.append((position, title, authorname, '', bookid, year))
                if url and not url.startswith('http'):
                    url = self.BASEURL + url
        resultlist.sort(key=lambda item: float(item[0]))
        self.logger.debug(f"Found {len(resultlist)} for series {series_id}: {series_title}")
        if queue:
            queue.put(resultlist)
            return None
        return resultlist

    def add_bookid_to_db(self, bookid=None, bookstatus=None, audiostatus=None, reason='dbk.add_bookid_to_db'):
        # Find details on a book from provider using bookid
        # Ensure author in database, add book to database using provided or default statuses and reason
        if not CONFIG['DBK_API']:
            self.logger.warning('Databazeknih not enabled, check config')
            return False
        if not bookstatus:
            bookstatus = CONFIG['NEWBOOK_STATUS']
        if not audiostatus:
            audiostatus = CONFIG['NEWAUDIO_STATUS']

        bookdict, _ = self.get_bookdict_for_bookid(bookid)
        if not bookdict or bookdict['bookid'] != str(bookid):
            self.logger.debug(f'BookID {bookid} not found at Databazeknih')
            return False

        authorname = bookdict.get('authorname')
        if authorname:
            auth_name, _ = lazylibrarian.importer.get_preferred_author(authorname)
            db = database.DBConnection()
            res = db.match('SELECT authorid from authors WHERE authorname=?', (auth_name,))
            if res:
                bookdict['authorid'] = res['authorid']
            else:
                authorname, authorid, _ = lazylibrarian.importer.add_author_name_to_db(
                    author=auth_name, refresh=False, addbooks=False,
                    reason=f"Databazeknih add {bookid}:{bookdict['bookname']}", title=bookdict['bookname'])
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
        authorid = bookdict.get('authorid')
        if authorid:
            bookdict['status'] = bookstatus
            bookdict['audiostatus'] = audiostatus
            bookdict['reason'] = f"[{thread_name()}] {reason}"
            res = add_bookdict_to_db(bookdict)
            lazylibrarian.importer.update_totals(authorid)
            return res
        return False

    def find_results(self, searchterm=None, queue=None):
        # callers wait on the queue, so always put a result list on it
        if not CONFIG['DBK_API']:
            self.logger.warning('Databazeknih not enabled, check config')
            queue.put([])
            return False
        try:
            resultlist = []
            ignored = 0
            title = ''
            authorname = ''
            searchisbn = ''

            if is_valid_isbn(searchterm):
                searchisbn = re.sub(r'[^0-9X]', '', searchterm.upper())

            if '<ll>' in searchterm:  # special token separates title from author
                title, authorname = searchterm.split('<ll>')
                title = title.strip()
                authorname = authorname.strip()

            # strip all ascii and non-ascii quotes/apostrophes
            searchterm = strip_quotes(searchterm)
            fullterm = ' '.join(searchterm.replace('<ll>', ' ').split())
            self.logger.debug(f'Now searching Databazeknih with searchterm: {fullterm}')

            if searchisbn:
                entries = []
                page, _ = self._fetch(self.ISBNURL % urlencode({'q': searchisbn}))
                # the site redirects an isbn it knows to the book page
                book = self._parse_book(page) if page else {}
                if book:
                    entries.append(book)
            elif authorname and not title:
                # site search only matches titles, so list the author's books instead
                entries = []
                dbk_author_id = self._find_author(authorname)
                if dbk_author_id:
                    for bookid, bookname, year in self._author_books(dbk_author_id):
                        entries.append({'bookid': bookid, 'bookname': bookname, 'authors': [authorname],
                                        'bookdate': year, 'bookimg': 'images/nocover.png', 'bookrate': 0})
            else:
                # the site searches titles, so leave the author out of the query, and a
                # series suffix like 'Krev elfů (Zaklínač, #3)' would only add noise
                query = title or fullterm
                if query.endswith(')'):
                    query = query.rsplit('(', 1)[0].strip() or query
                entries = self._search_books(strip_quotes(query))

            valid_langs = get_list(CONFIG['IMP_PREFLANG'])
            for entry in entries:
                if 'authorname' in entry:  # a whole bookdict from an isbn search
                    book = entry
                else:
                    if not entry['authors'] or not entry['bookname']:
                        continue
                    book = {
                        'authorname': lazylibrarian.importer.get_preferred_author(entry['authors'][0])[0],
                        'bookid': entry['bookid'],
                        'bookname': entry['bookname'],
                        'booksub': '',
                        'bookisbn': '',
                        'bookpub': '',
                        'bookdate': entry['bookdate'] or '0000',
                        # search results are already filtered on language by the site
                        'booklang': '',
                        'booklink': self.BOOKURL % entry['bookid'],
                        'bookrate': entry['bookrate'],
                        'bookrate_count': 0,
                        'bookimg': entry['bookimg'],
                        'bookpages': 0,
                        'bookgenre': '',
                        'bookdesc': '',
                        'contributors': [["", name] for name in entry['authors'][1:]],
                        'series': [],
                    }
                    if ':' in book['bookname']:
                        main, sub = book['bookname'].split(':', 1)
                        if main.strip() and sub.strip():
                            book['bookname'] = main.strip()
                            book['booksub'] = sub.strip()

                if book['booklang'] and "All" not in valid_langs and book['booklang'] not in valid_langs:
                    self.logger.debug(f"Skipped {book['bookname']} with language {book['booklang']}")
                    ignored += 1
                    continue

                if authorname:
                    author_fuzz = fuzz.token_sort_ratio(book['authorname'], authorname, processor=default_process)
                else:
                    author_fuzz = fuzz.token_sort_ratio(book['authorname'], fullterm, processor=default_process)
                if title:
                    match_title = title.rsplit('(', 1)[0] if title.endswith(')') else title
                    book_fuzz = fuzz.token_set_ratio(book['bookname'], match_title, processor=default_process)
                    # lose a point for each extra word in the fuzzy matches so we get the closest match
                    book_fuzz -= abs(len(get_list(book['bookname'])) - len(get_list(match_title)))
                else:
                    book_fuzz = fuzz.token_set_ratio(book['bookname'], fullterm, processor=default_process)
                isbn_fuzz = 100 if searchisbn and book['bookisbn'] == searchisbn else 0
                if searchisbn and not book['bookisbn']:
                    # the site took us to the book for this isbn
                    isbn_fuzz = 100
                highest_fuzz = max((author_fuzz + book_fuzz) / 2, isbn_fuzz)

                bookname = replace_all(book['bookname'], {':': '.', '"': '', '\'': ''})
                bookname = unaccented(bookname, only_ascii=False)

                author_id = ''
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
                    'source': 'DBK'
                })

            resultcount = len(resultlist)
            self.logger.debug(f"Returning {resultcount} {plural(resultcount, 'result')} for {fullterm}")
            self.logger.debug(f"Removed {ignored} unwanted language {plural(ignored, 'result')}")
            queue.put(resultlist)
            return resultcount > 0

        except Exception:
            self.logger.error(f'Unhandled exception in DBK.find_results: {traceback.format_exc()}')
            queue.put([])
            return False
