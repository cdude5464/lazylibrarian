"""Exercise provider-qualified statuses and submitted payloads in both skins."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from mako.template import Template


class SearchResultTemplateTest(unittest.TestCase):
    @staticmethod
    def render(skin, definition, results):
        path = Path(__file__).parents[1] / 'data' / 'interfaces' / skin / 'searchresults.html'
        source = re.sub(r'<%inherit[^>]+/>', '', path.read_text())
        values = dict(searchresults=results, authorlist=[], loadlist=[], booklist=['123'],
                      booksearch=[dict(BookID='123', Status='Have', AudioStatus='Have')],
                      title='Results', perm=65535, _=lambda value: value, js=json.dumps,
                      _js=json.dumps, _jsn=lambda single, plural: json.dumps([single, plural]))
        with patch('lazylibrarian.config2.CONFIG.get_int', return_value=1):
            return Template(source).get_def(definition).render(**values)

    @staticmethod
    def result(source='GoodReads', title='Novel', author='Writer', status=None):
        return dict(bookid='123', bookname=title, authorid='author', authorname=author,
                    source=source, bookrate=0, bookrate_count=0, highest_fuzz=100,
                    bookimg='', booklink='', bookdate='', library_book=status)

    def test_both_skins_preserve_source_context_and_canonical_format_status(self):
        known = self.result(status=dict(BookID='canonical', Status='Have', AudioStatus='Wanted'))
        unknown = self.result('GoogleBooks', title='Other Novel', author='Other Writer')
        modern = self.render('modern', 'body', [known, unknown])
        rows = json.loads(re.search(r'var llSearchRows = (.*);', modern).group(1))
        self.assertEqual(rows[0]['ebook'], ['status', 'Have', ''])
        self.assertEqual(parse_qs(urlsplit(rows[0]['audio'][2]).query)['bookid'], ['canonical'])
        params = parse_qs(urlsplit(rows[1]['ebook'][2]).query)
        self.assertEqual(params['source'], ['GoogleBooks'])
        self.assertEqual(params['title'], ['Other Novel'])
        self.assertEqual(params['authorname'], ['Other Writer'])
        classic = self.render('bookstrap', 'body', [known, unknown])
        self.assertIn('bookid=canonical', classic)
        self.assertIn('title=Other+Novel', classic)
        self.assertIn('source=GoogleBooks', classic)

    @unittest.skipUnless(shutil.which('node'), 'Node is required to execute the rendered bulk-selection flow')
    def test_modern_bulk_preserves_only_selected_source_and_refuses_id_collision(self):
        script = self.render('modern', 'javascriptIncludes', [])
        script = script.split('<script>', 1)[1].rsplit('</script>', 1)[0]
        rows = [dict(id='123', source='GoodReads', aid='a', title='Novel', author='Writer',
                     date='', rate=0, count=0, author_act=None, ebook=None, audio=None),
                dict(id='123', source='GoogleBooks', aid='b', title='Other', author='Other Writer',
                     date='', rate=0, count=0, author_act=None, ebook=None, audio=None)]
        harness = """
const assert = require('node:assert/strict');
let create, sent = [];
global.document = {addEventListener: (_event, fn) => fn()};
global.Alpine = {data: (_name, fn) => { create = fn; }};
global.window = {llSearchRows: ROWS};
global.fetch = (_url, options) => { sent.push(options.body); return new Promise(() => {}); };
global.llStatus = value => value;
SCRIPT
let app = create();
app.modalEl = () => ({show() {}});
app.toast = message => { app.message = message; };
app.toggle(app.all[0]);
assert.equal(Object.keys(app.sel).length, 1);
app.bulk('AddBook');
assert.equal(sent.length, 1);
assert.equal(sent[0].get('123'), 'a|Writer|Novel|GoodReads');
app.toggle(app.all[1]);
assert.equal(Object.keys(app.sel).length, 2);
app.bulk('AddBook');
assert.equal(sent.length, 1);
assert.match(app.message, /one metadata source/);
""".replace('ROWS', json.dumps(rows)).replace('SCRIPT', script)
        completed = subprocess.run(['node', '-e', harness], capture_output=True, text=True, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr)
