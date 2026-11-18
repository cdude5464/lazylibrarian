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

# Search and download the free e-books of the Prague City Library (Městská knihovna v Praze, mlp.cz/cz/eknihy).
# The catalogue has a public json api and the files can be downloaded without a library card or any login.

import json
import logging
import os
import re
import tempfile

import requests

from lazylibrarian.blockhandler import BLOCKHANDLER
from lazylibrarian.common import proxy_list
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import get_directory, setperm
from lazylibrarian.formatter import get_list, plural
from lazylibrarian.webshare import _inside, _remove_quietly, safe_filename

MLP_API = 'https://www.mlp.cz/katalog/api/'
MLP_FILES = 'https://web2.mlp.cz/koweb/'
PROVIDER = 'mlp'
PAGE_SIZE = 25

# The files live at <koweb>/<title key zero padded to 10 digits, in pairs>/<name>.<format>
_URL_RE = re.compile(r'https://web2\.mlp\.cz/koweb/(?:\d{2}/){5}[A-Za-z0-9_.-]+\.[A-Za-z0-9]{2,5}')


def valid_url(url: str) -> bool:
    """ Only ever fetch files from the library file server """
    return bool(_URL_RE.fullmatch(url or '')) and '..' not in url


def file_url(titul_key, name: str, extn: str) -> str:
    key = str(titul_key).zfill(10)
    path = '/'.join(key[i:i + 2] for i in range(0, 10, 2))
    return f"{MLP_FILES}{path}/{name}.{extn}"


def _api(endpoint: str, params):
    """ GET from the catalogue api, return (json, error message) """
    try:
        r = requests.get(MLP_API + endpoint, params=params, timeout=30, proxies=proxy_list())
    except Exception as e:
        return None, f"{type(e).__name__} contacting mlp.cz: {e}"
    if r.status_code != 200:
        return None, f"mlp.cz {endpoint} returned status {r.status_code}"
    try:
        return json.loads(r.content.decode('utf-8')), ''
    except ValueError as e:
        return None, f"Invalid response from mlp.cz {endpoint}: {e}"


def _first(value) -> str:
    """ Catalogue fields are lists, take the first entry """
    if isinstance(value, list):
        value = value[0] if value else ''
    return str(value or '').strip()


def _author(source: dict) -> str:
    """ 'Neff, Vladimír' -> 'Vladimír Neff' """
    name = _first(source.get('zahlavi'))
    if ',' in name:
        last, first = name.split(',', 1)
        name = f"{first.strip()} {last.strip()}"
    return name.strip()


def _wanted_extensions() -> list:
    return get_list(CONFIG['EBOOK_TYPE'])


def mlp_search(book=None, searchtype='ebook', test=False):
    logger = logging.getLogger(__name__)
    if BLOCKHANDLER.is_blocked(PROVIDER):
        if test:
            return False
        return [], "provider is already blocked"
    if test:
        book['bookid'] = '0'

    params = {'query': book['searchterm'], 'size': PAGE_SIZE, 'logged_in': 'false',
              'filter[format][eq]': 'e-kniha'}
    data, err = _api('titul/search', params)
    if err:
        if test:
            return False
        return [], err

    # the search result lacks the file list, and not every e-book can be downloaded
    keys = []
    for hit in data.get('hits', {}).get('hits', []):
        source = hit.get('_source', {})
        if 'T' in (source.get('ke_stazeni') or []) and source.get('titul_key'):
            keys.append(source['titul_key'])

    extensions = _wanted_extensions()
    results = []
    removed = 0
    if keys:
        params = [('id', key) for key in keys] + [('size', len(keys)), ('source', 'full'), ('logged_in', 'false')]
        data, err = _api('titul', params)
        if err:
            if test:
                return False
            return [], err
        for hit in data.get('hits', {}).get('hits', []):
            source = hit.get('_source', {})
            name = _first(source.get('nazev'))
            author = _author(source)
            for digi in source.get('digi') or []:
                extn = (digi.get('digi_format') or '').lower()
                soubor = digi.get('digi_ptr_soubor') or ''
                url = file_url(source.get('titul_key', ''), soubor, extn)
                if not name or extn not in extensions or not valid_url(url):
                    removed += 1
                    continue
                title = f"{author} - {name}.{extn}" if author else f"{name}.{extn}"
                results.append({
                    'bookid': book['bookid'],
                    'tor_prov': PROVIDER,
                    'tor_title': title,
                    'tor_url': url,
                    'tor_size': digi.get('digi_filesize') or '0',
                    'tor_type': 'direct',
                    'tor_extn': extn,
                    'priority': CONFIG['MLP_DLPRIORITY'],
                })
                logger.debug(f"Found {title}, Size {digi.get('digi_filesize')}")

    if test:
        logger.debug(f"Test found {len(results)} {plural(len(results), 'result')} ({removed} removed)")
        return len(results)

    logger.debug(f"Found {len(results)} {plural(len(results), 'result')} from {PROVIDER} "
                 f"for {book['searchterm']} ({removed} removed)")
    return results, ''


def mlp_download(url: str, folder: str, filename: str):
    """ Download url into download_dir/folder/filename
        Returns (True, destination) or (False, error message) """
    logger = logging.getLogger(__name__)
    if not valid_url(url):
        return False, f"Invalid mlp url [{url}]"

    root_dir = get_directory('Download')
    download_dir = os.path.join(root_dir, folder) if folder else root_dir
    safe_name = safe_filename(filename)
    dest_filename = os.path.join(download_dir, safe_name)
    if not safe_name or not _inside(dest_filename, root_dir):
        return False, f"Refusing to save {filename} outside the download directory"
    if folder:
        os.makedirs(download_dir, exist_ok=True)
    # write to a unique temporary file so a failed download never leaves or clobbers a book file
    part_filename = ''
    size = 0
    try:
        with requests.get(url, stream=True, timeout=60, proxies=proxy_list()) as r:
            if r.status_code != 200:
                return False, f"Got a {r.status_code} response downloading {filename}"
            fd, part_filename = tempfile.mkstemp(suffix='.part', dir=download_dir)
            with os.fdopen(fd, 'wb') as f:
                for chunk in r.iter_content(chunk_size=65536):
                    f.write(chunk)
                    size += len(chunk)
        if size >= 100:
            os.replace(part_filename, dest_filename)
    except Exception as e:
        if part_filename:
            _remove_quietly(part_filename)
        return False, f"{type(e).__name__} downloading {filename}: {e}"

    if size < 100:
        _remove_quietly(part_filename)
        return False, f"Only got {size} bytes for {filename}"
    setperm(dest_filename)
    logger.debug(f"MLP saved {size} bytes to {dest_filename}")
    return True, dest_filename
