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

# Search and download from webshare.cz using its (undocumented) XML api.
# Search and file links work anonymously, an account is optional.
# Free accounts are speed limited, which doesn't matter much for ebooks.

import contextlib
import hashlib
import logging
import os
import re
import tempfile
import xml.etree.ElementTree as ElementTree

import requests

from lazylibrarian.blockhandler import BLOCKHANDLER
from lazylibrarian.common import proxy_list
from lazylibrarian.config2 import CONFIG
from lazylibrarian.filesystem import get_directory, setperm
from lazylibrarian.formatter import get_list, plural, sanitize

WEBSHARE_API = 'https://webshare.cz/api/'
PROVIDER = 'webshare'
_ITOA64 = './0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'

_token = ''


def md5_crypt(password: str, salt: str) -> str:
    """ FreeBSD style $1$ md5 crypt, needed for webshare login
        (the crypt module is not available on windows, or python 3.13+) """
    magic = b'$1$'
    pw = password.encode('utf-8')
    if salt.startswith('$1$'):
        salt = salt[3:]
    salt_b = salt.split('$', 1)[0][:8].encode('utf-8')

    ctx = pw + magic + salt_b
    final = hashlib.md5(pw + salt_b + pw).digest()
    for pl in range(len(pw), 0, -16):
        ctx += final[:min(16, pl)]
    i = len(pw)
    while i:
        ctx += b'\x00' if i & 1 else pw[:1]
        i >>= 1
    final = hashlib.md5(ctx).digest()

    for i in range(1000):
        c = pw if i & 1 else final
        if i % 3:
            c += salt_b
        if i % 7:
            c += pw
        c += final if i & 1 else pw
        final = hashlib.md5(c).digest()

    def to64(v, n):
        res = ''
        for _ in range(n):
            res += _ITOA64[v & 0x3f]
            v >>= 6
        return res

    encoded = ''
    for a, b, c in ((0, 6, 12), (1, 7, 13), (2, 8, 14), (3, 9, 15), (4, 10, 5)):
        encoded += to64((final[a] << 16) | (final[b] << 8) | final[c], 4)
    encoded += to64(final[11], 2)
    return f"$1${salt_b.decode('utf-8')}${encoded}"


def _api(endpoint: str, data: dict):
    """ POST to the webshare api, return (xml root, error message) """
    logger = logging.getLogger(__name__)
    try:
        r = requests.post(WEBSHARE_API + endpoint + '/', data=data, timeout=30,
                          proxies=proxy_list(), headers={'Accept': 'text/xml; charset=UTF-8'})
    except Exception as e:
        return None, f"{type(e).__name__} contacting webshare: {e}"
    if r.status_code != 200:
        return None, f"webshare {endpoint} returned status {r.status_code}"
    try:
        root = ElementTree.fromstring(r.content)
    except ElementTree.ParseError as e:
        return None, f"Invalid response from webshare {endpoint}: {e}"
    if root.findtext('status') != 'OK':
        msg = f"webshare {endpoint}: {root.findtext('code')} {root.findtext('message')}"
        logger.debug(msg)
        return root, msg
    return root, ''


def webshare_login(force=False) -> str:
    """ Return a login token, or empty string to work anonymously """
    global _token
    logger = logging.getLogger(__name__)
    user = CONFIG['WEBSHARE_USER']
    password = CONFIG['WEBSHARE_PASS']
    if not user or not password:
        return ''
    if _token and not force:
        return _token

    root, err = _api('salt', {'username_or_email': user})
    if err:
        logger.warning(f"Webshare login failed: {err}")
        return ''
    salt = root.findtext('salt') or ''
    hashed = hashlib.sha1(md5_crypt(password, salt).encode('utf-8')).hexdigest()
    digest = hashlib.md5(f"{user}:Webshare:{hashed}".encode()).hexdigest()
    root, err = _api('login', {'username_or_email': user, 'password': hashed,
                               'digest': digest, 'keep_logged_in': 1})
    if err:
        logger.warning(f"Webshare login failed: {err}")
        return ''
    _token = root.findtext('token') or ''
    logger.debug(f"Webshare login {'OK' if _token else 'returned no token'}")
    return _token


