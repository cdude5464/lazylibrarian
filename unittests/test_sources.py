#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test the registry of direct providers

import unittest

from lazylibrarian.sources import registry
from lazylibrarian.sources.registry import DirectProvider, skip_reason


def _search(book, search_type):
    return [], ''


class SourcesTest(unittest.TestCase):

    def test_builtin_providers(self):
        keys = [p.key for p in registry.direct_providers()]
        self.assertEqual(keys, ['BOK', 'SLSK', 'ANNA', 'WEBSHARE', 'MLP'])
        names = [p.name for p in registry.direct_providers()]
        self.assertEqual(len(names), len(set(names)))

    def test_lookup(self):
        self.assertEqual(registry.direct_provider('mlp').key, 'MLP')
        self.assertEqual(registry.direct_provider('ANNA').name, 'annas')
        self.assertIsNone(registry.direct_provider('nosuch'))

    def test_duplicate_key(self):
        registry.direct_providers()
        with self.assertRaises(ValueError):
            registry.register_direct_provider(DirectProvider(key='MLP', name='other', label='x', search=_search))
        with self.assertRaises(ValueError):
            registry.register_direct_provider(DirectProvider(key='OTHER', name='mlp', label='x', search=_search))

    def test_search_kind(self):
        for search_type, kind in [('book', 'E'), ('shortbook', 'E'), ('titlebook', 'E'), ('audio', 'A'),
                                  ('shortaudio', 'A'), ('mag', 'M'), ('comic', 'C'), ('general', '')]:
            self.assertEqual(registry.search_kind(search_type), kind, search_type)

    def test_media_type(self):
        for search_type, media in [('book', 'ebook'), ('audio', 'audio'), ('mag', 'mag'), ('comic', 'ebook')]:
            self.assertEqual(registry.media_type(search_type), media, search_type)

    def test_skip_reason(self):
        anna = registry.direct_provider('ANNA')
        self.assertEqual(skip_reason(anna, 'book', 'E'), '')
        self.assertTrue(skip_reason(anna, 'audio', 'E'))
        self.assertEqual(skip_reason(anna, 'general', ''), '')
        # webshare never has comics, whatever DLTYPES says
        webshare = registry.direct_provider('WEBSHARE')
        self.assertTrue(skip_reason(webshare, 'comic', 'EAMC'))
        self.assertEqual(skip_reason(webshare, 'mag', 'M'), '')
        # mlp only has ebooks, and is not used for general searches
        mlp = registry.direct_provider('MLP')
        self.assertEqual(skip_reason(mlp, 'titlebook', 'E'), '')
        self.assertTrue(skip_reason(mlp, 'audio', 'EA'))
        self.assertTrue(skip_reason(mlp, 'general', 'E'))

    def test_flags(self):
        self.assertEqual([p.name for p in registry.direct_providers() if p.download_dir],
                         ['zlibrary', 'annas', 'webshare', 'mlp'])
        self.assertEqual([p.name for p in registry.direct_providers() if p.result_title],
                         ['soulseek', 'annas', 'webshare', 'mlp'])
        self.assertEqual([p.usage_key for p in registry.direct_providers()],
                         ['BOK', 'soulseek', 'annas', 'WEBSHARE', 'MLP'])


if __name__ == '__main__':
    unittest.main()
