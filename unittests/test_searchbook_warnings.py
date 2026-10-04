# This file is part of LazyLibrarian.
# Test media-specific provider availability warnings without network access.

from unittest import mock

import pytest

import lazylibrarian
from lazylibrarian import searchbook
from lazylibrarian.config2 import LLConfigHandler
from lazylibrarian.configdefs import BASE_DEFAULTS


@pytest.fixture
def warning_config():
    config = LLConfigHandler(defaults=BASE_DEFAULTS)
    config.ensure_arrays_have_empty_item()
    for name in ['KAT', 'TPB', 'TDL', 'LIME', 'ABB', 'BOK', 'ANNA', 'SLSK']:
        config.set_bool(name, False)
    with mock.patch.object(searchbook, 'CONFIG', config), \
            mock.patch.object(lazylibrarian, 'TIMERS', {'NO_TOR_MSG': 0, 'NO_DIRECT_MSG': 0}), \
            mock.patch.object(searchbook.time, 'time', return_value=2000):
        yield config


@pytest.mark.parametrize('search_type', ['book', 'shortbook', 'titlebook'])
def test_audio_only_torrents_do_not_warn_for_ebooks(warning_config, search_type):
    warning_config.set_bool('ABB', True)
    with mock.patch.object(searchbook.logging, 'getLogger') as logger:
        searchbook.warn_mode('tor', search_type)
    logger.return_value.warning.assert_not_called()
    assert lazylibrarian.TIMERS['NO_TOR_MSG'] == 0


@pytest.mark.parametrize('search_type', ['audio', 'shortaudio', 'titleaudio'])
def test_ebook_only_direct_providers_do_not_warn_for_audio(warning_config, search_type):
    warning_config.set_bool('ANNA', True)
    with mock.patch.object(searchbook.logging, 'getLogger') as logger:
        searchbook.warn_mode('direct', search_type)
    logger.return_value.warning.assert_not_called()
    assert lazylibrarian.TIMERS['NO_DIRECT_MSG'] == 0


@pytest.mark.parametrize('mode, provider, search_type', [
    ('tor', 'ABB', 'audio'),
    ('tor', 'TPB', 'book'),
    ('direct', 'ANNA', 'book'),
    ('direct', 'BOK', 'book'),
    ('direct', 'SLSK', 'book'),
])
def test_compatible_unavailable_providers_still_warn(warning_config, mode, provider, search_type):
    warning_config.set_bool(provider, True)
    # This runs after the iterator reports zero successful providers; availability
    # must not suppress the warning just because the provider is now blocked.
    with mock.patch.object(searchbook.BLOCKHANDLER, 'is_blocked', return_value=True), \
            mock.patch.object(searchbook.logging, 'getLogger') as logger:
        searchbook.warn_mode(mode, search_type)
        searchbook.warn_mode(mode, search_type)
    logger.return_value.warning.assert_called_once_with(
        f'No {mode} providers are available. Check config and blocklist')


@pytest.mark.parametrize('enabled, dltypes, expected', [
    (True, 'E', True),
    (True, 'A', False),
    (False, 'E', False),
])
def test_generic_direct_provider_media_and_enabled_flags(warning_config, enabled, dltypes, expected):
    provider = warning_config.providers('GEN')[0]
    provider.set_bool('ENABLED', enabled)
    provider.set_str('DLTYPES', dltypes)
    with mock.patch.object(searchbook.logging, 'getLogger') as logger:
        searchbook.warn_mode('direct', 'book')
    assert logger.return_value.warning.called is expected


def test_blocked_compatible_provider_with_other_media_provider_still_warns(warning_config):
    warning_config.set_bool('ANNA', True)
    warning_config.set_bool('SLSK', True)
    warning_config.set_str('SLSK_DLTYPES', 'A')
    with mock.patch.object(searchbook.BLOCKHANDLER, 'is_blocked', side_effect=lambda name: name == 'annas'), \
            mock.patch.object(searchbook.logging, 'getLogger') as logger:
        searchbook.warn_mode('direct', 'book')
    logger.return_value.warning.assert_called_once()
