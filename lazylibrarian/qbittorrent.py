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
#  along with Lazylibrarian.  If not, see <http://www.gnu.org/licenses/>

import logging
import os
import re
from decimal import Decimal, InvalidOperation
import os
import re
import time

import requests

from lazylibrarian import i18n
from lazylibrarian.config2 import CONFIG
from lazylibrarian.box_helper_handoff import (
    POLICY_QUARANTINE_PREFIX,
    configured_qbittorrent_lifecycle_owner,
    helper_owns_qbittorrent_lifecycle,
    validate_box_helper_handoff_config,
)
from lazylibrarian.formatter import get_list, redact_url
from lib.qbittorrent import Client, WrongCredentialsError

# qBittorrent Web API 2.14+ can accept a torrents/add request before it has
# actually retrieved and parsed the url (pending_count > 0, HTTP 202). While
# that is in progress, torrents/properties for the new hash legitimately 404,
# so a short poll window isn't enough to tell a slow fetch from a real failure.
QBIT_ADD_POLL_SECONDS = 10
QBIT_ADD_PENDING_POLL_SECONDS = 60

# torrents/add answers 409 Conflict when qBittorrent already holds the torrent,
# whether or not it managed to merge the new trackers into the existing one.
QBIT_DUPLICATE_STATUS = 409


def get_client():
    logger = logging.getLogger(__name__)

    host = CONFIG['QBITTORRENT_HOST']
    port = CONFIG.get_int('QBITTORRENT_PORT')
    if not host.startswith("http"):
        host = f"http://{host}"
    host = host.strip('/')

    if CONFIG['QBITTORRENT_BASE']:
        url = f"{host}:{port}/{CONFIG['QBITTORRENT_BASE'].strip('/')}"
    else:
        url = f"{host}:{port}"

    try:
        verify_ssl = not CONFIG.get_bool('QBITTORRENT_IGNORE_SSL')
        skip_login = CONFIG.get_bool('QBITTORRENT_NOAUTH')
        qb = Client(url, CONFIG['QBITTORRENT_USER'], CONFIG['QBITTORRENT_PASS'],
                     verify=verify_ssl, skip_login=skip_login)
    except WrongCredentialsError:
        logger.error("qBittorrent reports Wrong Credentials")
        return None
    except Exception as e:
        logger.error(f"qBittorrent login Error: {e}")
        return None

    try:
        api = qb.api_version
    except Exception as e:
        logger.error(f"qBittorrent api_version Error: {e}")
        return None

    if not api:
        logger.debug("Failed to login to qBittorrent")
        return None
    return qb


