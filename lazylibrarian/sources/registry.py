#  This file is part of Lazylibrarian.
#  Lazylibrarian is free software, you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#  Lazylibrarian is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#  You should have received a copy of the GNU General Public License
#  along with Lazylibrarian.  If not, see <http://www.gnu.org/licenses/>.

"""
    Registry of the direct download providers (sites we search and download a file from ourselves,
    no downloader in between), so a new one does not need adding to a list in every module that handles them.

    How to add a direct provider:
    - write the code that searches and downloads, eg lazylibrarian/mlp.py
    - its config items are the enable switch <KEY>, <KEY>_DLPRIORITY and <KEY>_DLTYPES, added for you, and the
      ones in DirectProvider.config, eg a host or a login
    - give it a ProviderPage so the config page shows it, unless it needs more than fields
    - add a module to lazylibrarian/sources/ that calls register_direct_provider() with a DirectProvider.
      Keep that module light: import the provider code inside the functions, so a provider that is
      switched off is never imported. The modules here are found and imported by load_sources().

    The search function is called as search(book, search_type) and returns (results, error).
    search_type is the raw type of the search, eg 'book', 'titlebook', 'audio', 'mag'.
    If error is set, on_error(provider, error) is called, or the provider is blocked for BLOCKLIST_TIMER.
"""

import importlib
import logging
import pkgutil
from dataclasses import dataclass
from typing import Callable, Optional

# what each kind of search needs in the DLTYPES of a provider
BOOK_SEARCHES = ('book', 'shortbook', 'titlebook')
KIND_NAMES = {'E': 'eBook', 'A': 'AudioBook', 'M': 'Magazine', 'C': 'Comic'}


@dataclass(frozen=True)
class PageField:
    """ A text, password or number field of the provider on the config page. """
    name: str                     # config item without the key, eg 'USER' for WEBSHARE_USER
    label: str = ''               # label in front of the field, not used for the first field
    kind: str = 'text'            # text, password or number
    placeholder: str = ''
    tooltip: str = ''             # shown on the end of the row
    shown: str = ''               # a fixed text instead of the config value, read only (first field only)


@dataclass(frozen=True)
class ProviderPage:
    """ What the config page shows of a provider, the strings are marked with N_() and translated by the page.
        The first field is on the line of the provider name and the switch, then the other fields,
        then the priority, types and Test button of every provider. """
    title: str
    fields: tuple = ()
    help: str = ''                # shown under the first line


@dataclass(frozen=True)
class DirectProvider:
    key: str                      # config prefix, eg 'MLP' for MLP, MLP_DLPRIORITY, MLP_DLTYPES
    name: str                     # name in the blocklist and the wanted table, eg 'mlp'
    label: str                    # name shown to the user
    search: Callable              # search(book, search_type) -> (results, error)
    types: str = 'EAMC'           # kinds of item the site has at all, whatever the user sets in DLTYPES
    general: bool = True          # also searched by general searches (no kind of item)
    on_error: Optional[Callable] = None   # on_error(provider, error), default blocks for BLOCKLIST_TIMER
    download_dir: bool = True     # downloads into the first download directory
    result_title: bool = False    # the snatched file is named by the result title, not the book name
    telemetry: str = ''           # usage key Query/<telemetry>, default the config key
    order: int = 100              # search order, lowest first
    valid_url: Optional[Callable] = None  # valid_url(url) -> bool, checks the url of a result before it is used
    config: tuple = ()            # extra ConfigItems, the switch <KEY>, <KEY>_DLPRIORITY and <KEY>_DLTYPES are added
    dltypes: str = 'E'            # default of <KEY>_DLTYPES
    page: Optional[ProviderPage] = None   # the config page shows the provider from this, None = the page has its own code
    wizard: tuple = ()            # (label, help text) of the setup wizard, both marked with N_(), empty = not offered
    wizard_order: int = 100       # order in the wizard, lowest first
    recommended: tuple = ()       # countries the wizard recommends it for, '*' for every country
    test: Optional[Callable] = None       # test(book, host, api) -> result, run by the Test button of the provider
    download: Optional[Callable] = None   # download(url, folder, title) -> (success, message or filename)
                                          # a provider with this needs no branch in direct_dl_method

    @property
    def usage_key(self) -> str:
        return self.telemetry or self.key


