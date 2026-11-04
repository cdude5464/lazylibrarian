#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test the category detection in providers.get_capabilities()
#
#   Regression: get_capabilities() reset the *CAT settings to the provider-type default
#   (Torznab: 8000,8010 = "Other") before parsing the caps, but the parser only fills a
#   category when it is empty, so an indexer offering plain "Books" (7000) with no ebook
#   subcategory was left searching the wrong category. See commit 69d93bee.

from unittest import mock

from unittests.unittesthelpers import LLTestCase
from lazylibrarian.config2 import LLConfigHandler
from lazylibrarian.configdefs import BASE_DEFAULTS
from lazylibrarian.providers import get_capabilities

CAPS_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<caps>
  <server title="Prowlarr"/>
  <searching>
    <search available="yes" supportedParams="q"/>
    <book-search available="no" supportedParams="q"/>
  </searching>
  <categories>
    {categories}
    <category id="8000" name="Other"/>
  </categories>
</caps>"""

BOOKS_ONLY = '<category id="7000" name="Books"/>'
BOOKS_AND_AUDIOBOOKS = ('<category id="3000" name="Audio"><subcat id="3030" name="Audio/Audiobook"/></category>'
                        '<category id="7000" name="Books"/>')
EBOOK_SUBCAT_AND_AUDIOBOOKS = ('<category id="3000" name="Audio"><subcat id="3030" name="Audio/Audiobook"/></category>'
                               '<category id="7000" name="Books"><subcat id="7020" name="Books/EBook"/></category>')
AUDIO_WITHOUT_AUDIOBOOK_SUBCAT = ('<category id="3000" name="Audio"><subcat id="3010" name="Audio/MP3"/></category>'
                                  '<category id="7000" name="Books"><subcat id="7020" name="Books/EBook"/></category>')


class ProvidersCapsTest(LLTestCase):

    def _caps_for(self, categories: str):
        cfg = LLConfigHandler(defaults=BASE_DEFAULTS, configfile=self.COMPLEX_INI_FILE)
        provider = cfg.providers('TORZNAB')[0]
        provider['HOST'] = 'http://prowlarr.invalid:9696/1/api'
        xml = CAPS_TEMPLATE.format(categories=categories).encode()
        with mock.patch('lazylibrarian.providers.fetch_url', return_value=(xml, True)):
            get_capabilities(provider, force=True)
        return provider

    def test_books_without_ebook_subcategory_uses_books_category(self):
        provider = self._caps_for(BOOKS_ONLY)
        # was '8000,8010' ("Other") before the fix
        self.assertEqual(provider['BOOKCAT'], '7000')
        # no book-specific magazine/comic subcategory: falls back to Books, as documented in the parser
        self.assertEqual(provider['MAGCAT'], '7000')
        self.assertEqual(provider['COMICCAT'], '7000')

    def test_indexer_without_audio_category_has_no_audiocat(self):
        provider = self._caps_for(BOOKS_ONLY)
        # was '3030' (the type default) before the fix, so audiobook searches were sent to an
        # indexer that has no audio category at all
        self.assertEqual(provider['AUDIOCAT'], '')

    def test_ebook_and_audiobook_subcategories_are_used(self):
        provider = self._caps_for(EBOOK_SUBCAT_AND_AUDIOBOOKS)
        self.assertEqual(provider['BOOKCAT'], '7020')
        self.assertEqual(provider['AUDIOCAT'], '3030')

    def test_audio_without_audiobook_subcategory_uses_top_level_audio(self):
        provider = self._caps_for(AUDIO_WITHOUT_AUDIOBOOK_SUBCAT)
        self.assertEqual(provider['BOOKCAT'], '7020')
        self.assertEqual(provider['AUDIOCAT'], '3000')

    def test_books_and_audiobooks_without_ebook_subcategory(self):
        provider = self._caps_for(BOOKS_AND_AUDIOBOOKS)
        self.assertEqual(provider['BOOKCAT'], '7000')
        self.assertEqual(provider['AUDIOCAT'], '3030')
