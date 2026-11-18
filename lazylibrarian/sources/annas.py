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

# Anna's Archive, direct provider

from lazylibrarian.configtypes import ConfigInt, ConfigStr
from lazylibrarian.i18n import N_
from lazylibrarian.sources.registry import DirectProvider, media_type, register_direct_provider


def search(book, search_type):
    from lazylibrarian.annas import anna_search
    return anna_search(book, media_type(search_type))


def on_error(provider, error):
    from lazylibrarian.blockhandler import BLOCKHANDLER
    from lazylibrarian.config2 import CONFIG
    # Confirmed quota failures are blocked by anna_search itself. Transport and
    # parser failures must not inherit a stale remaining-download counter.
    if not BLOCKHANDLER.is_blocked('annas-search'):
        BLOCKHANDLER.block_provider('annas-search', error, delay=CONFIG.get_int('BLOCKLIST_TIMER'))


def test(book, host, api):
    from lazylibrarian.annas import anna_search
    from lazylibrarian.config2 import CONFIG
    if host:
        CONFIG.set_str('ANNA_HOST', host)
    if api:
        CONFIG.set_str('ANNA_KEY', api)
    return anna_search(book, test=True)


register_direct_provider(DirectProvider(key='ANNA', name='annas', label="Anna's Archive", search=search,
                                        on_error=on_error, result_title=True, telemetry='annas', order=30,
                                        test=test,
                                        config=(ConfigStr('ANNA', 'ANNA_HOST', 'https://annas-archive.org'),
                                                ConfigStr('ANNA', 'ANNA_KEY', ''),
                                                ConfigInt('ANNA', 'ANNA_DLLIMIT', 0),
                                                ConfigInt('ANNA', 'ANNA_MAX_SERVERS', 1),
                                                # comma separated upper case 2 letter language codes, ANY,
                                                # or empty to use IMP_PREFLANG
                                                ConfigStr('ANNA', 'ANNA_SEARCH_LANG', '')),
                                        wizard=(N_("Anna's Archive"), N_('Books in many languages. Downloads without a key are slow.')),
                                        wizard_order=10, recommended=('*',)))
