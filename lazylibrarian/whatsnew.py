#  This file is part of Lazylibrarian.
#  Lazylibrarian is free software':'you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#  Lazylibrarian is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#  You should have received a copy of the GNU General Public License
#  along with Lazylibrarian.  If not, see <http://www.gnu.org/licenses/>.

# Purpose:
#    Tell the user what changed since the version they last saw, from the commit titles on gitlab.
#    Docker and source installs are updated from outside, so current and latest are usually the
#    same and the update check has nothing to show; this compares against WHATS_NEW_SEEN instead.
#    The commits come from git, like the update check, as every install calling the gitlab api from the same
#    project runs into its rate limits. The api is only used when git isn't installed.

import html
import logging
import re
import threading
import time

from curl_cffi import requests

import lazylibrarian
from lazylibrarian.common import proxy_list
from lazylibrarian.config2 import CONFIG

# merges, translation updates and pipeline changes say nothing about what the user gets
SKIP_TITLE = re.compile(r'^(Merge |chore\((l10n|ci)\)|ci(\([^)]*\))?:|Translated using Weblate|'
                        r'i18n: update lazylibrarian\.pot)', re.IGNORECASE)
PAGE_CACHE_SECONDS = 3600
_page_cache: dict = {}
_checked: dict = {}  # the seen and current hashes WHATS_NEW was last worked out for
_lock = threading.Lock()


def is_hash(value: str) -> bool:
    return bool(re.fullmatch(r'[0-9a-f]{7,40}', value or ''))


def same_commit(a: str, b: str) -> bool:
    """ Compare long and short hashes """
    return bool(a and b) and (a.startswith(b) or b.startswith(a))


def project_url() -> str:
    return f"https://{CONFIG['GIT_HOST']}/api/v4/projects/{CONFIG['GIT_PROJECT'] or '9317860'}"


def web_url() -> str:
    return f"https://{CONFIG['GIT_HOST']}/{CONFIG['GIT_USER']}/{CONFIG['GIT_REPO']}"


def branch() -> str:
    """ The branch to compare against, package installs follow master """
    name = CONFIG['GIT_BRANCH'] or 'master'
    return 'master' if name.lower() == 'package' else name


def link_title(title: str) -> str:
    """ Escaped commit title with #123 linked to the issue and !123 to the merge request """
    base = web_url()
    text = html.escape(title)
    text = re.sub(r'(?<![\w&])#(\d+)\b', rf'<a href="{base}/-/issues/\1" target="_blank" rel="noopener">#\1</a>',
                  text)
    return re.sub(r'(?<![\w&])!(\d+)\b',
                  rf'<a href="{base}/-/merge_requests/\1" target="_blank" rel="noopener">!\1</a>', text)


def keep_commits(commits: list) -> list:
    """ Commits worth showing, newest first, as dicts the templates can use """
    kept = []
    for item in reversed(commits):
        title = item.get('title') or ''
        if len(item.get('parent_ids') or []) > 1 or SKIP_TITLE.match(title):
            continue
        kept.append({'id': item.get('id', ''), 'short_id': item.get('short_id', ''), 'title': title,
                     'html': link_title(title), 'author': item.get('author_name', ''),
                     'date': (item.get('committed_date') or item.get('created_at') or '')[:10]})
    return kept


def gitlab_get(path: str, params: dict | None = None):
    """ Decoded json from the gitlab api, or None if it can't be reached """
    logger = logging.getLogger(__name__)
    url = f"{project_url()}/{path}"
    try:
        timeout = CONFIG.get_int('HTTP_TIMEOUT') or 30
        verify = (CONFIG['SSL_CERTS'] or True) if CONFIG.get_bool('SSL_VERIFY') else False
        r = requests.get(url, params=params, timeout=timeout, proxies=proxy_list(), impersonate='chrome',
                         verify=verify)
        if r.status_code != 200:
            logger.debug(f"What's new: {url} returned {r.status_code}")
            return None
        return r.json()
    except Exception as err:
        logger.debug(f"What's new: {url} failed, {type(err).__name__}: {err}")
        return None


def git_commits(*logs: list, ref: str = '') -> list | None:
    """ versioncheck.git_commits, imported here as versioncheck imports this module """
    from lazylibrarian import versioncheck
    return versioncheck.git_commits(*logs, branch=ref)


