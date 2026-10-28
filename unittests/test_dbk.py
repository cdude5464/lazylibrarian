#  This file is part of Lazylibrarian.
#
# Purpose:
#   Testing functionality in dbk.py (Databáze knih) without network access

import unicodedata
from queue import Queue
from unittest import mock

import lazylibrarian
from lazylibrarian import dbk, importer
from lazylibrarian.config2 import CONFIG
from lazylibrarian.dbupgrade import has_column
from lazylibrarian.database import DBConnection
from unittests.unittesthelpers import LLTestCaseWithStartup

# Shortened copies of real pages from https://www.databazeknih.cz
BOOK_PAGE = r"""<html><head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Book",
  "name": "Krev elfů",
  "url": "https://www.databazeknih.cz/prehled-knihy/zaklinac-saga-krev-elfu-30482",
    "isbn": "80-85951-05-3",
    "author": [
          {
        "@type": "Person",
        "name": "Andrzej Sapkowski"
      }      ],
  "image": "https:\/\/www.databazeknih.cz\/img\/books\/30_\/30482\/bmid_krev-elfu-Jqe-30482.jpg",
    "aggregateRating": {
    "@type": "AggregateRating",
    "ratingValue": "4.6",
    "ratingCount": "5790",
    "bestRating": "5",
    "worstRating": "1"
  },
    "description": "První část…",
    "publisher": [
          {
        "@type": "Organization",
        "name": "Leonardo"
      }      ],
    "inLanguage": "cs",
  "genre": [
          "Literatura světová",          "Romány",          "Fantasy"      ]}
</script></head><body>
<div class="lora book_detail_serie_info">
    <p class="inline">
        <a class="odright_pet" href='/serie/zaklinac-saga---7063?lang=cz' title='Zaklínač: sága'>
            Zaklínač: sága
        </a> série</p>
    <span class="nowrap">
        <span class="odright_pet">1. díl</span>
    </span>
    <br />
    <p class="inline">
        <a class="odright_pet" href='/serie/zaklinac-zaklinac-13665?lang=cz' title='Zaklínač'>
            Zaklínač
        </a> série</p>
    3. díl
</div>
<h1 class="oddown_zero">Krev elfů</h1>
<div class="lora lineHeightMid">
    <a href='/zanry/fantasy-21'>Fantasy</a><br />
    1998
    <span class='pozn'>,</span> <a href='/nakladatelstvi/leonardo-338'>Leonardo</a>
</div>
<div id='left'>
    <h2>O knize <em class="nobold">Krev elfů</em></h2>
    <p class='new2 odtop'>První část ságy o Zaklínači.
Geralt, Ciri, Yennefer a další.</p>
</div>
</body></html>"""

MORE_INFO = """
<div class='book-details__row'><dt>Originální název</dt><dd>Krew elfów, 1994</dd></div>
<div class='book-details__row'><dt>Počet stran</dt><dd><span itemprop='numberOfPages'>308</span></dd></div>
<div class='book-details__row'><dt>Jazyk vydání</dt><dd>český</dd></div>
<div class='book-details__row'><dt>ISBN</dt><dd>80-85951-05-3</dd></div>
"""

SEARCH_PAGE = """<html><body>
<p class='new'>
    <a href="/prehled-knihy/zaklinac-saga-krev-elfu-30482"><picture>
        <img src="https://www.databazeknih.cz/img/books/30_/30482/krev-elfu-Jqe-30482.jpg?v=1577582533"
             alt="Obálka knihy Krev elfů" class="img_39_left odtopm" /></picture></a>
    <img src='img/content/squares/red.gif' title='91%' alt='91%' class='odr' /><a class='new' type='book'
        href='/prehled-knihy/zaklinac-saga-krev-elfu-30482'>Krev elfů</a>
    <br /><span class='pozn'>
        1998,
        Andrzej Sapkowski
    </span>
</p>
<p class='new'>
    <img src='img/content/squares/blue.gif' title='47%' alt='47%' class='odr' /><a class='new' type='book'
        href='/prehled-knihy/john-sinclair-na-stope-hruzy-zaklinac-40113'>Zaklínač</a>
    <br /><span class='pozn'>
        1998,
        Jason Dark (p)
    </span>
</p>
<div class="pager"><div class="pagination">
    <span class="current">1</span>
    <span class="next"><a rel="next" href="/vyhledavani/knihy?q=krev&amp;page=2">&gt;</a></span>
</div></div>
</body></html>"""