_DIRECT: dict[str, DirectProvider] = {}
_loaded = False


def register_direct_provider(provider: DirectProvider):
    if provider.key in _DIRECT:
        raise ValueError(f"Direct provider {provider.key} is already registered")
    if any(p.name == provider.name for p in _DIRECT.values()):
        raise ValueError(f"Direct provider name {provider.name} is already in use")
    _DIRECT[provider.key] = provider


def load_sources():
    """ Import every module in this package, each registers its sources """
    global _loaded
    if _loaded:
        return
    _loaded = True
    package = importlib.import_module(__package__)
    for module in pkgutil.iter_modules(package.__path__):
        if module.name != 'registry':
            try:
                importlib.import_module(f"{__package__}.{module.name}")
            except Exception as e:
                logging.getLogger(__name__).error(f"Failed to load source {module.name}: {type(e).__name__} {e}")


def direct_providers() -> list[DirectProvider]:
    """ All registered direct providers in search order """
    load_sources()
    return sorted(_DIRECT.values(), key=lambda p: (p.order, p.key))


def direct_config_items() -> list:
    """ The config items of all direct providers """
    from lazylibrarian.configtypes import ConfigBool, ConfigDownloadTypes, ConfigInt
    items = []
    for provider in direct_providers():
        key = provider.key
        items.extend(provider.config)
        items.append(ConfigBool(key, key, 0))
        items.append(ConfigInt(key, f'{key}_DLPRIORITY', 0))
        items.append(ConfigDownloadTypes(key, f'{key}_DLTYPES', provider.dltypes))
    return items


def wizard_providers() -> list:
    """ (key, label, help) of the direct providers the setup wizard offers """
    offered = [p for p in direct_providers() if p.wizard]
    return [(p.key, *p.wizard) for p in sorted(offered, key=lambda p: (p.wizard_order, p.key))]


def recommended_providers(country: str) -> list:
    """ Keys of the direct providers worth switching on in this country """
    return [p.key for p in direct_providers() if '*' in p.recommended or country in p.recommended]


def direct_provider(key_or_name: str) -> Optional[DirectProvider]:
    """ A direct provider by config key ('MLP') or internal name ('mlp') """
    for provider in direct_providers():
        if key_or_name in (provider.key, provider.name):
            return provider
    return None


def url_checker(name: str) -> Optional[Callable]:
    """ The function that checks the url of a result from this provider, None if it has no check """
    provider = direct_provider(name)
    return provider.valid_url if provider else None


def search_kind(search_type: str) -> str:
    """ The DLTYPES letter a search needs, '' for a general search """
    if search_type in BOOK_SEARCHES:
        return 'E'
    if 'audio' in search_type:
        return 'A'
    if 'mag' in search_type:
        return 'M'
    if 'comic' in search_type:
        return 'C'
    return ''


def media_type(search_type: str) -> str:
    """ 'mag', 'audio' or 'ebook', the searchtype most provider searches take """
    if 'mag' in search_type:
        return 'mag'
    if 'audio' in search_type:
        return 'audio'
    return 'ebook'


def skip_reason(provider: DirectProvider, search_type: str, dltypes: str) -> str:
    """ Why the provider is not searched for this type of search, '' if it is """
    kind = search_kind(search_type)
    if not kind:
        return '' if provider.general else f"Ignoring {provider.key} for {search_type}"
    if kind not in provider.types:
        return f"Ignoring {provider.key} for {KIND_NAMES[kind]}, it has none"
    if kind not in (dltypes or ''):
        return f"Ignoring {provider.key} for {KIND_NAMES[kind]}"
    return ''