def changes_between(from_hash: str, to_hash: str) -> list | None:
    """ Commits after from_hash up to to_hash, oldest first, from git or else the gitlab api """
    res = git_commits(['--reverse', f'{from_hash}..{to_hash}'])
    if res is not None:
        return res[0]
    return compare(from_hash, to_hash)


def compare(from_hash: str, to_ref: str) -> list | None:
    """ Commits after from_hash up to to_ref, oldest first, or None if gitlab can't tell us """
    res = gitlab_get('repository/compare', {'from': from_hash, 'to': to_ref})
    if not isinstance(res, dict) or not isinstance(res.get('commits'), list):
        return None
    return res['commits']


def mark_seen():
    """ The user has seen the changes in the running version """
    current = CONFIG['CURRENT_VERSION']
    with _lock:
        lazylibrarian.WHATS_NEW = []
        if not is_hash(current) or CONFIG['WHATS_NEW_SEEN'] == current:
            return
        CONFIG.set_str('WHATS_NEW_SEEN', current)
    CONFIG.save_config_and_backup_old(section='Git')


def check_whats_new():
    """ Called after the version check. Fills lazylibrarian.WHATS_NEW with the changes
        between the last version the user saw and the running one """
    logger = logging.getLogger(__name__)
    current = CONFIG['CURRENT_VERSION']
    seen = CONFIG['WHATS_NEW_SEEN']
    if not is_hash(current):
        lazylibrarian.WHATS_NEW = []
        return
    if not is_hash(seen):
        # new install, or the first version with this check: nothing to tell yet
        logger.debug(f"What's new: starting from {current}")
        mark_seen()
        return
    if same_commit(seen, current):
        lazylibrarian.WHATS_NEW = []
        return
    if _checked.get('key') == (seen, current):
        return
    commits = changes_between(seen, current)
    if commits is None:
        # try again at the next version check, keep what we had
        return
    with _lock:
        if CONFIG['WHATS_NEW_SEEN'] != seen or CONFIG['CURRENT_VERSION'] != current:
            # closed or updated while we were asking gitlab
            return
        lazylibrarian.WHATS_NEW = keep_commits(commits)
        _checked['key'] = (seen, current)
    logger.debug(f"What's new: {len(lazylibrarian.WHATS_NEW)} changes since {seen}")
    if not lazylibrarian.WHATS_NEW:
        # a rollback, or nothing but merges and translations
        mark_seen()


def recent_changes(count: int = 100) -> dict:
    """ Recent commits on the branch, split into the ones not installed yet and the installed ones.
        Cached for an hour so opening the page doesn't call gitlab every time """
    current = CONFIG['CURRENT_VERSION']
    ref = branch()
    key = (current, ref)
    with _lock:
        cached = _page_cache.get('data')
        if cached and _page_cache.get('key') == key and time.time() - _page_cache.get('time', 0) < PAGE_CACHE_SECONDS:
            return cached

    data = {'error': False, 'upcoming': [], 'installed': [], 'known': is_hash(current)}
    logs = [['-n', str(count), 'FETCH_HEAD']]
    if data['known']:
        logs.append([f'{current}..FETCH_HEAD'])
    found = None
    for name in dict.fromkeys([ref, 'master']):
        # master too, for a local branch the remote doesn't have
        found = git_commits(*logs, ref=name)
        if found is not None:
            ref = name
            break
    if found is not None:
        recent = found[0]
        upcoming_ids = {item['id'] for item in found[1]} if data['known'] else set()
    else:
        recent = gitlab_get('repository/commits', {'ref_name': ref, 'per_page': count})
        if recent == [] and ref != 'master':
            # a local branch gitlab doesn't have
            ref = 'master'
            recent = gitlab_get('repository/commits', {'ref_name': ref, 'per_page': count})
        if not isinstance(recent, list):
            data['error'] = True
            return data
        upcoming_ids = set()
        if data['known']:
            newer = compare(current, ref)
            if newer is None:
                data['error'] = True
                return data
            upcoming_ids = {item.get('id') for item in newer}
    data['branch'] = ref
    # the commits api lists newest first, keep_commits expects oldest first
    for item in keep_commits(list(reversed(recent))):
        if item['id'] in upcoming_ids:
            data['upcoming'].append(item)
        else:
            data['installed'].append(item)
    with _lock:
        _page_cache.update({'key': key, 'time': time.time(), 'data': data})
    return data
