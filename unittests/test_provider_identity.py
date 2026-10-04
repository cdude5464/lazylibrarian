from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from lazylibrarian import downloadmethods, resultlist


class Provider(dict):
    def get_item(self, key):
        return SimpleNamespace(value=self[key])


class ProviderIdentityTest(TestCase):
    def setUp(self):
        self.provider = Provider(NAME='Torznab_3', DISPNAME='IPTorrents',
                                 HOST='http://jackett:9117/jackett/api/v2.0/indexers/iptorrents/results/torznab/',
                                 SEED_RATIO=1.1, SEED_DURATION=43200)

    def resolve(self, identity, providers=None):
        with patch.object(downloadmethods.CONFIG, 'providers',
                          return_value=providers if providers is not None else [self.provider]):
            return downloadmethods.torrent_provider_options(identity)

    def test_result_url_without_configured_terminal_slash_keeps_policy(self):
        self.assertEqual(self.resolve(self.provider['HOST'].rstrip('/')),
                         {'seed_ratio': 1.1, 'seed_duration': 43200})

    def test_reverse_slash_difference_keeps_policy(self):
        self.provider['HOST'] = self.provider['HOST'].rstrip('/')
        self.assertEqual(self.resolve(self.provider['HOST'] + '/')['seed_duration'], 43200)

    def test_exact_internal_and_display_names_keep_policy(self):
        for key in ('NAME', 'DISPNAME'):
            self.assertEqual(self.resolve(self.provider[key])['seed_duration'], 43200)

    def test_other_provider_prefix_query_and_scheme_never_inherit_policy(self):
        for identity in ('', 'unknown', self.provider['HOST'] + 'other',
                         self.provider['HOST'] + '?other=1',
                         self.provider['HOST'].replace('iptorrents', 'seedpool-api'),
                         self.provider['HOST'].replace('http:', 'https:')):
            self.assertEqual(self.resolve(identity), {})

    def test_duplicate_normalized_identity_fails_closed(self):
        other = Provider(self.provider)
        other['NAME'] = 'Torznab_4'
        other['HOST'] = other['HOST'].rstrip('/')
        self.assertEqual(self.resolve(other['HOST'], [self.provider, other]), {})

    def test_missing_limits_do_not_invent_policy(self):
        self.provider.update(SEED_RATIO=0, SEED_DURATION=0)
        self.assertEqual(self.resolve(self.provider['HOST']), {})


class ConfigurationFailureRetryTest(TestCase):
    def test_only_exact_failed_pre_add_configuration_refusal_is_retryable(self):
        reason = 'Refusing qBittorrent add without an explicit provider share policy'
        for media in ('eBook', 'AudioBook'):
            self.assertTrue(resultlist._failed_source_retryable(
                {'Status': 'Failed', 'NZBprov': 'iptorrents', 'DLResult': reason}, media))
        for status, message in (
                ('Processed', reason),
                ('Failed', 'Wrong author in source metadata'),
                ('Failed', reason + '; source rejected'),
                ('Failed', 'BOX_HELPER_POLICY_QUARANTINE: policy not verified')):
            self.assertFalse(resultlist._failed_source_retryable(
                {'Status': status, 'NZBprov': 'iptorrents', 'DLResult': message}, 'eBook'))
