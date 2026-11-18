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

# Webshare (Czech and Slovak file hosting), direct provider

from lazylibrarian.configtypes import ConfigStr
from lazylibrarian.i18n import N_
from lazylibrarian.sources.registry import (
    DirectProvider,
    PageField,
    ProviderPage,
    media_type,
    register_direct_provider,
)


def search(book, search_type):
    from lazylibrarian.webshare import webshare_search
    return webshare_search(book, media_type(search_type))


def valid_url(url):
    from lazylibrarian.webshare import valid_ident
    return valid_ident(url)


def download(url, folder, title):
    from lazylibrarian.webshare import webshare_download
    return webshare_download(url, folder, title)


def test(book, host, api):
    from lazylibrarian.config2 import CONFIG
    from lazylibrarian.webshare import webshare_search
    if api:
        user, pwd = api.split(' : ', 1)
        CONFIG.set_str('WEBSHARE_USER', user)
        CONFIG.set_str('WEBSHARE_PASS', pwd)
    return webshare_search(book, test=True)


register_direct_provider(DirectProvider(key='WEBSHARE', name='webshare', label='Webshare', search=search,
                                        types='EAM', dltypes='A,E', result_title=True, order=40,
                                        valid_url=valid_url, download=download, test=test,
                                        config=(ConfigStr('WEBSHARE', 'WEBSHARE_USER', ''),
                                                ConfigStr('WEBSHARE', 'WEBSHARE_PASS', '')),
                                        wizard=(N_('Webshare'), N_('Czech and Slovak file hosting. Needs your Webshare login, '
                                                   'enter it on the Providers tab.')),
                                        wizard_order=20, recommended=('SK', 'CZ'),
                                        page=ProviderPage(
                                            'Webshare',
                                            (PageField('USER', placeholder=N_('webshare.cz username (optional)')),
                                             PageField('PASS', N_('Password'), 'password', N_('password (optional)'),
                                                       N_('Searching and downloading also works without an account'))))))
