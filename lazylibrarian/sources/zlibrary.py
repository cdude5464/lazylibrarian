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

# Z-Library, direct provider

from lazylibrarian.configtypes import ConfigCSV, ConfigInt, ConfigStr
from lazylibrarian.i18n import N_
from lazylibrarian.sources.registry import DirectProvider, register_direct_provider


def search(book, search_type):
    from lazylibrarian.directparser import direct_bok
    return direct_bok(book, 'BOK')


def on_error(provider, error):
    import time

    import lazylibrarian
    from lazylibrarian.blockhandler import BLOCKHANDLER
    from lazylibrarian.config2 import CONFIG
    from lazylibrarian.directparser import bok_grabs
    # use a short delay for site unavailable etc
    delay = CONFIG.get_int('BLOCKLIST_TIMER')
    dl_limit = CONFIG.get_int('BOK_DLLIMIT')
    count = lazylibrarian.TIMERS['BOK_TODAY']
    if count and count >= dl_limit:
        # rolling 24hr delay if limit reached
        grabs, oldest = bok_grabs()
        delay = oldest + 24 * 60 * 60 - time.time()
        error = f"Reached Daily download limit ({grabs}/{dl_limit})"
    BLOCKHANDLER.block_provider(provider.name, error, delay=delay)


def test(book, host, api):
    from lazylibrarian.config2 import CONFIG
    from lazylibrarian.directparser import direct_bok
    if host:
        CONFIG.set_str('BOK_HOST', host)
    if api:
        email, pwd, langs = api.split(' : ')
        CONFIG.set_str('BOK_EMAIL', email)
        CONFIG.set_str('BOK_PASS', pwd)
        CONFIG.set_str('BOK_SEARCH_LANG', langs)
    return direct_bok(book, prov='BOK', test=True)


register_direct_provider(DirectProvider(key='BOK', name='zlibrary', label='Z-Library', search=search,
                                        on_error=on_error, order=10, test=test,
                                        config=(ConfigStr('BOK', 'BOK_HOST', 'b-ok.cc'),
                                                ConfigStr('BOK', 'BOK_PASS', ''),
                                                ConfigStr('BOK', 'BOK_EMAIL', ''),
                                                ConfigStr('BOK', 'BOK_REMIX_USERID', ''),
                                                ConfigStr('BOK', 'BOK_REMIX_USERKEY', ''),
                                                # comma separated language names, ANY, or empty to use IMP_PREFLANG
                                                ConfigCSV('BOK', 'BOK_SEARCH_LANG', ''),
                                                ConfigInt('BOK', 'BOK_DLLIMIT', 5)),
                                        wizard=(N_('Z-Library'), N_('Needs your Z-Library login, enter it on the Providers tab.')),
                                        wizard_order=40))
