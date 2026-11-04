from unittest import TestCase
from unittest.mock import Mock, patch
from lazylibrarian import resultlist

class UpstreamLanguageGuardTest(TestCase):
    def expected(self, config, row=None, book=None):
        with patch.object(resultlist, 'CONFIG', config):
            return resultlist._expected_book_language(Mock(match=Mock(return_value=row)), book or {'bookid':'42'})

    def test_automatic_uses_all_import_languages(self):
        for automatic in ('', 'auto'):
            value=self.expected({'ANNA_SEARCH_LANG':automatic,'IMP_PREFLANG':'eng,deu'})
            self.assertFalse(resultlist._ebook_result_language_mismatch('en-US',value))
            self.assertFalse(resultlist._ebook_result_language_mismatch('de',value))
            self.assertTrue(resultlist._ebook_result_language_mismatch('es',value))

    def test_explicit_multi_search_languages_preserved(self):
        value=self.expected({'ANNA_SEARCH_LANG':'en,de','IMP_PREFLANG':'es'})
        self.assertFalse(resultlist._ebook_result_language_mismatch('de',value))
        self.assertTrue(resultlist._ebook_result_language_mismatch('es',value))

    def test_explicit_book_language_overrides_search_preference(self):
        value=self.expected({'ANNA_SEARCH_LANG':'en,de'},row={'BookLang':'es'})
        self.assertTrue(resultlist._ebook_result_language_mismatch('de',value))
        self.assertFalse(resultlist._ebook_result_language_mismatch('spa',value))

    def test_unknown_book_and_any_remain_unconstrained(self):
        self.assertFalse(resultlist._ebook_result_language_mismatch('en',self.expected({'ANNA_SEARCH_LANG':'es'},row={'BookLang':'Unknown'})))
        self.assertFalse(resultlist._ebook_result_language_mismatch('de',self.expected({'ANNA_SEARCH_LANG':'ANY'})))
