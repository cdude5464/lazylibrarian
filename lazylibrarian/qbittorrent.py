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
import time
from decimal import Decimal, InvalidOperation

from lazylibrarian.config2 import CONFIG
from lazylibrarian.box_helper_handoff import (
    POLICY_QUARANTINE_PREFIX,
    QBITTORRENT_LIFECYCLE_OWNER_ENV,
    configured_qbittorrent_lifecycle_owner,
    helper_owns_qbittorrent_lifecycle,
)
from lib.qbittorrent import Client, WrongCredentialsError


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
        qb = Client(url, CONFIG['QBITTORRENT_USER'], CONFIG['QBITTORRENT_PASS'], verify=verify_ssl)
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
    cat = CONFIG['QBITTORRENT_LABEL']
    if not cat:
        cat = None
    while retries:
        # get_torrent(hashid) gets info on one torrent but doesn't return all the information
        # eg we are missing name, state, progress
        # so get all of our torrents and then look for the hashid
        try:
            torrents = qbclient.torrents(category=cat)
        except Exception as e:
            dlcommslogger.error(f" Failed to get_name: {e}")
            return ''
        for torrent in torrents:
            if torrent.get('hash') == hashid and torrent.get('name'):
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
    cat = CONFIG['QBITTORRENT_LABEL']
    if not cat:
        cat = None
    while retries:
        try:
            torrents = qbclient.torrents(category=cat)
        except Exception as e:
            dlcommslogger.error(f"Failed to get_folder: {e}")
            torrents = ''
        for torrent in torrents:
            if torrent.get('hash') == hashid and torrent.get('save_path'):
                # If there's no folder yet then it's probably a magnet, try until folder is populated
                return torrent['save_path']
        time.sleep(6)
        retries -= 1
    if not save_path:
        return ''
    if os.name != 'nt':
        save_path = save_path.replace('\\', '/')
    return os.path.basename(os.path.normpath(save_path))


def get_progress(hashid):
    # returns int(progress/error), state/errormessage, bool(complete)
    # error codes -1 not found, -2 communication error
    dlcommslogger = logging.getLogger('special.dlcomms')
    dlcommslogger.debug(f'get_progress({hashid})')
    hashid = hashid.lower()
    qbclient = get_client()
    if not qbclient:
        return -2, 'error connecting', False
    failure = ''
    try:
        preferences = qbclient.preferences()
    except Exception as e:
        dlcommslogger.error(f"Failed to get_progress: {e}")
        preferences = {}
        failure = str(e)
    dlcommslogger.debug(str(preferences))
    max_ratio = 0.0
    if 'max_ratio_enabled' in preferences and 'max_ratio' in preferences and preferences['max_ratio_enabled']:
        max_ratio = float(preferences['max_ratio'])
    max_seeding_time = 0
    if preferences.get('max_seeding_time_enabled') and 'max_seeding_time' in preferences:
        max_seeding_time = int(preferences['max_seeding_time'])
    cat = CONFIG['QBITTORRENT_LABEL']
    if not cat:
        cat = None
    try:
        torrents = qbclient.torrents(category=cat)
    except Exception as e:
        dlcommslogger.error(f"Failed to get torrents: {e}")
        return -2, 'error getting torrents', False

    for torrent in torrents:
        if torrent.get('hash') == hashid:
            state = torrent.get('state', '')
            if 'ratio' in torrent:
                ratio = float(torrent['ratio'])
            else:
                ratio = 0.0
            if 'progress' in torrent:
                try:
                    progress = int(100 * float(torrent['progress']))
                except ValueError:
                    progress = 0
            else:
                progress = 0
            finished = False

            # state was changed from pausedUP to stoppedUP in web API 2.11.0, but wiki doesn't reflect change
            # See: https://qbittorrent-api.readthedocs.io/en/latest/apidoc/definitions.html
            if state == 'pausedUP' or state == 'stoppedUP':
                ratio_met = max_ratio > 0 and ratio >= max_ratio
                seeding_time = torrent.get('seeding_time', 0)
                time_met = max_seeding_time > 0 and seeding_time >= max_seeding_time * 60
                if ratio_met or time_met:
                    finished = True
            return progress, state, finished
    return -1, failure if failure else 'error hash not found', False


def remove_torrent(hashid, remove_data=False):
    logger = logging.getLogger(__name__)
    dlcommslogger = logging.getLogger('special.dlcomms')
    dlcommslogger.debug(f'remove_torrent({hashid},{remove_data})')
    hashid = hashid.lower()
    if helper_owns_qbittorrent_lifecycle():
        owner = configured_qbittorrent_lifecycle_owner()
        logger.warning(
            f"Retaining qBittorrent task {hashid[:8]}: lifecycle removal is owned by "
            f"{owner or 'an invalid external owner'}"
        )
        return False
    qbclient = get_client()
    if not qbclient:
        return False

    cat = CONFIG['QBITTORRENT_LABEL']
    if not cat:
        cat = None
    try:
        torrents = qbclient.torrents(category=cat)
    except Exception as e:
        dlcommslogger.error(f" Failed to remove_torrent: {e}")
        return False
    for torrent in torrents:
        if torrent.get('hash') == hashid:
            remove = True
            if torrent['state'] == 'uploading' or torrent['state'] == 'stalledUP':
                if not CONFIG.get_bool('SEED_WAIT'):
                    logger.debug(f"{torrent['name']} is seeding, removing torrent and data anyway")
                else:
                    logger.info(f"{torrent['name']} has not finished seeding yet, torrent will not be removed")
                    remove = False
            if remove:
                if remove_data:
                    try:
                        qbclient.delete_permanently(hashid)
                        logger.info(f"{torrent['name']} removing torrent and data")
                    except Exception as e:
                        dlcommslogger.error(f"Failed to delete_permanently: {e}")
                        return False
                else:
                    try:
                        qbclient.delete(hashid)
                        logger.info(f"{torrent['name']} removing torrent")
                    except Exception as e:
                        dlcommslogger.error(f"Failed to delete: {e}")
                        return False
                return True
    return False


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


