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

# Soulseek through a slskd server, direct provider

from lazylibrarian.configtypes import ConfigStr
from lazylibrarian.i18n import N_
from lazylibrarian.sources.registry import DirectProvider, register_direct_provider


def search(book, search_type):
    from lazylibrarian.soulseek import slsk_search
    return slsk_search(book, searchtype='audio' if 'audio' in search_type else 'ebook')


# soulseek downloads into its own folder and is named by the result title
def test(book, host, api):
    from lazylibrarian.config2 import CONFIG
    from lazylibrarian.soulseek import slsk_search
    if host:
        CONFIG.set_str('SLSK_HOST', host)
    if api:
        CONFIG.set_str('SLSK_API', api)
    return slsk_search(book, test=True)


register_direct_provider(DirectProvider(key='SLSK', name='soulseek', label='Soulseek', search=search,
                                        download_dir=False, result_title=True, telemetry='soulseek', order=20,
                                        test=test,
                                        config=(ConfigStr('SLSK', 'SLSK_HOST', 'http://localhost:5030'),
                                                ConfigStr('SLSK', 'SLSK_API', ''),
                                                ConfigStr('SLSK', 'SLSK_URLBASE', '/'),
                                                ConfigStr('SLSK', 'SLSK_REMOTE', ''),
                                                ConfigStr('SLSK', 'SLSK_LOCAL', '')),
                                        wizard=(N_('Soulseek'), N_('Needs a running slskd server, set it up on the Providers tab.')),
                                        wizard_order=50))
