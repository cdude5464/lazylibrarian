#  This file is part of Lazylibrarian.
#
# Purpose:
#   Testing parsing XML from providers

import unittest
from xml.etree import ElementTree

from lazylibrarian.config2 import LLConfigHandler, wishlist_type
from lazylibrarian.configdefs import BASE_DEFAULTS
from lazylibrarian import providers
from unittests.unittesthelpers import LLTestCase


class ProvidersTest(LLTestCase):

    def test_ReturnResultsFieldsBySearchTypeForBook(self):
        book = {"bookid": 'input_bookid', "bookName": 'input_bookname',
                "authorName": 'input_authorname', "searchterm": 'safe_searchterm'}

        newsnabplus_resp = '''<?xml version="1.0" encoding="utf-8"?>
                <rss xmlns:atom="http://www.w3.org/2005/Atom" xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/" version="2.0">
                       <channel>
                              <atom:link href="queryhere" rel="self" type="application/rss+xml"></atom:link>
                              <title>usenet-crawler</title>
                              <description>usenet-crawler Feed</description>
                              <link>https://www.usenet-crawler.com/</link>
                              <language>en-gb</language>
                              <webMaster>info@usenet-crawler.com (usenet-crawler)</webMaster>
                              <category></category>
                              <image>
                                     <url>https://www.usenet-crawler.com/templates/default/images/banner.jpg</url>
                                     <title>usenet-crawler</title>
                                     <link>https://www.usenet-crawler.com/</link>
                                     <description>Visit usenet-crawler - A quick usenet indexer</description>
                                 </image>
                              <newznab:response offset="0" total="3292"></newznab:response>
                              <item>
                                     <title>Debbie Macomber - When First They Met (html)</title>
                                     <guid isPermaLink="true">https://www.usenet-crawler.com/details/1c055031d3b32be8e2b9eaee1e33c315</guid>
                                     <link>http</link>
                                     <comments>https://www.usenet-crawler.com/details/1c055031d3b32be8e2b9eaee1e33c315#comments</comments>
                                     <pubDate>Sat, 02 Mar 2013 06:51:28 +0100</pubDate>
                                     <category>Books > Ebook</category>
                                     <description>Debbie Macomber - When First They Met (html)</description>
                                     <enclosure url="http" length="192447" type="application/x-nzb"></enclosure>
                                     <newznab:attr name="category" value="7000"></newznab:attr>
                                     <newznab:attr name="category" value="7020"></newznab:attr>
                                     <newznab:attr name="size" value="192447"></newznab:attr>
                                     <newznab:attr name="guid" value="1c055031d3b32be8e2b9eaee1e33c315"></newznab:attr>
                                 </item>
                          </channel>
                   </rss>                '''
        resultxml = ElementTree.fromstring(newsnabplus_resp)
        nzb = list(resultxml.findall("./channel/item//"))

        result = providers.return_results_by_search_type(book, nzb, search_mode='book', host='hostname')
        self.assertDictEqual({'bookid': 'input_bookid', 'nzbdate': 'Sat, 02 Mar 2013 06:51:28 +0100', 'nzbtitle':
                          'Debbie Macomber - When First They Met (html)', 'nzbsize': '192447', 'nzburl': 'http',
                          'nzbprov': 'hostname', 'nzbmode': 'book', 'priority': 0, 'prov_page': 'https://www.usenet-crawler.com/details/1c055031d3b32be8e2b9eaee1e33c315#comments'}, result)

    def test_ReturnResultsFieldsBySearchTypeForMag(self):
        book = {"bookid": 'input_bookid', "bookName": 'input_bookname',
                "authorName": 'input_authorname', "searchterm": 'safe_searchterm'}

        newsnabplus_resp = '''<?xml version="1.0" encoding="utf-8" ?>
            <rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/">
                <channel>
                    <atom:link href="https://www.usenet-crawler.com/api?q=scientific+american&amp;apikey=78c0509bc6bb91742ae0a0b6231e75e4&amp;t=search&amp;extended=1&amp;cat=7020" rel="self" type="application/rss+xml" />
                    <title>usenet-crawler</title>
                    <description>usenet-crawler Feed</description>
                    <link>https://www.usenet-crawler.com/</link>
                    <language>en-gb</language>
                    <webMaster>info@usenet-crawler.com (usenet-crawler)</webMaster>
                    <category></category>
                    <image>
                        <url>https://www.usenet-crawler.com/templates/default/images/banner.jpg</url>
                        <title>usenet-crawler</title>
                        <link>https://www.usenet-crawler.com/</link>
                        <description>Visit usenet-crawler - A quick usenet indexer</description>
                    </image>

                    <newznab:response offset="0" total="3292" />
                    <item>
                        <title>Scientific.American.SCIAM.November.20.3</title>
                        <guid isPermaLink="true">https://www.usenet-crawler.com/details/6814309804e3648c58a9f23345c2a28a</guid>
                        <link>https://www.usenet-crawler.com/getnzb/6814309804e3648c58a9f23345c2a28a.nzb&amp;i=155518&amp;r=78c0509bc6bb91742ae0a0b6231e75e4</link>
                        <comments>https://www.usenet-crawler.com/details/6814309804e3648c58a9f23345c2a28a#comments</comments>
                        <pubDate>Thu, 21 Nov 2013 16:13:52 +0100</pubDate>
                        <category>Books &gt; Ebook</category>
                        <description>Scientific.American.SCIAM.November.20.3</description>
                        <enclosure url="https://www.usenet-crawler.com/getnzb/6814309804e3648c58a9f23345c2a28a.nzb&amp;i=155518&amp;r=78c0509bc6bb91742ae0a0b6231e75e4" length="20811405" type="application/x-nzb" />

                        <newznab:attr name="category" value="7000" />
                        <newznab:attr name="category" value="7020" />
                        <newznab:attr name="size" value="20811405" />
                        <newznab:attr name="guid" value="6814309804e3648c58a9f23345c2a28a" />
                        <newznab:attr name="files" value="4" />
                        <newznab:attr name="poster" value="TROLL &lt;EBOOKS@town.ag&gt;" />

                        <newznab:attr name="grabs" value="10" />
                        <newznab:attr name="comments" value="0" />
                        <newznab:attr name="password" value="0" />
                        <newznab:attr name="usenetdate" value="Thu, 21 Nov 2013 12:13:01 +0100" />
                        <newznab:attr name="group" value="alt.binaries.ebook" />
                    </item>
                </channel>
            </rss>                '''
        # Take the above xml, parse it into element tree, extract the item from it
        # could have just put in item text, but took live example
        resultxml = ElementTree.fromstring(newsnabplus_resp)
        nzb = list(resultxml.findall("./channel/item//"))
        result = providers.return_results_by_search_type(book, nzb, 'hostname', 'mag')
        self.assertDictEqual(
            {'bookid': 'input_bookid', 'nzbdate': 'Thu, 21 Nov 2013 16:13:52 +0100',
             'nzbtitle': 'Scientific.American.SCIAM.November.20.3', 'nzbsize': '20811405',
             'nzburl': 'https://www.usenet-crawler.com/getnzb/6814309804e3648c58a9f23345c2a28a.nzb&i=155518&r=78c0509bc6bb91742ae0a0b6231e75e4',
             'nzbprov': 'hostname', 'nzbmode': 'mag', 'priority': 0, 'prov_page': 'https://www.usenet-crawler.com/details/6814309804e3648c58a9f23345c2a28a#comments'}, result)

    def test_ReturnResultsFieldsBySearchTypeForGeneral(self):
        book = {"bookid": 'input_bookid', "bookName": 'input_bookname',
                "authorName": 'input_authorname', "searchterm": 'safe_searchterm'}

        newsnabplus_resp = '''<?xml version="1.0" encoding="utf-8" ?>
            <rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/">
                <channel>
                    <atom:link href="https://www.usenet-crawler.com/api?q=scientific+american&amp;apikey=78c0509bc6bb91742ae0a0b6231e75e4&amp;t=search&amp;extended=1&amp;cat=7020" rel="self" type="application/rss+xml" />
                    <title>usenet-crawler</title>
                    <description>usenet-crawler Feed</description>
                    <link>https://www.usenet-crawler.com/</link>
                    <language>en-gb</language>
                    <webMaster>info@usenet-crawler.com (usenet-crawler)</webMaster>
                    <category></category>
                    <image>
                        <url>https://www.usenet-crawler.com/templates/default/images/banner.jpg</url>
                        <title>usenet-crawler</title>
                        <link>https://www.usenet-crawler.com/</link>
                        <description>Visit usenet-crawler - A quick usenet indexer</description>
                    </image>

                    <newznab:response offset="0" total="3292" />
                    <item>
                        <title>Scientific.American.SCIAM.November.20.3</title>
                        <guid isPermaLink="true">https://www.usenet-crawler.com/details/6814309804e3648c58a9f23345c2a28a</guid>
                        <link>https://www.usenet-crawler.com/getnzb/6814309804e3648c58a9f23345c2a28a.nzb&amp;i=155518&amp;r=78c0509bc6bb91742ae0a0b6231e75e4</link>
                        <comments>https://www.usenet-crawler.com/details/6814309804e3648c58a9f23345c2a28a#comments</comments>
                        <pubDate>Thu, 21 Nov 2013 16:13:52 +0100</pubDate>
                        <category>Books &gt; Ebook</category>
                        <description>Scientific.American.SCIAM.November.20.3</description>
                        <enclosure url="https://www.usenet-crawler.com/getnzb/6814309804e3648c58a9f23345c2a28a.nzb&amp;i=155518&amp;r=78c0509bc6bb91742ae0a0b6231e75e4" length="20811405" type="application/x-nzb" />

                        <newznab:attr name="category" value="7000" />
                        <newznab:attr name="category" value="7020" />
                        <newznab:attr name="size" value="20811405" />
                        <newznab:attr name="guid" value="6814309804e3648c58a9f23345c2a28a" />
                        <newznab:attr name="files" value="4" />
                        <newznab:attr name="poster" value="TROLL &lt;EBOOKS@town.ag&gt;" />

                        <newznab:attr name="grabs" value="10" />
                        <newznab:attr name="comments" value="0" />
                        <newznab:attr name="password" value="0" />
                        <newznab:attr name="usenetdate" value="Thu, 21 Nov 2013 12:13:01 +0100" />
                        <newznab:attr name="group" value="alt.binaries.ebook" />
                    </item>
                </channel>
            </rss>                '''
        # Take the above xml, parse it into element tree, extract the item from it
        # could have just put in item text, but took live example
        resultxml = ElementTree.fromstring(newsnabplus_resp)
        nzb = list(resultxml.findall("./channel/item//"))
        result = providers.return_results_by_search_type(book, nzb, 'hostname', None)
        self.assertDictEqual(
            {'bookid': 'input_bookid', 'nzbdate': 'Thu, 21 Nov 2013 16:13:52 +0100',
             'nzbtitle': 'Scientific.American.SCIAM.November.20.3', 'nzbsize': '20811405',
             'nzburl': 'https://www.usenet-crawler.com/getnzb/6814309804e3648c58a9f23345c2a28a.nzb&i=155518&r=78c0509bc6bb91742ae0a0b6231e75e4',
             'nzbprov': 'hostname', 'nzbmode': None, 'priority': 0, 'prov_page': 'https://www.usenet-crawler.com/details/6814309804e3648c58a9f23345c2a28a#comments'}, result)

    def test_titlebook_search_is_title_only(self):
        book = {'bookid': '1', 'bookName': 'Sample Title', 'bookSub': '',
                'authorName': 'A.B. Sample Author', 'searchterm': 'A.B. Sample Author Sample Title'}
        provider = LLConfigHandler(defaults=BASE_DEFAULTS, configfile=self.COMPLEX_INI_FILE).providers('TORZNAB')[0]
        provider['GENERALSEARCH'] = 'search'
        provider['BOOKCAT'] = '7020'

        provider['BOOKSEARCH'] = ''
        params = providers.return_search_structure(provider, 'key', book, 'book', 'nzb')
        self.assertEqual(params['q'], b'Sample Author Sample Title')
        params = providers.return_search_structure(provider, 'key', book, 'titlebook', 'nzb')
        self.assertEqual(params['q'], b'Sample Title')
        self.assertEqual(params['cat'], '7020')

        provider['BOOKSEARCH'] = 'book'
        params = providers.return_search_structure(provider, 'key', book, 'book', 'nzb')
        self.assertEqual(params['author'], b'Sample Author')
        params = providers.return_search_structure(provider, 'key', book, 'titlebook', 'nzb')
        self.assertNotIn('author', params)
        self.assertEqual(params['title'], b'Sample Title')

    def test_wishlist_type(self):
        provs = [
            ('https://www.goodreads.com/review/list_rss/userid', 'goodreads'),
            ('https://www.goodreads.com/review/list/12345678-jane-doe?shelf=to-read', 'goodreads'),
            ('https://www.goodreads.com/list/show/143500.Best_Books_of_the_Decade_2020_s', 'listopia'),
            ('https://www.goodreads.com/book/show/title', 'listopia'),
            ('https://www.amazon.co.uk/charts', 'amazon'),
            ('https://www.nytimes.com/books/best-sellers/', 'ny_times'),
            ('https://best-books.publishersweekly.com/pw/best-books/2022/top-10', 'publishersweekly'),
            ('https://apps.npr.org/best-books/#year=2022', 'apps.npr.org'),
            ('https://www.penguinrandomhouse.com/books/all-best-sellers', 'penguinrandomhouse'),
            ('https://www.barnesandnoble.com/b/books/_/N-1fZ29Z8q8', 'barnesandnoble'),
            ('https://somewhere-else.com/', '')
        ]
        for p in provs:
            self.assertEqual(wishlist_type(p[0]), p[1])

    # Same markup as the Goodreads bookshelf widget, with made up books
    GR_WIDGET = r"""  var widget_code = '  <div class=\"gr_custom_container_ll1\">\n    <h2 class=\"gr_custom_header_ll1\">\n    <a style=\"text-decoration: none;\" rel=\"nofollow\" href=\"https://www.goodreads.com/review/list/1-jane-doe?shelf=to-read&amp;utm_medium=api&amp;utm_source=custom_widget\">Jane&#39;s books<\/a>\n    <\/h2>\n      <div class=\"gr_custom_each_container_ll1\">\n          <div class=\"gr_custom_book_container_ll1\">\n            <a title=\"The Example Book (Example Series #3)\" rel=\"nofollow\" href=\"https://www.goodreads.com/review/show/1000000001?utm_medium=api&amp;utm_source=custom_widget\"><img alt=\"The Example Book\" border=\"0\" src=\"https://i.gr-assets.com/images/S/compressed.photo.goodreads.com/books/1700000000l/87654321._SY75_.jpg\" /><\/a>\n          <\/div>\n          <div class=\"gr_custom_title_ll1\">\n            <a rel=\"nofollow\" href=\"https://www.goodreads.com/review/show/1000000001\">The Example Book<\/a>\n          <\/div>\n          <div class=\"gr_custom_author_ll1\">\n            by <a rel=\"nofollow\" href=\"https://www.goodreads.com/author/show/1000.Ann_Author\">Ann Author<\/a>\n          <\/div>\n      <\/div>\n      <div class=\"gr_custom_each_container_ll1\">\n          <div class=\"gr_custom_book_container_ll1\">\n            <a title=\"Don&#39;t Look Back &amp; Other Stories\" rel=\"nofollow\" href=\"https://www.goodreads.com/review/show/123\"><img alt=\"x\" border=\"0\" src=\"https://s.gr-assets.com/assets/nophoto/book/50x75-a91bf249278a81aabab721ef782c4a74.png\" /><\/a>\n          <\/div>\n          <div class=\"gr_custom_author_ll1\">\n            by <a rel=\"nofollow\" href=\"https://www.goodreads.com/author/show/1.A_B\">A.B. Writer<\/a>\n          <\/div>\n      <\/div>\n  <\/div>\n'
  var widget_div = document.getElementById('gr_custom_widget_ll1')
"""

    def test_goodreads_widget_url(self):
        url, user_id, shelf = providers.goodreads_widget_url(
            'https://www.goodreads.com/review/list_rss/12345678?key=KEY&shelf=to-read', 'll1')
        self.assertEqual('https://www.goodreads.com/review/custom_widget/12345678?shelf=to-read&num_books=100'
                         '&sort=date_added&order=d&show_author=1&show_cover=1&show_title=1&widget_id=ll1', url)
        self.assertEqual(('12345678', 'to-read'), (user_id, shelf))
        # a shelf page url, without the scheme
        url, user_id, shelf = providers.goodreads_widget_url(
            'www.goodreads.com/review/list/12345678-jane-doe?shelf=my%20audio', 'll1')
        self.assertTrue(url.startswith('https://www.goodreads.com/review/custom_widget/12345678?shelf=my+audio&'))
        self.assertEqual('my audio', shelf)
        # the widget can't give all books, or a group bookshelf
        for host in ['https://www.goodreads.com/review/list_rss/12345678',
                     'https://www.goodreads.com/review/list_rss/12345678?shelf=%23ALL%23',
                     'https://www.goodreads.com/group/bookshelf/1.rss',
                     'https://www.goodreads.com/review/list_rss/userid?shelf=to-read']:
            with self.assertRaises(ValueError):
                providers.goodreads_widget_url(host, 'll1')

    def test_parse_goodreads_widget(self):
        books = providers.parse_goodreads_widget(self.GR_WIDGET, 'to-read')
        self.assertEqual([
            {'title': 'The Example Book (Example Series #3)', 'author': 'Ann Author', 'bookid': '87654321'},
            # no cover, so no book id
            {'title': "Don't Look Back & Other Stories", 'author': 'A.B. Writer', 'bookid': ''},
        ], books)
        # the widget of another shelf
        with self.assertRaises(ValueError):
            providers.parse_goodreads_widget(self.GR_WIDGET, 'read')
        # an unknown user
        with self.assertRaises(ValueError):
            providers.parse_goodreads_widget(
                "  var widget_code = '  This Goodreads widget is not correct.\\n'\n", 'to-read')

    def test_unescape_js_string(self):
        bs = chr(92)
        self.assertEqual('a"b</a>\n', providers.unescape_js_string(f'a{bs}"b<{bs}/a>{bs}n\' rest'))
        # unicode escapes, also a surrogate pair
        self.assertEqual(chr(0x10C) + chr(0x1F600), providers.unescape_js_string(
            f"{bs}u010c{bs}ud83d{bs}ude00'"))
        with self.assertRaises(ValueError):
            providers.unescape_js_string('no closing quote')


if __name__ == '__main__':
    unittest.main()