def check_link():
    """ Check we can talk to qbittorrent"""
    try:
        qb_api = ''
        qbclient = get_client()
        if qbclient:
            qb_api = qbclient.api_version
        if qb_api:
            qb_version = qbclient.qbittorrent_version
            return f"qBittorrent login successful, api: {qb_api} version: {qb_version}"
        return "qBittorrent login FAILED\nCheck debug log"
    except Exception as err:
        return f"qBittorrent login FAILED: {type(err).__name__} {str(err)}"


def add_file(data, hashid, title, provider_options):
    dlcommslogger = logging.getLogger('special.dlcomms')

    dlcommslogger.debug(f'add_file(data){title}')
    if not provider_share_limits(provider_options):
        return False, "Refusing qBittorrent add without an explicit provider share policy"
    hashid = hashid.lower()
    qbclient = get_client()
    if not qbclient:
        return False, "Failed to login to qbittorrent"

    kwargs = get_args(provider_options)
    dlcommslogger.debug(f'{kwargs}')
    try:
        qbclient.download_from_file(data, **kwargs)
    except Exception as e:
        dlcommslogger.error(f"Failed to download_from_file: {e}")
        return False, str(e)

    count = 0
    while count < 10:
        count += 1
        time.sleep(1)
        # noinspection PyProtectedMember
        try:
            torrent = qbclient.get_torrent(hashid)
        except Exception as e:
            dlcommslogger.error(f"Failed to add torrent file: {e}")
            return False, str(e)
        if torrent:
            mismatch = repair_provider_share_limits(qbclient, hashid, provider_options)
            if mismatch:
                dlcommslogger.warning(
                    f"qBittorrent provider share limits not verified for {hashid[:8]}: {mismatch}"
                )
                if count < 10:
                    time.sleep(1)
                    continue
                warning = quarantine_unverified_provider_torrent(
                    qbclient, hashid, mismatch
                )
                dlcommslogger.error(warning)
                # The torrent already exists. Report success so LazyLibrarian
                # records its exact hash and emits normal helper ownership
                # instead of creating an unmanaged qBittorrent orphan.
                return True, warning
            # Add explicit pause as qbittorrent v5 seems to ignore start paused arg
            if CONFIG.get_bool('TORRENT_PAUSED'):
                paused = not qbclient.qbittorrent_version.startswith('v5')
                dlcommslogger.debug(f"Pausing torrent {hashid}")
                qbclient.pause(hashid, paused)
            if count > 1:
                dlcommslogger.debug(f"hashid found in torrent list after {count} seconds")
            return True, ''
    res = "hashid not found in torrent list, add_file failed"
    dlcommslogger.debug(res)
    return False, res


def add_torrent(link, hashid, provider_options):
    dlcommslogger = logging.getLogger('special.dlcomms')

    dlcommslogger.debug(f'add_torrent({link})')
    if not provider_share_limits(provider_options):
        return False, "Refusing qBittorrent add without an explicit provider share policy"

    qbclient = get_client()
    if not qbclient:
        return False, "Failed to login to qbittorrent"

    hashid = hashid.lower()
    kwargs = get_args(provider_options)
    dlcommslogger.debug(f'{kwargs}')
    try:
        qbclient.download_from_link(link, **kwargs)
    except Exception as e:
        dlcommslogger.error(f" Failed to download_from_link: {e}")
        return False, str(e)

    count = 0
    while count < 10:
        count += 1
        time.sleep(1)
        # noinspection PyProtectedMember
        try:
            torrent = qbclient.get_torrent(hashid)
        except Exception as e:
            dlcommslogger.error(f" Failed to add torrent: {e}")
            return False, str(e)
        if torrent:
            mismatch = repair_provider_share_limits(qbclient, hashid, provider_options)
            if mismatch:
                dlcommslogger.warning(
                    f"qBittorrent provider share limits not verified for {hashid[:8]}: {mismatch}"
                )
                if count < 10:
                    time.sleep(1)
                    continue
                warning = quarantine_unverified_provider_torrent(
                    qbclient, hashid, mismatch
                )
                dlcommslogger.error(warning)
                return True, warning
            # Add explicit pause as qbittorrent v5 seems to ignore start paused arg
            if CONFIG.get_bool('TORRENT_PAUSED'):
                paused = not qbclient.qbittorrent_version.startswith('v5')
                dlcommslogger.debug(f"Pausing torrent {hashid}")
                qbclient.pause(hashid, paused)
            if count > 1:
                dlcommslogger.debug(f"hashid found in torrent list after {count} seconds")
            return True, ''
    res = "hashid not found in torrent list, add_torrent failed"
    dlcommslogger.debug(res)
    return False, res


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


def get_args(provider_options):
    """ Get optional arguments based on configuration"""
    args = {'paused': bool(CONFIG.get_bool('TORRENT_PAUSED'))}
    if CONFIG['QBITTORRENT_DIR']:
        args['savepath'] = CONFIG['QBITTORRENT_DIR']

    if CONFIG['QBITTORRENT_LABEL']:
        args['category'] = CONFIG['QBITTORRENT_LABEL']

    args.update(provider_share_limits(provider_options))

    return args