AUTHOR_BOOKS_PAGE = """<html><body>
<h3 class='midlRowHeight oddown'>
    <a href='/prehled-knihy/krev-elfu-433' title='Krev elfů'>Krev elfů</a>
    <span class='pozn odl'> 2011 (1. vydání 1994) </span>
</h3>
<h3 class='midlRowHeight oddown'>
    <a href='/prehled-knihy/magicke-stripky-30500' title='Magické střípky'>Magické střípky</a>
    <span class='pozn odl'> 2002 (1. vydání) </span>
</h3>
<h3>Až vyjde nová kniha autora</h3>
<div class="pager"><div class="pagination"></div></div>
</body></html>"""

# Edgar Wallace's Czech and Slovak books, the same work is a separate book in each language
WALLACE_BOOKS_PAGE = """<html><body>
<select name="lang"><option value="/vydane-knihy/edgar-wallace-4308?lang=czsk">český + slovenský jazyk</option>
<option value="/vydane-knihy/edgar-wallace-4308?lang=cz" selected>český jazyk</option>
<option value="/vydane-knihy/edgar-wallace-4308?lang=sk">slovenský jazyk</option></select>
<h3><a href='/prehled-knihy/andel-hruzy-99197'>Anděl hrůzy</a><span class='pozn'> 1931 (1. vydání 1922) </span></h3>
<h3><a href='/prehled-knihy/bily-tvar-99150'>Bílá tvář</a><span class='pozn'> 1930 (1. vydání) </span></h3>
<h3><a href='/prehled-knihy/hlasy-noci-555'>Hlasy noci</a><span class='pozn'> 1999 (1. vydání) </span></h3>
<div class="pager"><div class="pagination"></div></div>
</body></html>"""

WALLACE_SK_PAGE = """<html><body>
<h3><a href='/prehled-knihy/anjel-hrozy-99198'>Anjel hrôzy</a><span class='pozn'> 1969 (1. vydání 1922) </span></h3>
<div class="pager"><div class="pagination"></div></div>
</body></html>"""


def more_info(original, language):
    original = f"<div class='book-details__row'><dt>Originální název</dt><dd>{original}</dd></div>" if original else ''
    return f"{original}<div class='book-details__row'><dt>Jazyk vydání</dt><dd>{language}</dd></div>"


WALLACE_MORE = {
    '99197': more_info('The Angel of Terror, 1922', 'český'),
    '99198': more_info('The Angel of Terror, 1922', 'slovenský'),
    '99150': more_info('The Face in the Night, 1924', 'český'),
    '555': more_info('', 'český'),
}

SERIES_PAGE = """<html><body>
<div itemprop="hasPart" itemscope itemtype="https://schema.org/Book">
    <span class="gray odright_pet">2. v sérii</span>
    <a class='biggest odr' href='/prehled-knihy/zaklinac-saga-cas-opovrzeni-30399' title='Čas opovržení'>Čas opovržení</a>
    <span class='pozn odtop'><a href="/serie-autora/andrzej-sapkowski-269">Andrzej Sapkowski</a>, 2007</span>
</div>
<div itemprop="hasPart" itemscope itemtype="https://schema.org/Book">
    <span class="gray odright_pet">1. v sérii</span>
    <a class='biggest odr' href='/prehled-knihy/krev-elfu-433' title='Krev elfů'>Krev elfů</a>
    <span class='pozn odtop'><a href="/serie-autora/andrzej-sapkowski-269">Andrzej Sapkowski</a>, 2011</span>
</div>
</body></html>"""

AUTHOR_SEARCH_PAGE = """<html><body>
<a href="autori/andrzej-sapkowski-269">Andrzej Sapkowski</a>
<a href="autori/andrzej-sapkowski-ml-99999">Andrzej Nowak</a>
</body></html>"""

AUTHOR_PAGE = r"""<html><head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Person",
  "name": "Karel Čapek",
  "url": "https://www.databazeknih.cz/autori/karel-capek-101",
  "image": "https:\/\/www.databazeknih.cz\/img\/authors\/10_\/101\/karel-capek-z04-101.jpg",
  "description": "Český prozaik, dramatik, novinář a překladatel...",
  "birthDate": "1890-01-09",
  "deathDate": "1938-12-25",
  "birthPlace": {
    "@type": "Place",
    "name": "Malé Svatoňovice"
  }
}
</script></head><body>
<h1>Karel Čapek</h1>
</body></html>"""


