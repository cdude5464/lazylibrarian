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

# Free e-books of the Prague City Library (Městská knihovna v Praze), direct provider

from lazylibrarian.i18n import N_
from lazylibrarian.sources.registry import DirectProvider, PageField, ProviderPage, register_direct_provider


def search(book, search_type):
    from lazylibrarian.mlp import mlp_search
    return mlp_search(book, 'ebook')


def valid_url(url):
    from lazylibrarian.mlp import valid_url as mlp_valid_url
    return mlp_valid_url(url)


def download(url, folder, title):
    from lazylibrarian.mlp import mlp_download
    return mlp_download(url, folder, title)


def test(book, host, api):
    from lazylibrarian.mlp import mlp_search
    return mlp_search(book, test=True)


register_direct_provider(DirectProvider(key='MLP', name='mlp', label='Městská knihovna v Praze', search=search,
                                        types='E', general=False, result_title=True, order=50,
                                        valid_url=valid_url, download=download, test=test,
                                        wizard=(N_('Prague City Library'), N_('Free Czech e-books from the Městská knihovna v Praze. '
                                                          'No login needed.')),
                                        wizard_order=30, recommended=('CZ',),
                                        page=ProviderPage(
                                            N_('Prague City Library'), (PageField('', shown='mlp.cz/cz/eknihy'),),
                                            N_('Free Czech e-books from the Městská knihovna v Praze, '
                                               'no login needed. eBooks only.'))))
