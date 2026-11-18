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

"""Links to other services (Audiobookshelf, Calibre, Prowlarr, the download clients...) in the "..." menus of the
modern interface. Audiobookshelf, Calibre and the downloaded files have their own address in the config,
Prowlarr and the download clients are reached at the address LazyLibrarian already uses for them."""

import re
from urllib.parse import urlsplit

import lazylibrarian
from lazylibrarian import i18n
from lazylibrarian.config2 import CONFIG

# the links with an address of their own: (config key prefix, icon, default name, for admins only)
LINKS = [
    ('LINK_AUDIOBOOKSHELF', 'fa-headphones', 'Audiobookshelf', False),
    ('LINK_CALIBRE', 'fa-book-open', 'Calibre', False),
    ('LINK_DOWNLOADS', 'fa-folder-open', None, True),
]
# the links built from other settings, for admins only
AUTO_LINKS = ['LINK_DOWNLOADER', 'LINK_PROWLARR']
LOCAL_HOSTS = ('localhost', '127.0.0.1', '0.0.0.0', '::1', '[::1]')


def safe_url(url: str) -> str:
    """ The address as a link may use it: http(s), or a bare host which gets http:// """
    url = (url or '').strip()
    if not url:
        return ''
    low = url.lower()
    if low.startswith(('http://', 'https://')):
        return url
    if '://' in low or low.startswith(('javascript:', 'data:', 'vbscript:')):
        return ''
    return 'http://' + url


def _browser_host() -> str:
    """ The host name the browser reached LazyLibrarian on, empty outside a web request """
    try:
        import cherrypy
        return urlsplit(cherrypy.request.base).hostname or ''
    except Exception:
        return ''


def _is_container_name(name: str) -> bool:
    """ In docker, a host name without dots (and not an address) is another container, unknown to the browser """
    if not name or '.' in name or ':' in name:
        return False
    try:
        from lazylibrarian.common import docker
        return bool(docker())
    except Exception:
        return False


def _for_browser(url: str) -> str:
    """ A service LazyLibrarian reaches on localhost runs on the machine the browser reached LazyLibrarian on,
        and so does one reached by a docker container name (qbittorrent:8090), which only docker can resolve """
    parts = urlsplit(url)
    name = (parts.hostname or '').lower()
    if name in LOCAL_HOSTS or _is_container_name(name):
        host = _browser_host()
        if host and host.lower() not in LOCAL_HOSTS:
            if ':' in host:
                host = f'[{host}]'
            netloc = host + (f':{parts.port}' if parts.port else '')
            url = parts._replace(netloc=netloc).geturl()
    return url


def _client_url(host: str, port=0, base='', https=False) -> str:
    """ host[:port][/base] as an url, the way the download client modules build it """
    host = (host or '').strip()
    if not host:
        return ''
    if not host.lower().startswith('http'):
        host = ('https://' if https else 'http://') + host
    url = host.rstrip('/')
    if port and not urlsplit(url).port:
        url = f'{url}:{port}'
    base = (base or '').strip('/')
    if base:
        url = f'{url}/{base}'
    return url + '/'


def downloader_links() -> list:
    """ The web interfaces of the download clients in use, as (href, icon, name) """
    links = []
    for name, href in client_urls(enabled_only=True).items():
        if href not in [link[0] for link in links]:
            links.append((href, 'fa-cloud-download-alt', name))
    return links