class DBKTest(LLTestCaseWithStartup):

    @classmethod
    def setUpClass(cls) -> None:
        rc = super().setUpClass()
        cls.dbk_api = CONFIG.get_bool('DBK_API')
        cls.preflang = CONFIG.get_csv('IMP_PREFLANG')
        CONFIG.set_bool('DBK_API', True)
        CONFIG.set_csv('IMP_PREFLANG', 'cs, Czech')
        return rc

    @classmethod
    def tearDownClass(cls) -> None:
        CONFIG.set_bool('DBK_API', cls.dbk_api)
        CONFIG.set_csv('IMP_PREFLANG', cls.preflang)
        return super().tearDownClass()

    def test_id_from_link(self):
        self.assertEqual(dbk.DBK._id_from_link('/prehled-knihy/krev-elfu-433'), '433')
        self.assertEqual(dbk.DBK._id_from_link('/serie/zaklinac-saga---7063?lang=cz'), '7063')
        self.assertEqual(dbk.DBK._id_from_link('autori/andrzej-sapkowski-269'), '269')
        self.assertEqual(dbk.DBK._id_from_link('/prehled-knihy/'), '')

    def test_parse_book(self):
        book = dbk.DBK()._parse_book(BOOK_PAGE, MORE_INFO)
        self.assertEqual(book['bookid'], '30482')
        self.assertEqual(book['bookname'], 'Krev elfů')
        self.assertEqual(book['authorname'], 'Andrzej Sapkowski')
        self.assertEqual(book['bookisbn'], '8085951053')
        self.assertEqual(book['bookpub'], 'Leonardo')
        # first publication from the original title, not this edition's 1998
        self.assertEqual(book['bookdate'], '1994')
        self.assertEqual(book['booklang'], 'Czech')
        self.assertEqual(book['bookpages'], 308)
        self.assertEqual(book['bookrate'], 4.6)
        self.assertEqual(book['bookrate_count'], 5790)
        self.assertEqual(book['bookgenre'], 'Literatura světová,Romány,Fantasy')
        self.assertTrue(book['bookimg'].startswith('https://www.databazeknih.cz/img/books/'))
        # the whole description from the page, not the shortened json-ld one
        self.assertTrue(book['bookdesc'].startswith('První část ságy o Zaklínači.\nGeralt'))
        self.assertEqual(book['series'], [('Zaklínač: sága', 'DBK7063', '1'), ('Zaklínač', 'DBK13665', '3')])
        self.assertEqual(book['source'], 'DBK')

    def test_parse_book_without_more_info(self):
        book = dbk.DBK()._parse_book(BOOK_PAGE)
        self.assertEqual(book['bookdate'], '1998')
        self.assertEqual(book['bookpages'], 0)

    def test_parse_book_not_a_book(self):
        self.assertEqual(dbk.DBK()._parse_book(SEARCH_PAGE), {})

    def test_parse_search(self):
        results, next_page = dbk.DBK()._parse_search(SEARCH_PAGE)
        self.assertEqual([r['bookid'] for r in results], ['30482', '40113'])
        self.assertEqual(results[0]['authors'], ['Andrzej Sapkowski'])
        self.assertEqual(results[0]['bookdate'], '1998')
        self.assertEqual(results[0]['bookrate'], 4.55)
        # pseudonym marker removed
        self.assertEqual(results[1]['authors'], ['Jason Dark'])
        self.assertEqual(results[1]['bookimg'], 'images/nocover.png')
        self.assertEqual(next_page, '/vyhledavani/knihy?q=krev&page=2')

    def test_parse_book_list(self):
        books, next_page = dbk.DBK()._parse_book_list(AUTHOR_BOOKS_PAGE)
        self.assertEqual(books, [('433', 'Krev elfů', '1994'), ('30500', 'Magické střípky', '2002')])
        self.assertEqual(next_page, '')

    def test_series_members(self):
        with mock.patch.object(dbk.DBK, '_fetch', return_value=(SERIES_PAGE, True)) as fetch:
            members = dbk.DBK().get_series_members('DBK7063', 'Zaklínač: sága')
            self.assertEqual(fetch.call_args[0][0], 'https://www.databazeknih.cz/serie/serie-7063')
        self.assertEqual(members, [('1', 'Krev elfů', 'Andrzej Sapkowski', '', '433', '2011'),
                                   ('2', 'Čas opovržení', 'Andrzej Sapkowski', '', '30399', '2007')])

    def test_search_language(self):
        dbk_api = dbk.DBK()
        try:
            for prefs, expected in [('cs, Czech', 'cz'), ('sk', 'sk'), ('Czech, Slovak', 'czsk'),
                                    ('en, eng, en-US, en-GB, English', 'en'), ('All', ''), ('Czech, German', '')]:
                CONFIG.set_csv('IMP_PREFLANG', prefs)
                self.assertEqual(dbk_api._search_language(), expected, prefs)
        finally:
            CONFIG.set_csv('IMP_PREFLANG', 'cs, Czech')

    def test_author_languages(self):
        dbk_api = dbk.DBK()
        try:
            for prefs, expected in [('cs, Czech', ['cz']), ('sk, Slovak', ['sk']), ('sk, Slovak, cs, Czech', ['sk', 'cz']),
                                    ('Czech, en, Slovak', ['cz', 'sk']), ('All', []), ('en, English', []),
                                    ('sk, All', [])]:
                CONFIG.set_csv('IMP_PREFLANG', prefs)
                self.assertEqual(dbk_api._author_languages(), expected, prefs)
        finally:
            CONFIG.set_csv('IMP_PREFLANG', 'cs, Czech')

    def test_author_books_language(self):
        """ Without lang the site lists only the Czech books. The short page name redirects
            to the full one without lang, so other languages use the full name """
        try:
            for prefs, urls in [('cs, Czech', ['autor-4308']),
                                ('sk, Slovak', ['autor-4308', 'edgar-wallace-4308?lang=sk']),
                                # the czsk list has only one of the Czech and Slovak translations
                                ('sk, cs', ['autor-4308', 'edgar-wallace-4308?lang=sk', 'autor-4308']),
                                ('All', ['autor-4308', 'edgar-wallace-4308?lang=czsk'])]:
                CONFIG.set_csv('IMP_PREFLANG', prefs)
                with mock.patch.object(dbk.DBK, '_fetch', return_value=(WALLACE_BOOKS_PAGE, True)) as fetch:
                    dbk.DBK()._author_books('4308')
                self.assertEqual([c[0][0] for c in fetch.call_args_list],
                                 [f'https://www.databazeknih.cz/vydane-knihy/{url}' for url in urls], prefs)
        finally:
            CONFIG.set_csv('IMP_PREFLANG', 'cs, Czech')

    def test_author_books_prefer_language(self):
        """ One translation of each work, in the language that comes first in the preferences """
        pages = {'https://www.databazeknih.cz/vydane-knihy/autor-4308': WALLACE_BOOKS_PAGE,
                 'https://www.databazeknih.cz/vydane-knihy/edgar-wallace-4308?lang=sk': WALLACE_SK_PAGE}
        pages.update({f'https://www.databazeknih.cz/book-detail-more-info/{bookid}': more
                      for bookid, more in WALLACE_MORE.items()})
        try:
            for prefs, expected in [('sk, Slovak, cs, Czech', ['99198', '99150', '555']),
                                    ('cs, Czech, sk, Slovak', ['99197', '99150', '555'])]:
                CONFIG.set_csv('IMP_PREFLANG', prefs)
                with mock.patch.object(dbk.DBK, '_fetch', side_effect=lambda url: (pages.get(url, ''), True)):
                    books = dbk.DBK()._author_books('4308', prefer_language=True)
                    self.assertEqual([b[0] for b in books], expected, prefs)
                    # searches list every book, without reading each one
                    self.assertEqual(len(dbk.DBK()._author_books('4308')), 4)
        finally:
            CONFIG.set_csv('IMP_PREFLANG', 'cs, Czech')

    def test_find_results(self):
        pages = {'https://www.databazeknih.cz/vyhledavani/knihy?q=Krev+elf%C5%AF&lang=cz': SEARCH_PAGE}
        with mock.patch.object(dbk.DBK, '_fetch', side_effect=lambda url: (pages.get(url, ''), False)) as fetch:
            queue = Queue()
            self.assertTrue(dbk.DBK().find_results('Krev elfů (Zaklínač, #3)<ll>Andrzej Sapkowski', queue))
            # series suffix and author are left out of the title search
            self.assertEqual(fetch.call_args_list[0][0][0], list(pages)[0])
        results = queue.get()
        self.assertEqual(len(results), 2)
        best = max(results, key=lambda r: r['highest_fuzz'])
        self.assertEqual(best['bookid'], '30482')
        self.assertEqual(best['source'], 'DBK')

    def test_find_results_isbn(self):
        with mock.patch.object(dbk.DBK, '_fetch', return_value=(BOOK_PAGE, False)) as fetch:
            queue = Queue()
            self.assertTrue(dbk.DBK().find_results('80-85951-05-3', queue))
            self.assertEqual(fetch.call_args[0][0], 'https://www.databazeknih.cz/search?q=8085951053')
        results = queue.get()
        self.assertEqual(results[0]['bookid'], '30482')
        self.assertEqual(results[0]['isbn_fuzz'], 100)

    def test_find_author(self):
        with mock.patch.object(dbk.DBK, '_fetch', return_value=(AUTHOR_SEARCH_PAGE, False)):
            self.assertEqual(dbk.DBK()._find_author('Andrzej Sapkowski'), '269')
            self.assertEqual(dbk.DBK()._find_author('Terry Pratchett'), '')

    def test_find_results_author_only(self):
        pages = {'https://www.databazeknih.cz/search?in=authors&q=Andrzej+Sapkowski': AUTHOR_SEARCH_PAGE,
                 'https://www.databazeknih.cz/vydane-knihy/autor-269': AUTHOR_BOOKS_PAGE}
        with mock.patch.object(dbk.DBK, '_fetch', side_effect=lambda url: (pages.get(url, ''), False)):
            queue = Queue()
            self.assertTrue(dbk.DBK().find_results('<ll>Andrzej Sapkowski', queue))
        results = queue.get()
        self.assertEqual([r['bookid'] for r in results], ['433', '30500'])
        self.assertEqual(results[0]['authorname'], 'Andrzej Sapkowski')

    def test_dbk_id_columns(self):
        db = DBConnection()
        try:
            self.assertTrue(has_column(db, 'books', 'dbk_id'))
            self.assertTrue(has_column(db, 'authors', 'dbk_id'))
        finally:
            db.close()

    def test_author_id_from_text(self):
        for text in ['269', 'DBK269', 'dbk269', ' 269 ', 'https://www.databazeknih.cz/autori/andrzej-sapkowski-269',
                     'https://www.databazeknih.cz/autori/andrzej-sapkowski-269/?lang=cz', 'autori/andrzej-sapkowski-269']:
            self.assertEqual(dbk.DBK.author_id_from_text(text), 'DBK269', text)
        for text in ['', None, 'Andrzej Sapkowski', 'DBK']:
            self.assertEqual(dbk.DBK.author_id_from_text(text), '', text)

    def test_get_author_info(self):
        with mock.patch.object(dbk.DBK, '_fetch', return_value=(AUTHOR_PAGE, False)) as fetch:
            author = dbk.DBK().get_author_info(authorid='DBK101')
            self.assertEqual(fetch.call_args[0][0], 'https://www.databazeknih.cz/autori/autor-101')
        self.assertEqual(author['authorid'], 'DBK101')
        # format_author_name stores names decomposed
        self.assertEqual(unicodedata.normalize('NFC', author['authorname']), 'Karel Čapek')
        self.assertEqual(author['authorlink'], 'https://www.databazeknih.cz/autori/karel-capek-101')
        self.assertEqual(author['authorimg'],
                         'https://www.databazeknih.cz/img/authors/10_/101/karel-capek-z04-101.jpg')
        self.assertEqual(author['authorborn'], '1890-01-09')
        self.assertEqual(author['authordeath'], '1938-12-25')
        self.assertTrue(author['about'].startswith('Český prozaik, dramatik'))

    def test_get_author_info_no_photo_or_page(self):
        page = AUTHOR_PAGE.replace(r'https:\/\/www.databazeknih.cz\/img\/authors\/10_\/101\/karel-capek'
                                   r'-z04-101.jpg', '/img/content/noimage-author.png')
        with mock.patch.object(dbk.DBK, '_fetch', return_value=(page, False)):
            self.assertEqual(dbk.DBK().get_author_image(authorid='DBK101'), '')
        with mock.patch.object(dbk.DBK, '_fetch', return_value=('', False)):
            self.assertEqual(dbk.DBK().get_author_info(authorid='DBK101'), {})
        # a page that is not an author
        with mock.patch.object(dbk.DBK, '_fetch', return_value=(BOOK_PAGE, False)):
            self.assertEqual(dbk.DBK().get_author_info(authorid='101'), {})

    def test_find_author_id(self):
        pages = {'https://www.databazeknih.cz/search?in=authors&q=Karel+%C4%8Capek':
                 '<a href="/autori/karel-capek-101">Karel Čapek</a><a href="/autori/karel-jan-capek-4910">'
                 'Karel Jan Čapek</a>',
                 'https://www.databazeknih.cz/autori/autor-101': AUTHOR_PAGE}
        with mock.patch.object(dbk.DBK, '_fetch', side_effect=lambda url: (pages.get(url, ''), False)):
            author = dbk.DBK().find_author_id(authorname='Karel Čapek', title='R.U.R.')
            self.assertEqual(author['authorid'], 'DBK101')
            self.assertEqual(unicodedata.normalize('NFC', author['authorname']), 'Karel Čapek')
            self.assertEqual(dbk.DBK().find_author_id(authorname='Terry Pratchett'), {})
            # without an id, get_author_info finds the author by name
            self.assertEqual(dbk.DBK().get_author_info(authorname='Karel Čapek')['authorid'], 'DBK101')

    def test_author_source(self):
        source = lazylibrarian.INFOSOURCES['DBK']
        self.assertEqual(source['author_key'], 'dbk_id')
        self.assertEqual(source['author_link'], 'dbk_link')
        self.assertIn('dbk_id', importer.author_keys())

    def test_author_id_lookup_no_collision(self):
        """ A GoodReads author with id 269 and the Databazeknih author 269 are different people """
        db = DBConnection()
        try:
            db.action("DELETE FROM authors WHERE AuthorID IN ('269', 'DBK269')")
            db.action("INSERT INTO authors (AuthorID, AuthorName, gr_id) VALUES ('269', 'Goodreads Author', '269')")
            db.action("INSERT INTO authors (AuthorID, AuthorName, dbk_id) VALUES ('DBK269', 'Andrzej Sapkowski', "
                      "'DBK269')")
            self.assertEqual(importer.get_preferred_author('x', authorid='269'), ('Goodreads Author', '269'))
            self.assertEqual(importer.get_preferred_author('x', authorid='DBK269'), ('Andrzej Sapkowski', 'DBK269'))
        finally:
            db.action("DELETE FROM authors WHERE AuthorID IN ('269', 'DBK269')")
            db.close()

    def test_get_author_books_by_dbk_id(self):
        """ The importer passes the dbk_id, the author may have been added from another source """
        pages = {'https://www.databazeknih.cz/vydane-knihy/autor-269': AUTHOR_BOOKS_PAGE,
                 'https://www.databazeknih.cz/prehled-knihy/kniha-433': BOOK_PAGE,
                 'https://www.databazeknih.cz/prehled-knihy/kniha-30500': BOOK_PAGE}
        db = DBConnection()
        try:
            db.action("DELETE FROM authors WHERE AuthorID='12345'")
            db.action("INSERT INTO authors (AuthorID, AuthorName, gr_id, dbk_id, Status) VALUES "
                      "('12345', 'Andrzej Sapkowski', '12345', 'DBK269', 'Active')")
            with mock.patch.object(dbk.DBK, '_fetch', side_effect=lambda url: (pages.get(url, ''), True)), \
                    mock.patch.object(dbk, 'add_author_books_to_db') as add_books:
                dbk.DBK().get_author_books('DBK269', 'Andrzej Sapkowski', entrystatus='Active')
            self.assertTrue(add_books.called)
            args = add_books.call_args[0]
            books = args[0].get()
            self.assertEqual(len(books), 2)
            self.assertEqual({b['authorid'] for b in books}, {'12345'})
            self.assertEqual(args[5], '12345')
        finally:
            db.action("DELETE FROM authors WHERE AuthorID='12345'")
            db.close()

    def test_dbk_link_column(self):
        db = DBConnection()
        try:
            self.assertTrue(has_column(db, 'authors', 'dbk_link'))
        finally:
            db.close()
