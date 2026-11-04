#  This file is part of Lazylibrarian.
#
# Purpose:
#   Testing functionality in bn.py (Biblioteka Narodowa) without network access

import unicodedata
from queue import Queue
from unittest import mock

from lxml import etree

from lazylibrarian import bn, database
from lazylibrarian.config2 import CONFIG
from lazylibrarian.dbupgrade import has_column
from unittests.unittesthelpers import LLTestCaseWithStartup

# Shortened copies of real records from https://data.bn.org.pl/api/institutions/bibs.marcxml
BN_RESPONSE = """<?xml version="1.0" encoding="UTF-8"?>
<resp>
  <nextPage>https://data.bn.org.pl/api/institutions/bibs.marcxml?author=Sapkowski&amp;limit=100&amp;sinceId=5382028</nextPage>
  <collection>
    <record xmlns='http://www.loc.gov/MARC21/slim'><leader>02824nam a2200829 i 4500</leader>
      <controlfield tag='001'>b0000001011104</controlfield>
      <controlfield tag='008'>970510s1994    pl           |000 f pol  </controlfield>
      <datafield ind1=' ' ind2=' ' tag='020'><subfield code='a'>8370540791</subfield></datafield>
      <datafield ind1=' ' ind2=' ' tag='041'><subfield code='a'>pol</subfield></datafield>
      <datafield ind1='1' ind2=' ' tag='100'><subfield code='a'>Sapkowski, Andrzej</subfield>
        <subfield code='d'>(1948- )</subfield><subfield code='e'>Autor</subfield></datafield>
      <datafield ind1='1' ind2='0' tag='245'><subfield code='a'>Krew elfów /</subfield>
        <subfield code='c'>Andrzej Sapkowski.</subfield></datafield>
      <datafield ind1=' ' ind2=' ' tag='260'><subfield code='a'>Warszawa :</subfield>
        <subfield code='b'>"SuperNOWA",</subfield><subfield code='c'>1994</subfield></datafield>
      <datafield ind1='1' ind2=' ' tag='490'><subfield code='a'>Saga o wiedźminie / Andrzej Sapkowski ;</subfield>
        <subfield code='v'>t. 1</subfield></datafield>
      <datafield ind1=' ' ind2='7' tag='648'><subfield code='a'>1901-2000</subfield><subfield code='2'>DBN</subfield></datafield>
      <datafield ind1=' ' ind2='7' tag='650'><subfield code='a'>Potwory</subfield><subfield code='2'>DBN</subfield></datafield>
      <datafield ind1=' ' ind2='7' tag='655'><subfield code='a'>Fantasy</subfield><subfield code='2'>DBN</subfield></datafield>
      <datafield ind1='1' ind2=' ' tag='700'><subfield code='a'>Simon, Erik</subfield>
        <subfield code='e'>Tłumaczenie</subfield></datafield>
      <datafield ind1='1' ind2=' ' tag='800'><subfield code='a'>Sapkowski, Andrzej</subfield>
        <subfield code='d'>(1948- ).</subfield><subfield code='t'>Wiedźmin</subfield><subfield code='v'>t. 1</subfield></datafield>
    </record>
    <record xmlns='http://www.loc.gov/MARC21/slim'><leader>03018nam a2200865 i 4500</leader>
      <controlfield tag='001'>b0000005382027</controlfield>
      <controlfield tag='008'>170103s2014    pl           |000 j pol  </controlfield>
      <datafield ind1=' ' ind2=' ' tag='020'><subfield code='a'>9788375780635</subfield>
        <subfield code='q'>(oprawa miękka)</subfield></datafield>
      <datafield ind1='1' ind2=' ' tag='100'><subfield code='a'>Sapkowski, Andrzej</subfield>
        <subfield code='e'>Autor</subfield></datafield>
      <datafield ind1='1' ind2='0' tag='245'><subfield code='a'>Ostatnie życzenie /</subfield>
        <subfield code='c'>Andrzej Sapkowski.</subfield></datafield>
      <datafield ind1=' ' ind2='1' tag='264'><subfield code='a'>Warszawa :</subfield>
        <subfield code='b'>SuperNOWA,</subfield><subfield code='c'>copyright 2014.</subfield></datafield>
      <datafield ind1=' ' ind2=' ' tag='520'><subfield code='a'>Pierwszy tom opowiadań o wiedźminie.</subfield></datafield>
    </record>
    <record xmlns='http://www.loc.gov/MARC21/slim'><leader>01234nas a2200301 i 4500</leader>
      <controlfield tag='001'>b0000000123456</controlfield>
      <datafield ind1='0' ind2='0' tag='245'><subfield code='a'>Nowa Fantastyka.</subfield></datafield>
    </record>
  </collection>
</resp>
"""