def client_urls(enabled_only=False) -> dict:
    """ The web interface of each download client that has a host set, {name: url as the browser reaches it},
        only those in use when enabled_only """
    def use(key):
        return not enabled_only or CONFIG.get_bool(key)
    clients = []
    if use('TOR_DOWNLOADER_QBITTORRENT'):
        clients.append(('qBittorrent', _client_url(CONFIG['QBITTORRENT_HOST'], CONFIG.get_int('QBITTORRENT_PORT'),
                                                   CONFIG['QBITTORRENT_BASE'])))
    if use('TOR_DOWNLOADER_TRANSMISSION'):
        # the setting is the rpc base, the web interface is next to it
        base = (CONFIG['TRANSMISSION_BASE'] or '/transmission/').strip('/')
        base = re.sub(r'/rpc$', '', base)
        clients.append(('Transmission', _client_url(CONFIG['TRANSMISSION_HOST'], CONFIG.get_int('TRANSMISSION_PORT'),
                                                    f'{base}/web')))
    if use('TOR_DOWNLOADER_DELUGE') and not CONFIG['DELUGE_USER']:
        # with a user name LazyLibrarian talks to the deluge daemon, which has no web page
        clients.append(('Deluge', _client_url(CONFIG['DELUGE_HOST'], CONFIG.get_int('DELUGE_PORT'),
                                              CONFIG['DELUGE_BASE'], https=bool(CONFIG['DELUGE_CERT']))))
    if use('TOR_DOWNLOADER_UTORRENT'):
        clients.append(('uTorrent', _client_url(CONFIG['UTORRENT_HOST'], CONFIG.get_int('UTORRENT_PORT'),
                                                CONFIG['UTORRENT_BASE'] or 'gui')))
    if use('NZB_DOWNLOADER_SABNZBD'):
        # the external host is the address for the browser, when it differs from the one LazyLibrarian uses
        host = CONFIG['SAB_EXTERNAL_HOST'] or CONFIG['SAB_HOST']
        port = 0 if CONFIG['SAB_EXTERNAL_HOST'] else CONFIG.get_int('SAB_PORT')
        clients.append(('SABnzbd', _client_url(host, port, CONFIG['SAB_SUBDIR'])))
    if use('NZB_DOWNLOADER_NZBGET'):
        clients.append(('NZBGet', _client_url(CONFIG['NZBGET_HOST'], CONFIG.get_int('NZBGET_PORT'))))
    if use('TOR_DOWNLOADER_SYNOLOGY') or use('NZB_DOWNLOADER_SYNOLOGY'):
        clients.append(('Download Station', _client_url(CONFIG['SYNOLOGY_HOST'], CONFIG.get_int('SYNOLOGY_PORT'))))
    urls = {}
    for name, url in clients:
        href = safe_url(url)
        if href:
            urls[name] = _for_browser(href)
    return urls


def prowlarr_links() -> list:
    """ Prowlarr, as (href, icon, name) """
    return [(url, 'fa-search', 'Prowlarr') for url in prowlarr_urls()]


def prowlarr_urls(arrays=('NEWZNAB', 'TORZNAB')) -> list:
    """ Prowlarr, found from the indexers it added to these provider lists: it names them "<indexer> (Prowlarr)"
        and gives each the address <prowlarr>/<indexer id>/ """
    urls = []
    for array in arrays:
        for provider in CONFIG.providers(array):
            host = safe_url(provider['HOST'])
            if not host:
                continue
            parts = urlsplit(host)
            by_name = provider['DISPNAME'].strip().lower().endswith('(prowlarr)')
            by_address = parts.port == 9696 and re.search(r'/\d+/?(api)?/?$', parts.path)
            if not (by_name or by_address):
                continue
            path = re.sub(r'/\d+/?(api)?/?$', '', parts.path).rstrip('/')
            url = _for_browser(parts._replace(path=path + '/', query='', fragment='').geturl())
            if url not in urls:
                urls.append(url)
    return urls


CUSTOM_PAGES = ('books', 'audio', 'history', 'logs')


def custom_link(page=None) -> list:
    """ The link of your own, as [(href, icon, name)], if it has an address and goes on this page """
    href = safe_url(CONFIG.get_str('LINK_CUSTOM_URL'))
    if not href or (page and CONFIG.get_str('LINK_CUSTOM_PAGE') != page):
        return []
    name = CONFIG.get_str('LINK_CUSTOM_NAME').strip() or urlsplit(href).hostname or href
    return [(href, 'fa-link', name)]


def menu_links(perm: int, only=None, page=None) -> list:
    """ The links to show for a user with these permissions, as (href, icon, name),
        only those in the list of keys (eg ['LINK_CALIBRE']) when it is given, and the link of your own
        when it is set for this page (books, audio, history or logs) """
    if not perm or not CONFIG.get_bool('MENU_LINKS'):
        return []
    admin = bool(perm & lazylibrarian.perm_config)
    links = []
    for key, icon, default, admin_only in LINKS:
        if (admin_only and not admin) or (only is not None and key not in only):
            continue
        href = safe_url(CONFIG.get_str(f'{key}_URL'))
        if not href:
            continue
        name = ''
        if f'{key}_NAME' in CONFIG.config:
            name = CONFIG.get_str(f'{key}_NAME').strip()
        if not name:
            name = default or i18n.gettext('Downloaded files')
        links.append((href, icon, name))
    if admin:
        if only is None or 'LINK_DOWNLOADER' in only:
            links.extend(downloader_links())
        if only is None or 'LINK_PROWLARR' in only:
            links.extend(prowlarr_links())
        if only is None or page:
            links.extend(custom_link(page))
    return links