def valid_infohash(hashid):
    """ v1 infohashes are 40 hex characters, v2 are 64 """
    if not hashid or not isinstance(hashid, str):
        return False
    return bool(re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', hashid.lower()))


def matches_hash(torrent, hashid):
    """ Match a torrents/info entry against an exact infohash.

    qBittorrent identifies a torrent by 'hash', but v2 and hybrid torrents also
    report infohash_v1/infohash_v2 separately (Web API 2.8.2+), and which of
    them ends up in 'hash' depends on the torrent.
    """
    if not isinstance(torrent, dict):
        return False
    hashid = hashid.lower()
    for key in ('hash', 'infohash_v1', 'infohash_v2'):
        value = torrent.get(key)
        if isinstance(value, str) and value.lower() == hashid:
            return True
    return False


def find_torrent(qbclient, hashid, full_scan=False):
    """ Look up a single torrent by exact infohash, or return {}.

    Not filtered by category: a torrent we didn't add ourselves, or one added
    before the category was configured, can sit in any category or save path,
    and the infohash is the only thing worth matching on. Web API versions that
    predate the hashes filter return the full list, so match locally too.

    The hashes filter only matches the id qBittorrent gave the torrent, which
    for a v2 or hybrid torrent is its truncated v2 hash, so asking for the v1
    hash of a hybrid torrent finds nothing even though it is right there.
    full_scan asks for the whole list instead and matches infohash_v1 and
    infohash_v2 as well. That costs a full torrent list, so it is only worth
    doing once the cheap lookup has already missed.
    """
    if not hashid or not isinstance(hashid, str):
        return {}
    hashid = hashid.lower()
    torrents = qbclient.torrents(hashes=hashid)
    if isinstance(torrents, list):
        for torrent in torrents:
            if matches_hash(torrent, hashid):
                return torrent
    if not full_scan:
        return {}

    torrents = qbclient.torrents()
    if not isinstance(torrents, list):
        return {}
    for torrent in torrents:
        if matches_hash(torrent, hashid):
            return torrent
    return {}


def torrent_id(torrent, default=''):
    """ The id qBittorrent knows a torrent by, which is what its api expects """
    value = torrent.get('hash') if isinstance(torrent, dict) else None
    return value.lower() if isinstance(value, str) and value else default


def get_files(hashid):
    dlcommslogger = logging.getLogger('special.dlcomms')

    dlcommslogger.debug(f'get_torrent_files({hashid})')
    hashid = hashid.lower()
    qbclient = get_client()
    if not qbclient:
        return ''
    retries = 5

    while retries:
        try:
            files = qbclient.get_torrent_files(hashid)
        except Exception as e:
            dlcommslogger.error(f"Failed to get_files: {e}")
            return ''
        if files:
            return files
        time.sleep(2)
        retries -= 1
    return ''


def get_name(hashid):
    dlcommslogger = logging.getLogger('special.dlcomms')

    dlcommslogger.debug(f'get_name({hashid})')
    hashid = hashid.lower()
    qbclient = get_client()
    if not qbclient:
        return ''

    retries = 5
    while retries:
        # get_torrent(hashid) gets info on one torrent but doesn't return all the information
        # eg we are missing name, state, progress
        try:
            torrent = find_torrent(qbclient, hashid)
        except Exception as e:
            dlcommslogger.error(f" Failed to get_name: {e}")
            return ''
        if torrent.get('name'):
            return torrent['name']
        time.sleep(2)
        retries -= 1
    return ''


def get_folder(hashid):
    dlcommslogger = logging.getLogger('special.dlcomms')

    dlcommslogger.debug(f'get_folder({hashid})')
    hashid = hashid.lower()
    qbclient = get_client()
    if not qbclient:
        return ''

    retries = 5
    save_path = ''
    while retries:
        try:
            torrent = find_torrent(qbclient, hashid)
        except Exception as e:
            dlcommslogger.error(f"Failed to get_folder: {e}")
            torrent = {}
        if torrent.get('content_path'):
            # return absolute path of single file, or folder contaning multi files
            return torrent['content_path']
        time.sleep(6)
        retries -= 1
    if not save_path:
        return ''
    if os.name != 'nt':
        save_path = save_path.replace('\\', '/')
    return os.path.basename(os.path.normpath(save_path))


def get_content_path(hashid):
    """qBittorrent's actual content path (root of the downloaded files) for a torrent.
    Differs from save_path + name when the torrent was renamed; use it to locate the real
    folder for post-processing. Returns '' if unavailable."""
    dlcommslogger = logging.getLogger('special.dlcomms')
    dlcommslogger.debug(f'get_content_path({hashid})')
    hashid = hashid.lower()
    qbclient = get_client()
    if not qbclient:
        return ''
    cat = CONFIG['QBITTORRENT_LABEL']
    if not cat:
        cat = None
    # content_path is normally populated as soon as the torrent exists, but can be briefly
    # empty right after completion; retry a few times (short sleep) before giving up.
    retries = 3
    while retries:
        try:
            torrents = qbclient.torrents(category=cat)
        except Exception as e:
            dlcommslogger.error(f"Failed to get_content_path: {e}")
            return ''
        for torrent in torrents:
            if torrent.get('hash') == hashid and torrent.get('content_path'):
                return torrent['content_path']
        retries -= 1
        if retries:
            time.sleep(2)
    return ''


def get_progress(hashid):
    # returns int(progress/error), state/errormessage, bool(complete)
    # error codes -1 not found, -2 communication error
    dlcommslogger = logging.getLogger('special.dlcomms')
    dlcommslogger.debug(f'get_progress({hashid})')
    hashid = hashid.lower()
    qbclient = get_client()
    if not qbclient:
        return -2, 'error connecting', False
    try:
        torrent = find_torrent(qbclient, hashid)
    except Exception as e:
        dlcommslogger.error(f"Failed to get torrents: {e}")
        return -2, 'error getting torrents', False

    if torrent:
        state = torrent.get('state', '')
        if 'progress' in torrent:
            try:
                progress = int(100 * float(torrent['progress']))
            except ValueError:
                progress = 0
        else:
            progress = 0

        # qBittorrent enforces the seeding policy (share-ratio / seeding-time limits, including
        # any per-provider seed_ratio/seed_duration we set when adding) itself, so we delegate the
        # "should we keep seeding?" decision to the client's reported state rather than
        # re-evaluating limits here. While a completed torrent is still being seeded it reports an
        # active upload state (uploading / stalledUP / forcedUP / queuedUP). Once the client stops
        # seeding it -- because a limit was reached, a stop-condition fired, or the user stopped it
        # -- the state becomes stoppedUP (pausedUP before web API 2.11.0). We therefore treat the
        # torrent as finished exactly when the client has stopped seeding it: this honours
        # KEEP_SEEDING while the client is still seeding, yet lets a completed-but-stopped torrent
        # be processed instead of being stuck in 'Seeding' forever.
        # See: https://qbittorrent-api.readthedocs.io/en/latest/apidoc/definitions.html
        finished = state == 'pausedUP' or state == 'stoppedUP'
        dlcommslogger.debug(f"{hashid} state={state} progress={progress} finished={finished}")
        return progress, state, finished
    return -1, 'error hash not found', False


def configured_categories():
    """ Every category this configuration could have filed a torrent under.

    QBITTORRENT_LABEL is a single category, or a comma separated list that
    resolves per library, so both spellings have to count as ours.
    """
    label = CONFIG['QBITTORRENT_LABEL']
    if not label:
        return set()
    return {label, *get_list(label, ',')}


def category_mismatch(category, expect_category=None):
    """ Say why a torrent is not where we filed it, or return '' if it is.

    With nothing recorded, fall back to what this configuration could have
    asked for. An install with no label of its own files torrents with no
    category at all, so that is what counts as ours there.
    """
    if expect_category is not None:
        if category != expect_category:
            return f"torrent category [{category}] does not match owned category [{expect_category}]"
        return ''
    ours = configured_categories() or {''}
    if category not in ours:
        return f"torrent category [{category}] is not one of ours {sorted(ours)}"
    return ''


def category_matches(hashid, expect_category=None):
    """ Whether the torrent is still in the category we filed it under.

    Three answers, because they lead to different places: True to go ahead,
    False for a torrent that is somewhere else or no longer here, and None when
    the client could not be asked, which is worth trying again rather than
    treating as a no.
    """
    dlcommslogger = logging.getLogger('special.dlcomms')
    qbclient = get_client()
    if not qbclient:
        return None
    try:
        torrent = find_torrent(qbclient, hashid.lower())
    except Exception as e:
        dlcommslogger.error(f"Failed to check category: {e}")
        return None
    if not torrent:
        return False
    return not category_mismatch(torrent.get('category') or '', expect_category)


def seed_state(hashid):
    """ What a torrent has seeded so far, as (ratio, seconds), or None.

    None means we could not ask, which is not the same as nothing seeded.
    """
    dlcommslogger = logging.getLogger('special.dlcomms')
    qbclient = get_client()
    if not qbclient:
        return None
    try:
        torrent = find_torrent(qbclient, hashid.lower())
    except Exception as e:
        dlcommslogger.error(f"Failed to get seed_state: {e}")
        return None
    if not torrent:
        return None
    # torrents/info reports the ratio as a float and seeding_time in seconds
    return torrent.get('ratio') or 0, torrent.get('seeding_time') or 0


def remove_torrent(hashid, remove_data=False, expect_category=None):
    """ Remove a torrent from qBittorrent, category permitting.

    :param expect_category: the category recorded when we snatched this, or None
        where there is no record of it. A torrent sitting in any other category
        is left alone: qBittorrent looks a torrent up by hash whatever category
        it is in, which is what lets us find one we took on, and the same reach
        would otherwise let us delete a torrent somebody keeps for a private
        tracker.
    """
    logger = logging.getLogger(__name__)
    dlcommslogger = logging.getLogger('special.dlcomms')
    dlcommslogger.debug(f'remove_torrent({hashid},{remove_data},{expect_category})')
    hashid = hashid.lower()
    if helper_owns_qbittorrent_lifecycle():
        logger.warning("qBittorrent removal is owned by the durable box helper; retaining torrent")
        return False
    qbclient = get_client()
    if not qbclient:
        return False

    try:
        torrent = find_torrent(qbclient, hashid)
    except Exception as e:
        dlcommslogger.error(f" Failed to remove_torrent: {e}")
        return False
    if torrent:
        # delete by the id qBittorrent filed it under, which is not always the
        # hash we matched on
        found = torrent_id(torrent, hashid)
        name = torrent.get('name', found)
        mismatch = category_mismatch(torrent.get('category') or '', expect_category)
        if mismatch:
            logger.warning(f"Skipping deletion of {found}: {mismatch}")
            return False
        remove = True
        if torrent.get('state') in ('uploading', 'stalledUP'):
            if not CONFIG.get_bool('SEED_WAIT'):
                logger.debug(f"{name} is seeding, removing torrent and data anyway")
            else:
                logger.info(f"{name} has not finished seeding yet, torrent will not be removed")
                remove = False
        if remove:
            if remove_data:
                try:
                    qbclient.delete_permanently(found)
                    logger.info(f"{name} removing torrent and data")
                except Exception as e:
                    dlcommslogger.error(f"Failed to delete_permanently: {e}")
                    return False
            else:
                try:
                    qbclient.delete(found)
                    logger.info(f"{name} removing torrent")
                except Exception as e:
                    dlcommslogger.error(f"Failed to delete: {e}")
                    return False
            return True
    return False


def check_link():
    """ Check we can talk to qbittorrent"""
    try:
        qb_api = ''
        qbclient = get_client()
        if qbclient:
            qb_api = qbclient.api_version
        if qb_api:
            qb_version = qbclient.qbittorrent_version
            return i18n.gettext('%(name)s login successful, api: %(api)s version: %(version)s') % {'name': 'qBittorrent', 'api': qb_api, 'version': qb_version}, True
        return i18n.gettext('%(name)s login FAILED\nCheck debug log') % {'name': 'qBittorrent'}, False
    except Exception as err:
        return i18n.gettext('%(name)s login FAILED: %(error)s') % {'name': 'qBittorrent', 'error': f'{type(err).__name__} {str(err)}'}, False


def classify_add_response(result):
    """ Interpret the response from qBittorrent's torrents/add endpoint.

    Pre-2.14 Web API responses (plain "Ok." text, or an empty body) carry no
    structured info, so there's nothing to classify - treat as 'legacy' and
    fall back to polling for the hash as before. Web API 2.14+ returns JSON
    with success_count/pending_count/failure_count and added_torrent_ids.

    :return: (state, added_ids) where state is one of
             'legacy', 'accepted', 'pending', 'rejected'
    """
    if not isinstance(result, dict):
        return 'legacy', []

    added_ids = result.get('added_torrent_ids') or []
    success_count = result.get('success_count', 0)
    pending_count = result.get('pending_count', 0)
    failure_count = result.get('failure_count', 0)

    if failure_count and not (success_count or pending_count):
        return 'rejected', added_ids
    # Check pending ahead of success: if a batch response is ever a mix of
    # the two, we still need the longer pending poll window, not the short
    # one that's only safe when everything in the batch was already added.
    if pending_count:
        return 'pending', added_ids
    if success_count:
        return 'accepted', added_ids
    return 'legacy', added_ids


def pause_torrent(qbclient, dlcommslogger, hashid):
    # Add explicit pause as qbittorrent v5 seems to ignore start paused arg
    if not CONFIG.get_bool('TORRENT_PAUSED'):
        return
    try:
        paused = not qbclient.qbittorrent_version.startswith('v5')
        dlcommslogger.debug(f"Pausing torrent {hashid}")
        qbclient.pause(hashid, paused)
    except Exception as e:
        dlcommslogger.error(f" Failed to pause torrent {hashid}: {e}")


def wait_for_torrent(qbclient, dlcommslogger, hashid, result, label):
    """ Poll qBittorrent until a just-added torrent shows up, or give up.

    :param hashid: the infohash we calculated, used when qBittorrent doesn't
                   tell us which id it gave the torrent
    :param result: the response already returned by download_from_link/file
    :param label: 'add_torrent' or 'add_file', used in the failure message
    :return: (torrent id, '', False) once it appears, or (False, message, False).
             The third value says the torrent was not already in qBittorrent.
    """
    state, added_ids = classify_add_response(result)
    dlcommslogger.debug(f"torrents/add response state={state}, id_count={len(added_ids)}")
    if helper_owns_qbittorrent_lifecycle() and added_ids:
        if (len(added_ids) != 1 or not valid_infohash(added_ids[0])
                or added_ids[0].lower() != hashid.lower()):
            return False, 'qBittorrent identity differs from durable add intent; retained for operator review', False

    if state == 'rejected':
        res = "qBittorrent rejected the torrent add"
        dlcommslogger.error(res)
        return False, res, False
    if isinstance(result, dict) and result.get('failure_count'):
        # Only reachable when success_count or pending_count is also set, ie a
        # partial failure on a multi-url add. We only ever submit one url, so
        # this shouldn't happen in practice, but don't discard it silently.
        dlcommslogger.error("qBittorrent reported a partial add failure")

    if len(added_ids) == 1 and valid_infohash(added_ids[0]):
        # Web API 2.14+ tells us the id it gave the torrent. For a v2 or hybrid
        # torrent that is the truncated v2 hash, not the v1 hash we calculate
        # from the metadata, so take qBittorrent's answer over our own.
        if added_ids[0].lower() != hashid:
            dlcommslogger.debug(f"qBittorrent gave {added_ids[0]} as the id for {hashid}")
        hashid = added_ids[0].lower()

    max_wait = QBIT_ADD_PENDING_POLL_SECONDS if state == 'pending' else QBIT_ADD_POLL_SECONDS
    count = 0
    while count < max_wait:
        count += 1
        time.sleep(1)
        try:
            torrent = qbclient.get_torrent(hashid)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                # Not indexed yet, e.g. qBittorrent is still fetching a pending url
                continue
            dlcommslogger.error(f" Failed {label}: {e}")
            return False, str(e), False
        except Exception as e:
            dlcommslogger.error(f" Failed {label}: {e}")
            return False, str(e), False
        if torrent:
            if (helper_owns_qbittorrent_lifecycle() and isinstance(torrent, dict)
                    and torrent.get('hash') and torrent_id(torrent) != hashid):
                return False, 'qBittorrent identity differs from durable add intent; retained for operator review', False
            pause_torrent(qbclient, dlcommslogger, hashid)
            if count > 1:
                dlcommslogger.debug(f"hashid found in torrent list after {count} seconds")
            return hashid, '', False

    # One last look at the whole list before giving up: a torrent fetched from
    # a url can turn out to be v2 or hybrid, and then the id qBittorrent filed
    # it under isn't the hash we have been asking for.
    try:
        torrent = find_torrent(qbclient, hashid, full_scan=True)
    except Exception as e:
        dlcommslogger.error(f" Failed {label}: {e}")
        return False, str(e), False
    if torrent:
        found = torrent_id(torrent, hashid)
        if helper_owns_qbittorrent_lifecycle() and found != hashid:
            return False, 'qBittorrent identity differs from durable add intent; retained for operator review', False
        dlcommslogger.debug(f"Found {hashid} in the torrent list under id {found}")
        pause_torrent(qbclient, dlcommslogger, found)
        return found, '', False

    res = f"hashid not found in torrent list, {label} failed"
    dlcommslogger.debug(res)
    return False, res, False


def handle_add_http_error(qbclient, dlcommslogger, err, hashid, label):
    """ Work out whether an HTTPError from torrents/add means qBittorrent
    already has the torrent we asked it for.

    A 409 says the torrent is a duplicate of one qBittorrent already holds, but
    it says that whether or not the trackers could be merged, and whether the
    existing torrent is downloading, seeding or paused. It's only a success if
    the exact infohash we wanted is really there, so ask rather than assume.

    :return: (torrent id, '', True) for a duplicate we can use, else
             (False, message, False). The third value marks a torrent that was
             already in qBittorrent before we asked for it, which makes it
             someone else's to delete.
    """
    logger = logging.getLogger(__name__)
    response = getattr(err, 'response', None)
    status_code = getattr(response, 'status_code', None)
    if status_code != QBIT_DUPLICATE_STATUS:
        dlcommslogger.error(f"Failed {label}: {err}")
        return False, str(err), False

    reason = getattr(response, 'text', '')
    if not isinstance(reason, str):
        reason = ''
    # the body is usually just "Conflict", but don't rely on that: it is the
    # one place qBittorrent could echo the url we submitted back at us
    reason = redact_url(reason.strip()[:200])

    if not valid_infohash(hashid):
        res = f"qBittorrent refused {label} with {status_code} and [{hashid}] is not a usable infohash"
        logger.error(res)
        return False, res, False

    try:
        torrent = find_torrent(qbclient, hashid, full_scan=True)
    except Exception as e:
        res = f"qBittorrent returned {status_code} for {label}, and the hash lookup failed: {e}"
        logger.error(res)
        return False, res, False

    if torrent:
        found = torrent_id(torrent, hashid)
        logger.info(f"Torrent already exists in qBittorrent; using existing hash {found}")
        category = torrent.get('category') or ''
        our_label = CONFIG['QBITTORRENT_LABEL']
        if our_label and category != our_label:
            mismatch = category_mismatch(category)
            if mismatch:
                res = (f"Torrent {found} is in category [{category}], not [{our_label}]. "
                       f"Skipping to avoid a snatch loop (the postprocessor would not "
                       f"find the files and the book would be re-searched indefinitely)")
                logger.info(res)
                return False, res, False
            logger.info(f"Existing torrent is in category [{category}] "
                        f"(accepted alternate for [{our_label}])")
        dlcommslogger.debug(f"Existing torrent: name=[{torrent.get('name')}] state={torrent.get('state')} "
                            f"category=[{category}] progress={torrent.get('progress')}")
        return found, '', True

    res = f"qBittorrent refused {label} with {status_code} and has no torrent with hash {hashid}"
    if reason:
        res = f"{res}: {reason}"
    logger.error(res)
    return False, res, False


def add_file(data, hashid, title, provider_options, label=None):
    """ Send torrent data to qBittorrent.

    :return: (torrent id, '', adopted) on success, or (False, message, False).
             The id is qBittorrent's own, which is not always the hash we
             calculated, and adopted is True when the torrent was already there.
    """
    dlcommslogger = logging.getLogger('special.dlcomms')

    dlcommslogger.debug(f'add_file(data){title}')
    hashid = hashid.lower()
    if helper_owns_qbittorrent_lifecycle():
        try:
            validate_box_helper_handoff_config()
        except RuntimeError:
            return False, 'Refusing qBittorrent add without the paired durable helper ownership configuration', False
        if not provider_share_limits(provider_options):
            return False, "Refusing qBittorrent add without an explicit provider share policy", False
    qbclient = get_client()
    if not qbclient:
        return False, "Failed to login to qbittorrent", False

    preflight_error = helper_add_preflight(qbclient, hashid)
    if preflight_error:
        return False, preflight_error, False
    kwargs = get_args(provider_options, label)
    dlcommslogger.debug(f'{kwargs}')
    try:
        result = qbclient.download_from_file(data, **kwargs)
    except requests.HTTPError as e:
        return verify_provider_add_result(qbclient, handle_add_http_error(qbclient, dlcommslogger, e, hashid, 'add_file'), provider_options, hashid)
    except Exception as e:
        dlcommslogger.error(f"Failed to download_from_file: {e}")
        return False, str(e), False

    return verify_provider_add_result(qbclient, wait_for_torrent(qbclient, dlcommslogger, hashid, result, 'add_file'), provider_options, hashid)


def add_torrent(link, hashid, provider_options, label=None):
    """ Send a url or magnet to qBittorrent.

    :return: (torrent id, '', adopted) on success, or (False, message, False).
             The id is qBittorrent's own, which is not always the hash we
             calculated, and adopted is True when the torrent was already there.
    """
    dlcommslogger = logging.getLogger('special.dlcomms')

    dlcommslogger.debug(f'add_torrent({redact_url(link)})')

    if helper_owns_qbittorrent_lifecycle():
        try:
            validate_box_helper_handoff_config()
        except RuntimeError:
            return False, 'Refusing qBittorrent add without the paired durable helper ownership configuration', False
        if not provider_share_limits(provider_options):
            return False, "Refusing qBittorrent add without an explicit provider share policy", False
    qbclient = get_client()
    if not qbclient:
        return False, "Failed to login to qbittorrent", False

    hashid = hashid.lower()
    preflight_error = helper_add_preflight(qbclient, hashid)
    if preflight_error:
        return False, preflight_error, False
    kwargs = get_args(provider_options, label)
    dlcommslogger.debug(f'{kwargs}')
    try:
        result = qbclient.download_from_link(link, **kwargs)
    except requests.HTTPError as e:
        return verify_provider_add_result(qbclient, handle_add_http_error(qbclient, dlcommslogger, e, hashid, 'add_torrent'), provider_options, hashid)
    except Exception as e:
        dlcommslogger.error(f" Failed to download_from_link: {e}")
        return False, str(e), False

    return verify_provider_add_result(qbclient, wait_for_torrent(qbclient, dlcommslogger, hashid, result, 'add_torrent'), provider_options, hashid)


def get_args(provider_options, label=None):
    """ Get optional arguments based on configuration

    :param label: the category to file the torrent under, already resolved for
        the library being searched. QBITTORRENT_LABEL can be a comma separated
        list of per library categories, so the unresolved value is not usable as
        a category on its own.
    """
    args = {'paused': bool(CONFIG.get_bool('TORRENT_PAUSED'))}
    if CONFIG['QBITTORRENT_DIR']:
        args['savepath'] = CONFIG['QBITTORRENT_DIR']

    if label is None:
        label = CONFIG['QBITTORRENT_LABEL']
    if label:
        args['category'] = label

    if helper_owns_qbittorrent_lifecycle():
        args.update(provider_share_limits(provider_options))
    else:
        if "seed_ratio" in provider_options:
            args['ratioLimit'] = provider_options["seed_ratio"]
        if "seed_duration" in provider_options:
            args['seedingTimeLimit'] = provider_options["seed_duration"]

    return args


def provider_share_limits(provider_options):
    """Return one explicit qBittorrent policy for a configured provider.

    qBittorrent uses ``-2`` for a limit inherited from its global preferences.
    Provider-aware torrents must instead send every share-limit field, using
    ``-1`` for disabled goals, so later HnR lifecycle checks never depend on a
    mutable global ratio or inactive-seeding policy.
    """
    if not isinstance(provider_options, dict) or not any(
            key in provider_options for key in ("seed_ratio", "seed_duration")):
        return {}

    def explicit_limit(key, *, whole_number=False):
        if key not in provider_options:
            return -1
        value = provider_options[key]
        if isinstance(value, bool) or value is None:
            raise ValueError(f"{key} must be finite, positive, or exactly -1")
        try:
            number = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as error:
            raise ValueError(
                f"{key} must be finite, positive, or exactly -1"
            ) from error
        if not number.is_finite():
            raise ValueError(f"{key} must be finite, positive, or exactly -1")
        if number == -1:
            return -1
        if number <= 0 or (whole_number and number != number.to_integral_value()):
            suffix = " whole minutes" if whole_number else ""
            raise ValueError(f"{key} must be positive{suffix} or exactly -1")
        return int(number) if whole_number else float(number)

    try:
        ratio = explicit_limit("seed_ratio")
        duration = explicit_limit("seed_duration", whole_number=True)
    except ValueError as error:
        logging.getLogger('special.dlcomms').error(
            f"Invalid explicit qBittorrent provider share policy: {error}"
        )
        return {}
    if ratio == -1 and duration == -1:
        logging.getLogger('special.dlcomms').error(
            "Invalid explicit qBittorrent provider share policy: all goals are disabled"
        )
        return {}
    return {
        "ratioLimit": ratio,
        "seedingTimeLimit": duration,
        "inactiveSeedingTimeLimit": -1,
    }


def provider_share_limit_mismatch(qbclient, hashid, provider_options):
    """Read back and compare the exact per-torrent provider share policy."""
    expected = provider_share_limits(provider_options)
    if not expected:
        return ''
    return share_limit_mismatch(qbclient, hashid, expected)


def share_limit_mismatch(qbclient, hashid, expected):
    """Compare one already-normalized qBittorrent share-limit mapping."""
    try:
        torrents = qbclient.torrents(hashes=hashid.lower())
    except Exception as e:
        return f"readback failed: {type(e).__name__} {e}"
    if not isinstance(torrents, list):
        return "readback returned an invalid torrent list"
    matching = [
        torrent for torrent in torrents if isinstance(torrent, dict)
        if str(torrent.get('hash', '')).lower() == hashid.lower()
    ]
    if len(matching) != 1:
        return f"readback returned {len(matching)} exact hash rows"
    torrent = matching[0]
    checks = (
        ("ratio_limit", float, float(expected["ratioLimit"])),
        ("seeding_time_limit", int, int(expected["seedingTimeLimit"])),
        ("inactive_seeding_time_limit", int, int(expected["inactiveSeedingTimeLimit"])),
    )
    mismatches = []
    for field, converter, wanted in checks:
        try:
            actual = converter(torrent.get(field))
        except (TypeError, ValueError):
            mismatches.append(f"{field}=missing expected={wanted}")
            continue
        if actual != wanted:
            mismatches.append(f"{field}={actual} expected={wanted}")
    return ', '.join(mismatches)


def set_share_limits(qbclient, hashid, limits):
    """Write all three qBittorrent share-limit fields to one exact hash."""
    qbclient._post(
        "torrents/setShareLimits",
        {
            "hashes": hashid.lower(),
            "ratioLimit": str(limits["ratioLimit"]),
            "seedingTimeLimit": str(limits["seedingTimeLimit"]),
            "inactiveSeedingTimeLimit": str(limits["inactiveSeedingTimeLimit"]),
        },
    )


def repair_provider_share_limits(qbclient, hashid, provider_options):
    """Apply an exact provider policy after add, then verify its readback."""
    expected = provider_share_limits(provider_options)
    if not expected:
        return ''
    mismatch = share_limit_mismatch(qbclient, hashid, expected)
    if not mismatch:
        return ''
    try:
        set_share_limits(qbclient, hashid, expected)
    except Exception as e:
        return f"setShareLimits failed: {type(e).__name__} {e}; prior readback: {mismatch}"
    return share_limit_mismatch(qbclient, hashid, expected)


def quarantine_unverified_provider_torrent(qbclient, hashid, provider_mismatch):
    """Stop and tag an added torrent whose provider policy cannot be verified."""
    errors = []
    try:
        qbclient._post(
            "torrents/addTags",
            {"hashes": hashid.lower(), "tags": "ll-policy-quarantine"},
        )
    except Exception as e:
        errors.append(f"quarantine tag failed: {type(e).__name__} {e}")
    try:
        qbclient._post(
            "torrents/setForceStart",
            {"hashes": hashid.lower(), "value": "false"},
        )
    except Exception as e:
        errors.append(f"force-start clear failed: {type(e).__name__} {e}")
    try:
        qbclient._post("torrents/stop", {"hashes": hashid.lower()})
    except Exception as e:
        errors.append(f"stop failed: {type(e).__name__} {e}")

    stopped = False
    for attempt in range(5):
        try:
            torrents = qbclient.torrents(hashes=hashid.lower())
            matching = [
                torrent for torrent in torrents if isinstance(torrent, dict)
                if str(torrent.get('hash', '')).lower() == hashid.lower()
            ] if isinstance(torrents, list) else []
            if len(matching) == 1:
                state = str(matching[0].get('state', '')).lower()
                stopped = state in {'stoppedup', 'stoppeddl', 'pausedup', 'pauseddl'} \
                    and not bool(matching[0].get('force_start'))
                if stopped:
                    break
        except Exception as e:
            errors.append(f"stop readback failed: {type(e).__name__} {e}")
            break
        if attempt < 4:
            time.sleep(1)
    if not stopped:
        errors.append("stop/non-forced state was not verified")
    detail = "; ".join(errors) if errors else "stopped and non-forced state verified"
    return (
        f"{POLICY_QUARANTINE_PREFIX}qBittorrent provider policy was not verified "
        f"for {hashid[:8]} ({provider_mismatch}); retained exact hash under "
        f"helper policy quarantine; {detail}"
    )


def preserve_rejected_torrent(hashid, provider_options):
    """Keep a post-add rejection under its exact provider share policy."""
    logger = logging.getLogger(__name__)
    dlcommslogger = logging.getLogger('special.dlcomms')
    hashid = hashid.lower()
    qbclient = get_client()
    if not qbclient:
        return False
    expected = provider_share_limits(provider_options)
    if not expected:
        dlcommslogger.error(
            f"Rejected torrent {hashid[:8]} has no explicit provider share policy"
        )
        return False
    mismatch = repair_provider_share_limits(qbclient, hashid, provider_options)
    if mismatch:
        dlcommslogger.error(
            f"Failed to verify rejected torrent provider share limits: {mismatch}"
        )
        return False
    logger.warning(
        f"Preserving rejected torrent {hashid[:8]} in qBittorrent under its verified provider policy"
    )
    return True


def helper_add_preflight(qbclient, hashid):
    """Refuse fresh LL adoption of any already-held helper torrent.

    Existing attested generations are recovered by the helper, never adopted by
    a new LL grab. No category, limits, state, or tracker mutation is authorized
    by this read-only check.
    """
    if not helper_owns_qbittorrent_lifecycle():
        return ''
    try:
        validate_box_helper_handoff_config()
    except RuntimeError:
        return 'Refusing qBittorrent add without the paired durable helper ownership configuration'
    try:
        existing = find_torrent(qbclient, hashid, full_scan=True)
    except Exception as exc:
        return f'Cannot verify qBittorrent ownership before add: {type(exc).__name__}'
    if existing:
        return 'Refusing fresh helper adoption of a pre-existing qBittorrent torrent'
    return ''


def verify_provider_add_result(qbclient, result, provider_options, expected_hash=None):
    """Preserve the upstream id/adopted return contract and verify our policy."""
    hashid, message, adopted = result
    if not hashid or not helper_owns_qbittorrent_lifecycle():
        return result
    if expected_hash and hashid.lower() != expected_hash.lower():
        return False, 'qBittorrent identity differs from durable add intent; retained for operator review', False
    if adopted:
        return False, 'Refusing fresh helper adoption of a pre-existing qBittorrent torrent', False
    mismatch = ''
    for attempt in range(10):
        mismatch = repair_provider_share_limits(qbclient, hashid, provider_options)
        if not mismatch:
            break
        if attempt < 9:
            time.sleep(1)
    if mismatch:
        warning = quarantine_unverified_provider_torrent(qbclient, hashid, mismatch)
        return hashid, warning, False
    return result