class BNTest(LLTestCaseWithStartup):

    @classmethod
    def setUpClass(cls) -> None:
        rc = super().setUpClass()
        cls.bn_api = CONFIG.get_bool('BN_API')
        cls.preflang = CONFIG.get_csv('IMP_PREFLANG')
        CONFIG.set_bool('BN_API', True)
        CONFIG.set_csv('IMP_PREFLANG', 'Polish')
        return rc

    @classmethod
    def tearDownClass(cls) -> None:
        CONFIG.set_bool('BN_API', cls.bn_api)
        CONFIG.set_csv('IMP_PREFLANG', cls.preflang)
        return super().tearDownClass()

    @staticmethod
    def records():
        xml_data = etree.XML(BN_RESPONSE.encode("utf-8"))
        return xml_data.xpath("./collection/marc21:record", namespaces=bn.BN.NS)

    def test_api_id(self):
        self.assertEqual(bn.BN._api_id('b0000005382027'), 5382027)
        self.assertEqual(bn.BN._api_id('b00001080000546'), 1080000546)
        self.assertEqual(bn.BN._api_id(''), 0)

    def test_strip_isbd(self):
        self.assertEqual(bn.BN._strip_isbd('Krew elfów /'), 'Krew elfów')
        self.assertEqual(bn.BN._strip_isbd('Warszawa :'), 'Warszawa')
        self.assertEqual(bn.BN._strip_isbd('Wydanie I w tej edycji.'), 'Wydanie I w tej edycji')
        self.assertEqual(bn.BN._strip_isbd('Kowalski, J.'), 'Kowalski, J.')

    def test_parse_record(self):
        book = bn.BN()._parse_marc21_record(self.records()[0])
        self.assertEqual(book['bnid'], 'b0000001011104')
        self.assertEqual(book['title'], 'Krew elfów')
        # translator is not an author
        self.assertEqual(book['authors'], ['Sapkowski, Andrzej'])
        self.assertEqual(book['isbn'], '8370540791')
        self.assertEqual(book['publisher_location'], 'Warszawa')
        self.assertEqual(book['publisher_name'], 'SuperNOWA')
        self.assertEqual(book['pubdate'].year, 1994)
        self.assertEqual(book['languages'], ['Polish'])
        # the Polish series name printed in the book (490) wins over the catalogue's 800
        self.assertEqual(book['series'], 'Saga o wiedźminie')
        self.assertEqual(book['series_index'], '1')
        # chronological 648 terms are not used as subjects
        self.assertEqual(book['subjects_dbn'], ['Potwory', 'Fantasy'])

    def test_parse_record_language_from_008(self):
        book = bn.BN()._parse_marc21_record(self.records()[1])
        self.assertEqual(book['languages'], ['Polish'])
        self.assertEqual(book['pubdate'].year, 2014)
        self.assertEqual(book['comments'], 'Pierwszy tom opowiadań o wiedźminie.')
        self.assertIsNone(book['series'])

    def test_parse_record_skips_serials(self):
        self.assertIsNone(bn.BN()._parse_marc21_record(self.records()[2]))

    def test_book_dict(self):
        bn_api = bn.BN()
        meta = bn_api._create_meta_record(bn_api._parse_marc21_record(self.records()[0]), '')
        book = bn_api._book_dict(meta)
        self.assertEqual(book['bookid'], 'b0000001011104')
        self.assertEqual(book['authorname'], 'Andrzej Sapkowski')
        self.assertEqual(book['bookname'], 'Krew elfów')
        self.assertEqual(book['bookisbn'], '8370540791')
        self.assertEqual(book['bookpub'], 'Warszawa ; SuperNOWA')
        self.assertEqual(book['bookdate'], '1994-01-01')
        self.assertEqual(book['booklang'], 'Polish')
        self.assertEqual(book['bookgenre'], 'Potwory,Fantasy')
        self.assertIn('b0000001011104', book['booklink'])
        # series id must start with the BN source prefix so bookdict can merge series
        self.assertEqual(book['series'], [('Saga o wiedźminie', 'BNb0000001011104', 1.0)])
        self.assertEqual(book['source'], 'BN')

    def test_find_results(self):
        bn_api = bn.BN()
        with mock.patch.object(bn.BN, '_execute_query', return_value=(self.records(), False)) as query:
            queue = Queue()
            self.assertTrue(bn_api.find_results('Krew elfów<ll>Andrzej Sapkowski', queue))
            query.assert_called_once()
            # IMP_PREFLANG is Polish, so BN filters on language
            self.assertEqual(query.call_args[0][0],
                             {'author': 'Andrzej Sapkowski', 'title': 'Krew elfów', 'language': 'polski'})
        results = queue.get()
        self.assertEqual(len(results), 2)
        best = max(results, key=lambda r: r['highest_fuzz'])
        self.assertEqual(best['bookid'], 'b0000001011104')
        self.assertEqual(best['source'], 'BN')

    def test_find_results_hyphenated_isbn(self):
        with mock.patch.object(bn.BN, '_execute_query', return_value=(self.records(), False)) as query:
            queue = Queue()
            self.assertTrue(bn.BN().find_results('978-83-7578-063-5', queue))
            self.assertEqual(query.call_args[0][0], {'isbnIssn': '9788375780635'})
        results = {r['bookid']: r for r in queue.get()}
        self.assertEqual(results['b0000005382027']['isbn_fuzz'], 100)

    def test_isbn_forms(self):
        self.assertEqual(bn.BN._isbn_forms('9788385661146'), ['9788385661146', '838566114X'])
        self.assertEqual(bn.BN._isbn_forms('838566114X'), ['838566114X', '9788385661146'])
        self.assertEqual(bn.BN._isbn_forms('9798385661145'), ['9798385661145'])
        # an isbn-13 search also tries the isbn-10 older books are catalogued with
        self.assertEqual(bn.BN()._create_query_variations(isbn='9788385661146'),
                         [{'isbnIssn': '9788385661146'}, {'isbnIssn': '838566114X'}])

    def test_bn_language(self):
        bn_api = bn.BN()
        try:
            for prefs, expected in [('Polish', 'polski'), ('pl, pol, Polish', 'polski'),
                                    ('en, eng, en-US, en-GB, English', 'angielski'),
                                    ('Polish, English', ''), ('All', ''), ('Polish, Unknown', '')]:
                CONFIG.set_csv('IMP_PREFLANG', prefs)
                self.assertEqual(bn_api._bn_language(), expected, prefs)
        finally:
            CONFIG.set_csv('IMP_PREFLANG', 'Polish')

    def test_series_suffix_removed_from_title(self):
        queries = bn.BN()._create_query_variations(authors='Sapkowski', title='Krew elfów (Wiedźmin, #3)')
        self.assertEqual(queries[0], {'author': 'Sapkowski', 'title': 'Krew elfów'})

    @staticmethod
    def series_record(fields):
        return etree.XML(f'''<record xmlns='http://www.loc.gov/MARC21/slim'><leader>01234nam a2200301 i 4500</leader>
          <controlfield tag='001'>b0000001000001</controlfield>
          <datafield ind1='1' ind2=' ' tag='100'><subfield code='a'>Paolini, Christopher</subfield>
            <subfield code='e'>Autor</subfield></datafield>
          <datafield ind1='1' ind2='0' tag='245'><subfield code='a'>Najstarszy /</subfield></datafield>
          {fields}</record>'''.encode())

    def test_parse_series(self):
        bn_api = bn.BN()
        uniform = '''<datafield ind1='1' ind2=' ' tag='800'><subfield code='a'>Paolini, Christopher</subfield>
            <subfield code='t'>Inheritance</subfield><subfield code='v'>ks. 2</subfield></datafield>'''
        for statement, series, index in [
                # Polish name printed in the book
                ("<subfield code='a'>Dziedzictwo / Christopher Paolini ;</subfield><subfield code='v'>ks. 2</subfield>",
                 'Dziedzictwo', '2'),
                # unnumbered variant printed in one edition, use the catalogue's numbered series
                ("<subfield code='a'>Dziedzictwa księga druga / Christopher Paolini</subfield>",
                 'Inheritance', '2'),
                # publisher's series, not the author's
                ("<subfield code='a'>Nowa Fantastyka</subfield>", 'Inheritance', '2')]:
            record = self.series_record(f"<datafield ind1='1' ind2=' ' tag='490'>{statement}</datafield>{uniform}")
            book = bn_api._parse_marc21_record(record)
            self.assertEqual((book['series'], book['series_index']), (series, index), statement)

    def test_multipart_edition_title(self):
        bn_api = bn.BN()
        series = '''<datafield ind1='1' ind2=' ' tag='490'><subfield code='a'>Wiedźmin / Andrzej Sapkowski</subfield></datafield>'''
        # without a part title, $n is a part of the edition, not a series number
        record = self.series_record(series).getroottree().getroot()
        title = record.xpath("./marc21:datafield[@tag='245']", namespaces=bn.BN.NS)[0]
        title[0].text = 'Ostatnie życzenie.'
        title.append(etree.XML("<subfield xmlns='http://www.loc.gov/MARC21/slim' code='n'>Cz. 1 /</subfield>"))
        book = bn_api._parse_marc21_record(record)
        self.assertEqual(book['title'], 'Ostatnie życzenie. Cz. 1')
        self.assertEqual((book['series'], book['series_index']), ('Wiedźmin', None))
        # with a part title, $a is the series and $n the number in it, as in DNB
        title.append(etree.XML("<subfield xmlns='http://www.loc.gov/MARC21/slim' code='p'>Krew elfów</subfield>"))
        title[0].text = 'Saga o wiedźminie.'
        book = bn_api._parse_marc21_record(record)
        self.assertEqual(book['title'], 'Krew elfów')
        self.assertEqual((book['series'], book['series_index']), ('Saga o wiedźminie', '1'))

    def test_book_dict_keeps_series_without_number(self):
        bn_api = bn.BN()
        record = self.series_record(
            "<datafield ind1='1' ind2=' ' tag='490'><subfield code='a'>Świat Dysku / Terry Pratchett</subfield></datafield>")
        book = bn_api._book_dict(bn_api._create_meta_record(bn_api._parse_marc21_record(record), ''))
        self.assertEqual(book['series'], [('Świat Dysku', 'BNb0000001000001', '')])

    def test_title_with_empty_author_is_free_text(self):
        # the api findBook command searches for 'name<ll>'
        with mock.patch.object(bn.BN, '_execute_query', return_value=([], False)) as query:
            bn.BN()._search('Ostatnie życzenie Sapkowski<ll>', limit=100)
            sent = [call[0][0] for call in query.call_args_list]
        self.assertIn({'title': 'Ostatnie życzenie', 'author': 'Sapkowski', 'language': 'polski'}, sent)

    def test_parse_record_writer_credited_as_text(self):
        record = etree.XML('''<record xmlns='http://www.loc.gov/MARC21/slim'><leader>01234nam a2200301 i 4500</leader>
          <controlfield tag='001'>b0000090000211</controlfield>
          <datafield ind1='1' ind2=' ' tag='100'><subfield code='a'>Serkowski, Antoni</subfield>
            <subfield code='e'>Ilustracje</subfield></datafield>
          <datafield ind1='1' ind2='0' tag='245'><subfield code='a'>Niepamięć absolutna /</subfield></datafield>
          <datafield ind1='1' ind2=' ' tag='700'><subfield code='a'>Pitura, Jacek</subfield>
            <subfield code='e'>Tekst</subfield></datafield>
          <datafield ind1='1' ind2=' ' tag='700'><subfield code='a'>Nowak, Jan</subfield>
            <subfield code='e'>Tłumaczenie</subfield></datafield>
        </record>'''.encode())
        self.assertEqual(bn.BN()._parse_marc21_record(record)['authors'], ['Pitura, Jacek'])

    def test_author_results_only_own_books(self):
        bn_api = bn.BN()
        found = [{'authorname': 'Andrzej Sapkowski', 'bookname': 'Krew elfów'},
                 {'authorname': 'Orson Scott Card', 'bookname': 'Siódmy syn'}]

        def fake_find_results(searchterm, queue):
            queue.put(found)
            return True

        with mock.patch.object(bn.BN, 'find_results', side_effect=fake_find_results):
            results = bn_api._author_results('Andrzej Sapkowski')
            self.assertEqual([r['bookname'] for r in results], ['Krew elfów'])
            # names stored without diacritics still match
            found[0]['authorname'] = 'Stanisław Lem'
            self.assertEqual(len(bn_api._author_results('Stanislaw Lem', 'Lem')), 1)
            # 'ł' must become 'l', not disappear
            found[0]['authorname'] = 'Łukasz Orbitowski'
            self.assertEqual(len(bn_api._author_results('Lukasz Orbitowski')), 1)

    def test_find_results_disabled_puts_empty_list(self):
        CONFIG.set_bool('BN_API', False)
        try:
            queue = Queue()
            self.assertFalse(bn.BN().find_results('Krew elfów', queue))
            self.assertEqual(queue.get_nowait(), [])
        finally:
            CONFIG.set_bool('BN_API', True)

    def test_find_results_isbn(self):
        bn_api = bn.BN()
        with mock.patch.object(bn.BN, '_execute_query', return_value=(self.records(), False)) as query:
            queue = Queue()
            self.assertTrue(bn_api.find_results('9788375780635', queue))
            self.assertEqual(query.call_args[0][0], {'isbnIssn': '9788375780635'})
        results = {r['bookid']: r for r in queue.get()}
        self.assertEqual(results['b0000005382027']['isbn_fuzz'], 100)
        self.assertEqual(results['b0000001011104']['isbn_fuzz'], 0)

    def test_free_text_query_variations(self):
        queries = bn.BN()._create_query_variations(title='Najstarszy Paolini')
        self.assertEqual(queries, [{'title': 'Najstarszy Paolini'},
                                   {'title': 'Najstarszy', 'author': 'Paolini'},
                                   {'author': 'Najstarszy', 'title': 'Paolini'},
                                   {'author': 'Najstarszy Paolini'}])
        # long titles are not tried as an author name
        queries = bn.BN()._create_query_variations(title='Pan Tadeusz czyli ostatni zajazd na Litwie')
        self.assertNotIn({'author': 'Pan Tadeusz czyli ostatni zajazd na Litwie'}, queries)
        self.assertIn({'title': 'Pan Tadeusz czyli ostatni zajazd', 'author': 'na Litwie'}, queries)

    def test_free_text_search_merges_variations(self):
        records = self.records()
        # first variation finds a translation only, later ones find the wanted edition again
        responses = [([records[0]], False), ([], False), ([records[0], records[1]], False), ([], False)]
        with mock.patch.object(bn.BN, '_execute_query', side_effect=responses) as query:
            results, _, next_start = bn.BN()._search('Najstarszy Paolini', limit=1)
            self.assertEqual(query.call_count, 4)
        self.assertEqual([r['id'] for r in results], ['b0000001011104', 'b0000005382027'])
        self.assertEqual(next_start, 0)

    def test_title_author_search_stops_at_first_hit(self):
        with mock.patch.object(bn.BN, '_execute_query', return_value=(self.records(), False)) as query:
            bn.BN()._search('Krew elfów<ll>Sapkowski', limit=100)
            query.assert_called_once()

    def test_get_bookdict_for_bookid(self):
        bn_api = bn.BN()
        with mock.patch.object(bn.BN, '_execute_query', return_value=(self.records()[1:2], False)) as query:
            bookdict, _ = bn_api.get_bookdict_for_bookid('b0000005382027')
            self.assertEqual(query.call_args[0][0], {'id': 5382027})
        self.assertEqual(bookdict['bookid'], 'b0000005382027')
        self.assertEqual(bookdict['bookname'], 'Ostatnie życzenie')

    def test_execute_query_uses_fetch_url(self):
        with mock.patch.object(bn, 'fetch_url', return_value=(BN_RESPONSE.encode('utf-8'), True)) as fetch:
            records, cached = bn.BN()._execute_query({'author': 'Sapkowski (fetch test)'})
            fetch.assert_called_once()
            self.assertIn('data.bn.org.pl', fetch.call_args[0][0])
        self.assertEqual(len(records), 3)
        self.assertFalse(cached)

    def test_execute_query_sends_composed_characters(self):
        # LL stores names decomposed, BN only finds the composed form
        name = unicodedata.normalize('NFD', 'Stefan Żeromski (unicode test)')
        with mock.patch.object(bn, 'fetch_url', return_value=(BN_RESPONSE.encode('utf-8'), True)) as fetch:
            bn.BN()._execute_query({'author': name})
            url = fetch.call_args[0][0]
        self.assertIn('Stefan+%C5%BBeromski', url)
        self.assertNotIn('%CC%87', url)

    def test_get_author_books_assigns_refreshed_author(self):
        # BN names the author 'Łukasz Orbitowski', the library has 'Lukasz Orbitowski'
        found = [{'authorname': 'Łukasz Orbitowski', 'authorid': '', 'bookname': 'Szczęśliwa ziemia'}]
        with mock.patch.object(bn.BN, '_author_results', return_value=found), \
                mock.patch.object(bn, 'add_author_books_to_db') as add_books:
            bn.BN().get_author_books(authorid='BN_TEST_AUTHOR', authorname='Lukasz Orbitowski')
            queue = add_books.call_args[0][0]
        book = queue.get()[0]
        self.assertEqual((book['authorid'], book['authorname']), ('BN_TEST_AUTHOR', 'Lukasz Orbitowski'))

    def test_execute_query_rate_limited(self):
        with mock.patch.object(bn, 'fetch_url', return_value=('Response status 429: Too Many Requests', False)), \
                mock.patch.object(bn.BLOCKHANDLER, 'block_provider_backoff') as backoff:
            records, cached = bn.BN()._execute_query({'author': 'Sapkowski (rate limit test)'})
            backoff.assert_called_once()
            self.assertEqual(backoff.call_args[0][0], 'BN')
        self.assertEqual(records, [])

    def test_database_has_bn_id(self):
        db = database.DBConnection()
        try:
            self.assertTrue(has_column(db, 'books', 'bn_id'))
        finally:
            db.close()
