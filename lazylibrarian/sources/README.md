# Sources: the registry of direct providers

A *direct provider* is a site LazyLibrarian searches and downloads a file from itself, with no downloader
(SABnzbd, qBittorrent, ...) in between. Z-Library, Soulseek, Anna's Archive, Webshare and the Prague City
Library (MLP) are direct providers.

Each one is described by a `DirectProvider` in a module of this package. The rest of the program asks the
registry (`registry.py`) instead of keeping a list of providers in every module, so **a new direct provider is
one new file** here plus the code that talks to the site.

Everything in the package is imported by `load_sources()`: any module in this directory is picked up, there is
no list to edit. A module that fails to import is logged (`Failed to load source ...`) and skipped, so the
others keep working, but its config items are then missing too.

## What the registry drives

| Where | What it takes from the registry |
|---|---|
| `providers.iterate_over_direct_sites` | the providers to search, in `order`, and what each one does with an error |
| `configdefs.py` | the config items, see [Config items](#config-items) |
| `resultlist.find_best_result` | `valid_url`, to reject a result with a bad url |
| `downloadmethods.direct_dl_method` | `download`, for a provider that has one |
| `providers.test_provider` | `test`, for the Test button |
| `postprocess` | `download_dir`, where the downloaded file is looked for |
| `telemetry` | `usage_key`, the usage switches |
| `webServe` | `label` and `result_title` (names in the history, blocklist cards, the snatched file name) |
| `setupwizard` | `wizard`, `wizard_order` and `recommended` |
| bookstrap config page | `page`, see [Config page](#config-page) |

## Adding a provider

1. Write the code that searches and downloads, like `lazylibrarian/mlp.py` (search) and
   `lazylibrarian/webshare.py`.
2. Add `lazylibrarian/sources/<name>.py` that calls `register_direct_provider(DirectProvider(...))`.
3. Add the user visible strings to the translations the usual way, see `lazylibrarian/locale/README.md`.
   Do not edit the `.po` files in a merge request.

Keep the module light. Import the provider code inside the functions, not at the top, so a provider that is
switched off is never imported. Imports of `lazylibrarian.configtypes`, `lazylibrarian.i18n` and the registry
are fine at the top.

```python
from lazylibrarian.configtypes import ConfigStr
from lazylibrarian.i18n import N_
from lazylibrarian.sources.registry import (
    DirectProvider, PageField, ProviderPage, media_type, register_direct_provider,
)


def search(book, search_type):
    from lazylibrarian.example import example_search
    return example_search(book, media_type(search_type))


def test(book, host, api):
    from lazylibrarian.example import example_search
    return example_search(book, test=True)


register_direct_provider(DirectProvider(
    key='EXAMPLE', name='example', label='Example Library', search=search, test=test,
    types='E', general=False, result_title=True, order=60,
    config=(ConfigStr('EXAMPLE', 'EXAMPLE_HOST', 'https://example.org'),),
    page=ProviderPage(N_('Example Library'), (PageField('HOST', placeholder=N_('Example host')),)),
    wizard=(N_('Example Library'), N_('Free e-books, no login needed.')),
    wizard_order=60, recommended=('CZ',)))
```

## `DirectProvider`

| Field | Meaning |
|---|---|
| `key` | config prefix, upper case. `MLP` gives the items `MLP`, `MLP_DLPRIORITY`, `MLP_DLTYPES` |
| `name` | internal name, lower case, used in the blocklist, the `wanted` table and `provider=` in the urls. Must be unique |
| `label` | name shown to the user, eg in the Test result |
| `search` | `search(book, search_type) -> (results, error)`, see [Search](#search) |
| `types` | the kinds of item the site has at all: letters of `E`ebook, `A`udiobook, `M`agazine, `C`omic. What the user sets in `<KEY>_DLTYPES` is limited to this |
| `general` | also used by general searches, which have no kind of item. `False` for a site that cannot search without a book |
| `on_error` | `on_error(provider, error)`. Default: block the provider for `BLOCKLIST_TIMER` |
| `download_dir` | downloads into the first download directory. `False` when the file lands somewhere else, as with Soulseek |
| `result_title` | the snatched file is named by the title of the result, not by the book |
| `telemetry` | usage key, `Query/<telemetry>`. Default the config key |
| `order` | search order, lowest first |
| `valid_url` | `valid_url(url) -> bool`. A result whose url fails is rejected. Always give one for a provider that downloads from a url |
| `download` | `download(url, folder, title) -> (success, message or filename)`. With this the provider needs no branch in `direct_dl_method`. Without it add a branch there (Z-Library, Soulseek and Anna's still have one, they keep counters, limits or logins) |
| `test` | `test(book, host, api) -> result`, called by the Test button. `host` and `api` are the values on the page, `None` when empty. Return a count or `False` |
| `config` | extra config items, a tuple of `ConfigStr`, `ConfigInt`, ... See below |
| `dltypes` | default of `<KEY>_DLTYPES`, `'E'` |
| `page` | what the config page shows, a `ProviderPage` |
| `wizard`, `wizard_order`, `recommended` | the setup wizard, see below |

### Search

`search_type` is the raw type of the search: `book`, `shortbook`, `titlebook`, `audio`, `mag`, `comic` or
`general...`. Use `media_type(search_type)` for `'mag'`, `'audio'` or `'ebook'`, and `search_kind` for the
letter the search needs. The registry already skips a provider that does not do the kind of item
(`skip_reason`), so the search function only sees searches it should answer.

It returns `(results, error)`. `error` is `''` when fine. A result is a dict like

```python
{'bookid': book['bookid'], 'tor_prov': 'example', 'tor_title': 'Author - Title.epub',
 'tor_url': url, 'tor_size': '12345', 'tor_type': 'direct', 'tor_extn': 'epub',
 'priority': CONFIG['EXAMPLE_DLPRIORITY']}
```

Keep what was found before an error, a later page timing out must not lose the earlier ones.

`url` goes through the web page and back to `snatch_book`, which decodes it once. Do not rely on it being
quoted: for a url the check in `valid_url` should see the plain address.

### Config items

The registry adds the three standard items of every provider: the switch `<KEY>` (boolean),
`<KEY>_DLPRIORITY` and `<KEY>_DLTYPES`. List the others in `config`, with the section equal to the key:

```python
config=(ConfigStr('EXAMPLE', 'EXAMPLE_HOST', 'https://example.org'),)
```

Do not add them to `configdefs.py`. It takes them from the registry.

### Config page

The bookstrap config page shows a provider that has a `ProviderPage`:

```python
ProviderPage(title, fields=(PageField(...), ...), help='')
PageField(name, label='', kind='text', placeholder='', tooltip='', shown='')
```

- the first field is on the line of the provider name and the enable switch; its `label` is not used.
  `shown` makes it a fixed, read only text (no login, nothing to set)
- the other fields get a row each, `kind` is `text`, `password` or `number`
- the priority, types and Test button are added to every provider
- field `name` is the config item without the key: `PageField('USER')` in `WEBSHARE` is `WEBSHARE_USER`, and the
  form field is `webshare_user`
- mark every string with `N_()`; the page translates them

A provider that needs more (a language picker, a counter, a button that reveals something) leaves `page` out and
keeps its own block in `data/interfaces/bookstrap/config.html`. Soulseek, Anna's Archive and Z-Library do that.
The modern interface builds its page from the config items and needs nothing.

### Setup wizard

`wizard=(label, help)` offers the provider in the wizard, in `wizard_order`. `recommended` lists the countries
it is switched on for by default (`'CZ'`, `'SK'`, ...), `('*',)` for every country. A provider without `wizard`
is not offered.

## Tests

`unittests/test_sources.py` covers the registry. When you add a provider update `test_builtin_providers`,
which lists the keys in order. Check by hand on a running instance:

- the Test button of the provider
- a manual search for a book, the provider shows in the results
- snatch one result: the file lands in the download directory and the history says `Snatched`
- the setup wizard offers it