def _wanted_extensions(searchtype: str) -> list:
    if searchtype == 'audio':
        # audiobooks are often uploaded as a single archive, postprocessing unpacks them
        return get_list(CONFIG['AUDIOBOOK_TYPE']) + ['zip', 'rar']
    if searchtype == 'mag':
        return get_list(CONFIG['MAG_TYPE'])
    return get_list(CONFIG['EBOOK_TYPE'])


def webshare_search(book=None, searchtype='ebook', test=False):
    logger = logging.getLogger(__name__)
    if BLOCKHANDLER.is_blocked(PROVIDER):
        if test:
            return False
        return [], "provider is already blocked"
    if test:
        book['bookid'] = '0'

    data = {'what': book['searchterm'], 'category': '' if searchtype == 'audio' else 'docs',
            'sort': '', 'limit': 100, 'offset': 0, 'wst': webshare_login()}
    root, err = _api('search', data)
    if err:
        if test:
            return False
        return [], err

    extensions = _wanted_extensions(searchtype)
    results = []
    removed = 0
    for item in root.findall('file'):
        ident = item.findtext('ident') or ''
        name = item.findtext('name') or ''
        extn = (item.findtext('type') or '').lower()
        size = item.findtext('size') or '0'
        if not ident or not name or extn not in extensions or item.findtext('password') == '1':
            removed += 1
            continue
        results.append({
            'bookid': book['bookid'],
            'tor_prov': PROVIDER,
            'tor_title': name,
            'tor_url': ident,
            'tor_size': size,
            'tor_type': 'direct',
            'tor_extn': extn,
            'priority': CONFIG['WEBSHARE_DLPRIORITY'],
        })
        logger.debug(f"Found {name}, Size {size}")

    if test:
        logger.debug(f"Test found {len(results)} {plural(len(results), 'result')} ({removed} removed)")
        return len(results)

    logger.debug(f"Found {len(results)} {plural(len(results), 'result')} from {PROVIDER} "
                 f"for {book['searchterm']} ({removed} removed)")
    return results, ''


def valid_ident(ident: str) -> bool:
    return bool(re.fullmatch(r'[A-Za-z0-9]+', ident or ''))


def safe_filename(name: str) -> str:
    """ Reduce an uploader supplied name to a single path component """
    # ':' would make "D:x" a drive relative path on Windows. sanitize() removes it, but only while
    # filename_dict has it, and dicts.json can be edited, so make sure
    name = sanitize((name or '').replace('\\', '/').split('/')[-1]).replace(':', '')
    return '' if name in ('.', '..') else name


def _remove_quietly(path: str):
    with contextlib.suppress(OSError):
        os.remove(path)


def _inside(path: str, directory: str) -> bool:
    directory = os.path.realpath(directory)
    try:
        return os.path.commonpath([os.path.realpath(path), directory]) == directory
    except ValueError:  # different drives on windows
        return False


def webshare_download(ident: str, folder: str, filename: str):
    """ Download file ident into download_dir/folder/filename
        Returns (True, destination) or (False, error message) """
    logger = logging.getLogger(__name__)
    data = {'ident': ident, 'download_type': 'file_download', 'wst': webshare_login()}
    root, err = _api('file_link', data)
    if err and root is not None and root.findtext('code', '').startswith('FILE_LINK_FATAL') and data['wst']:
        # token may have expired, retry with a fresh login
        data['wst'] = webshare_login(force=True)
        root, err = _api('file_link', data)
    if err:
        return False, err
    url = root.findtext('link')
    if not url:
        return False, "webshare returned no download link"

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
    logger.debug(f"Webshare saved {size} bytes to {dest_filename}")
    return True, dest_filename
