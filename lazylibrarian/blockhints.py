#  This file is part of Lazylibrarian.
#
# Purpose:
#   Say what to change, and where, when a provider is blocked, from the reason it was blocked for

from lazylibrarian import i18n

# a site that is down, or that Cloudflare cannot reach
_DOWN_CODES = ('502', '503', '504', '520', '521', '522', '523', '524', '525', '526', '527')
_UNREACHABLE = ('connection refused', 'failed to resolve', 'name or service not known', 'could not resolve',
                'curl: (6)', 'curl: (7)', 'connectionerror')
_SSL = ('sslerror', 'ssl:', 'certificate', 'curl: (35)', 'curl: (60)')


def _has_code(why: str, codes) -> bool:
    """ True if the lowercase reason carries one of the http status codes, as 'status 523' or 'error 503' """
    return any(f'status {code}' in why or f'error {code}' in why for code in codes)


def block_hint(prefix: str, reason: str) -> str:
    """ What to do so a provider blocked for 'reason' works again, or '' when there is nothing useful to say.
        prefix is the config form's field id prefix of the provider (newznab_0, torznab_1, kat...),
        empty for a blocked source that has no provider card (metadata sites and the like) """
    why = (reason or '').lower()
    nab = prefix.startswith(('newznab_', 'torznab_'))

    if 'timeout' in why or 'timed out' in why or 'curl: (28)' in why:
        if nab:
            return i18n.gettext('It did not answer in time. Raise its Timeout in Config → Providers, or Requests in '
                                'Config → Interface → Timeouts. If it goes through Prowlarr and FlareSolverr, check '
                                'that FlareSolverr is running and the Request Timeout of its proxy in Prowlarr.')
        return i18n.gettext('It did not answer in time. Raise Requests in Config → Interface → Timeouts.')

    if 'too many requests' in why or _has_code(why, ('429',)):
        return i18n.gettext('It limits how often it can be asked. Nothing to change: it is asked again when the block '
                            'ends, and less often each time it is still limited.')

    if not prefix:  # not a provider, the advice below is about provider settings
        return ''

    if 'unauthorized' in why or _has_code(why, ('401',)):
        if nab:
            return i18n.gettext('It refused the API key. Check the API key of this provider in Config → Providers.')
        return i18n.gettext('It refused access. Check its address in Config → Providers, or switch it off there.')

    if 'forbidden' in why or _has_code(why, ('403',)):
        if nab:
            return i18n.gettext('It blocks automated requests, often with Cloudflare. In Prowlarr, give the indexer '
                                'the tag of the FlareSolverr proxy and test it there.')
        return i18n.gettext('It blocks automated requests, often with Cloudflare. Search it through Prowlarr with '
                            'FlareSolverr instead, or switch it off in Config → Providers.')

    if _has_code(why, _DOWN_CODES):
        return i18n.gettext('The site is down or cannot be reached. Wait, or switch it off in Config → Providers if '
                            'it keeps happening.')

    if _has_code(why, ('404',)):
        return i18n.gettext('Page not found: the address is wrong or the site has changed. Check the host in '
                            'Config → Providers, or try another one.')

    # before unreachable: curl reports a certificate problem as a ConnectionError
    if any(text in why for text in _SSL):
        return i18n.gettext('A secure connection could not be made. Check http or https in the host in '
                            'Config → Providers, and the HTTPS and SSL settings in Config → Interface.')

    if any(text in why for text in _UNREACHABLE):
        return i18n.gettext('Its address cannot be reached. Check the host in Config → Providers and that the service '
                            'is running.')
    return ''
