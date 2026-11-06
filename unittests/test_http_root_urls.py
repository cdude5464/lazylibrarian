"""Regression coverage for subfolder URLs after the upstream base-tag change."""
from configparser import ConfigParser
from pathlib import Path
from unittest import TestCase
from urllib.parse import urljoin

from mako.template import Template

from lazylibrarian.config2 import LLConfigHandler
from lazylibrarian.configdefs import BASE_DEFAULTS, configitem_from_default
from lazylibrarian.configtypes import ConfigHTTPRoot


class HTTPRootURLsTest(TestCase):
    def test_load_edit_and_persist_share_canonical_prefix(self):
        definition = next(item for item in BASE_DEFAULTS if item.key == 'HTTP_ROOT')
        cases = {'': '', '/': '', 'books': '/books', '/books': '/books',
                 '/books/': '/books', 'nested/books/': '/nested/books',
                 ' /nested/books/ ': '/nested/books'}
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                item = configitem_from_default(definition)
                parser = ConfigParser()
                parser['WEBSERVER'] = {'http_root': raw}
                self.assertTrue(item.update_from_parser(parser, 'WEBSERVER', 'http_root'))
                self.assertEqual(item.get_str(), expected)
                self.assertEqual(item.get_save_str(), expected)
                item.set_from_ui("different/path/")
                self.assertEqual(item.get_str(), "/different/path")
                item.set_from_ui(raw)
                self.assertEqual(item.get_str(), expected)
                config = LLConfigHandler(defaults=[definition])
                config["HTTP_ROOT"] = raw
                self.assertEqual(config["HTTP_ROOT"], expected)
                self.assertEqual(ConfigHTTPRoot('WebServer', 'HTTP_ROOT', raw).get_str(), expected)

    def test_template_base_resolves_assets_and_navigation_under_mount(self):
        source = (Path(__file__).resolve().parents[1] / 'data/interfaces/bookstrap/base.html').read_text()
        base_tag = next(line.strip() for line in source.splitlines() if '<base href=' in line)
        for raw in ('', '/', 'books', '/books/', 'nested/books/'):
            with self.subTest(raw=raw):
                root = ConfigHTTPRoot('WebServer', 'HTTP_ROOT', raw).get_str()
                rendered = Template(base_tag).render(CONFIG={'HTTP_ROOT': root})
                base = rendered.split('href="', 1)[1].split('"', 1)[0]
                for page in ('authors', 'home', 'authorPage?AuthorID=123'):
                    base_url = urljoin(f'https://example.invalid{root}/{page}', base)
                    for asset in ('js/lazylibrarian-bs.js', 'css/bookstrap.css', 'get_index', 'home'):
                        self.assertEqual(urljoin(base_url, asset), f'https://example.invalid{root}/{asset}')
