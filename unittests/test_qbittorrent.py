from unittest import TestCase
from unittest.mock import Mock, call, patch

from lazylibrarian import box_helper_handoff, download_client, qbittorrent


class FakeConfig(dict):
    def get_bool(self, key):
        return bool(self.get(key, False))


class QbittorrentProviderShareLimitTest(TestCase):
    def setUp(self):
        self.config = FakeConfig({
            'QBITTORRENT_DIR': '/books',
            'QBITTORRENT_LABEL': 'books',
            'TORRENT_PAUSED': False,
        })

    def test_time_only_provider_sends_explicit_disabled_ratio_and_inactive_limits(self):
        with patch.object(qbittorrent, 'CONFIG', self.config):
            args = qbittorrent.get_args({'seed_duration': 20160})

        self.assertEqual(args['ratioLimit'], -1)
        self.assertEqual(args['seedingTimeLimit'], 20160)
        self.assertEqual(args['inactiveSeedingTimeLimit'], -1)

    def test_ratio_only_provider_sends_explicit_disabled_time_and_inactive_limits(self):
        with patch.object(qbittorrent, 'CONFIG', self.config):
            args = qbittorrent.get_args({'seed_ratio': 1.1})

        self.assertEqual(args['ratioLimit'], 1.1)
        self.assertEqual(args['seedingTimeLimit'], -1)
        self.assertEqual(args['inactiveSeedingTimeLimit'], -1)

    def test_unconfigured_provider_does_not_invent_a_share_policy(self):
        with patch.object(qbittorrent, 'CONFIG', self.config):
            args = qbittorrent.get_args({})

        self.assertNotIn('ratioLimit', args)
        self.assertNotIn('seedingTimeLimit', args)
        self.assertNotIn('inactiveSeedingTimeLimit', args)

    def test_invalid_or_all_disabled_provider_policy_is_rejected(self):
        invalid = (
            {'seed_ratio': -1, 'seed_duration': -1},
            {'seed_ratio': 0, 'seed_duration': 20160},
            {'seed_ratio': -2, 'seed_duration': 20160},
            {'seed_ratio': float('nan'), 'seed_duration': 20160},
            {'seed_ratio': float('inf'), 'seed_duration': 20160},
            {'seed_ratio': True, 'seed_duration': 20160},
            {'seed_duration': 1.5},
        )
        for provider_options in invalid:
            with self.subTest(provider_options=provider_options):
                self.assertEqual(
                    qbittorrent.provider_share_limits(provider_options), {}
                )

    def test_unknown_provider_is_refused_before_qbittorrent_side_effect(self):
        with (
            patch.object(qbittorrent, 'CONFIG', self.config),
            patch.object(qbittorrent, 'get_client') as get_client,
        ):
            success, error = qbittorrent.add_torrent(
                'https://tracker.invalid/file', 'a' * 40, {}
            )

        self.assertFalse(success)
        self.assertIn('explicit provider share policy', error)
        get_client.assert_not_called()

    def test_readback_rejects_inherited_inactive_limit(self):
        client = Mock()
        client.torrents.return_value = [{
            'hash': 'a' * 40,
            'ratio_limit': -1,
            'seeding_time_limit': 20160,
            'inactive_seeding_time_limit': -2,
        }]

        mismatch = qbittorrent.provider_share_limit_mismatch(
            client, 'a' * 40, {'seed_duration': 20160}
        )

        self.assertIn('inactive_seeding_time_limit=-2 expected=-1', mismatch)

    def test_file_and_link_adds_send_and_verify_the_exact_policy(self):
        expected_limits = {
            'ratioLimit': -1,
            'seedingTimeLimit': 20160,
            'inactiveSeedingTimeLimit': -1,
        }
        for add_name, add_args in (
            ('add_file', (b'torrent', 'a' * 40, 'Book', {'seed_duration': 20160})),
            ('add_torrent', ('https://tracker.invalid/file', 'a' * 40, {'seed_duration': 20160})),
        ):
            with self.subTest(add_name=add_name):
                client = Mock()
                client.get_torrent.return_value = {'hash': 'a' * 40}
                client.torrents.return_value = [{
                    'hash': 'a' * 40,
                    'ratio_limit': -1,
                    'seeding_time_limit': 20160,
                    'inactive_seeding_time_limit': -1,
                }]
                with (
                    patch.object(qbittorrent, 'CONFIG', self.config),
                    patch.object(qbittorrent, 'get_client', return_value=client),
                ):
                    success, error = getattr(qbittorrent, add_name)(*add_args)

                self.assertTrue(success, error)
                method = (
                    client.download_from_file
                    if add_name == 'add_file'
                    else client.download_from_link
                )
                _, kwargs = method.call_args
                self.assertEqual(
                    {key: kwargs[key] for key in expected_limits},
                    expected_limits,
                )
                client.torrents.assert_called_once_with(hashes='a' * 40)

    def test_post_add_mismatch_is_repaired_and_verified_on_exact_hash(self):
        client = Mock()
        client.torrents.side_effect = [
            [{
                'hash': 'a' * 40,
                'ratio_limit': -2,
                'seeding_time_limit': -2,
                'inactive_seeding_time_limit': -2,
            }],
            [{
                'hash': 'a' * 40,
                'ratio_limit': -1,
                'seeding_time_limit': 20160,
                'inactive_seeding_time_limit': -1,
            }],
        ]

        mismatch = qbittorrent.repair_provider_share_limits(
            client, 'a' * 40, {'seed_duration': 20160}
        )

        self.assertEqual(mismatch, '')
        client._post.assert_called_once_with(
            'torrents/setShareLimits',
            {
                'hashes': 'a' * 40,
                'ratioLimit': '-1',
                'seedingTimeLimit': '20160',
                'inactiveSeedingTimeLimit': '-1',
            },
        )

    def test_policy_mismatch_quarantines_exact_hash_stopped_and_nonforced(self):
        client = Mock()
        client.torrents.return_value = [{
            'hash': 'a' * 40,
            'state': 'stoppedUP',
            'force_start': False,
        }]

        warning = qbittorrent.quarantine_unverified_provider_torrent(
            client, 'a' * 40, 'inactive limit mismatch'
        )

        self.assertTrue(warning.startswith(qbittorrent.POLICY_QUARANTINE_PREFIX))
        self.assertIn('stopped and non-forced state verified', warning)
        self.assertEqual(
            client._post.call_args_list,
            [
                call(
                    'torrents/addTags',
                    {'hashes': 'a' * 40, 'tags': 'll-policy-quarantine'},
                ),
                call(
                    'torrents/setForceStart',
                    {'hashes': 'a' * 40, 'value': 'false'},
                ),
                call('torrents/stop', {'hashes': 'a' * 40}),
            ],
        )

    def test_rejected_torrent_preserves_and_verifies_exact_provider_policy(self):
        client = Mock()
        client.torrents.side_effect = [
            [{
                'hash': 'a' * 40,
                'ratio_limit': -1,
                'seeding_time_limit': 43200,
                'inactive_seeding_time_limit': -1,
            }],
            [{
                'hash': 'a' * 40,
                'ratio_limit': -1,
                'seeding_time_limit': 20160,
                'inactive_seeding_time_limit': -1,
            }],
        ]
        with patch.object(qbittorrent, 'get_client', return_value=client):
            preserved = qbittorrent.preserve_rejected_torrent(
                'a' * 40, {'seed_duration': 20160}
            )

        self.assertTrue(preserved)
        client._post.assert_called_once_with(
            'torrents/setShareLimits',
            {
                'hashes': 'a' * 40,
                'ratioLimit': '-1',
                'seedingTimeLimit': '20160',
                'inactiveSeedingTimeLimit': '-1',
            },
        )

    def test_unrepairable_add_retains_hash_and_never_enables_force_start(self):
        client = Mock()
        client.get_torrent.return_value = {'hash': 'a' * 40}
        client.torrents.return_value = [{
            'hash': 'a' * 40,
            'ratio_limit': -1,
            'seeding_time_limit': 20160,
            'inactive_seeding_time_limit': -2,
            'state': 'stoppedUP',
            'force_start': False,
        }]
        with (
            patch.object(qbittorrent, 'CONFIG', self.config),
            patch.object(qbittorrent, 'get_client', return_value=client),
            patch.object(qbittorrent.time, 'sleep'),
        ):
            success, warning = qbittorrent.add_torrent(
                'https://tracker.invalid/file',
                'a' * 40,
                {'seed_duration': 20160},
            )

        self.assertTrue(success)
        self.assertTrue(warning.startswith(qbittorrent.POLICY_QUARANTINE_PREFIX))
        self.assertEqual(client.torrents.call_count, 21)
        self.assertIn(
            call(
                'torrents/addTags',
                {'hashes': 'a' * 40, 'tags': 'll-policy-quarantine'},
            ),
            client._post.call_args_list,
        )
        self.assertIn(
            call(
                'torrents/setForceStart',
                {'hashes': 'a' * 40, 'value': 'false'},
            ),
            client._post.call_args_list,
        )
        self.assertNotIn(
            call(
                'torrents/setForceStart',
                {'hashes': 'a' * 40, 'value': 'true'},
            ),
            client._post.call_args_list,
        )

    def test_helper_lifecycle_owner_suppresses_torrent_and_payload_deletion(self):
        for remove_data in (False, True):
            with (
                self.subTest(remove_data=remove_data),
                patch.dict(
                    'os.environ',
                    {
                        box_helper_handoff.BOX_HELPER_HANDOFF_PROTOCOL_ENV:
                            box_helper_handoff.BOX_HELPER_HANDOFF_PROTOCOL,
                        box_helper_handoff.QBITTORRENT_LIFECYCLE_OWNER_ENV: 'helper',
                    },
                    clear=True,
                ),
                patch.object(qbittorrent, 'get_client') as get_client,
            ):
                removed = qbittorrent.remove_torrent('A' * 40, remove_data)

            self.assertFalse(removed)
            get_client.assert_not_called()

    def test_invalid_external_lifecycle_owner_fails_closed(self):
        with (
            patch.dict(
                'os.environ',
                {
                    box_helper_handoff.BOX_HELPER_HANDOFF_PROTOCOL_ENV:
                        box_helper_handoff.BOX_HELPER_HANDOFF_PROTOCOL,
                    box_helper_handoff.QBITTORRENT_LIFECYCLE_OWNER_ENV: 'typo',
                },
                clear=True,
            ),
            patch.object(qbittorrent, 'get_client') as get_client,
        ):
            removed = qbittorrent.remove_torrent('a' * 40, True)

        self.assertFalse(removed)
        get_client.assert_not_called()

    def test_durable_handoff_requires_exact_helper_owner(self):
        invalid = (
            {},
            {
                box_helper_handoff.BOX_HELPER_HANDOFF_PROTOCOL_ENV:
                    box_helper_handoff.BOX_HELPER_HANDOFF_PROTOCOL,
            },
            {
                box_helper_handoff.BOX_HELPER_HANDOFF_PROTOCOL_ENV:
                    box_helper_handoff.BOX_HELPER_HANDOFF_PROTOCOL,
                box_helper_handoff.QBITTORRENT_LIFECYCLE_OWNER_ENV: '',
            },
            {
                box_helper_handoff.BOX_HELPER_HANDOFF_PROTOCOL_ENV:
                    box_helper_handoff.BOX_HELPER_HANDOFF_PROTOCOL,
                box_helper_handoff.QBITTORRENT_LIFECYCLE_OWNER_ENV: 'lazylibrarian',
            },
            {
                box_helper_handoff.QBITTORRENT_LIFECYCLE_OWNER_ENV: 'helper',
            },
        )
        for env in invalid:
            with self.subTest(env=env), patch.dict('os.environ', env, clear=True):
                with self.assertRaises(RuntimeError):
                    box_helper_handoff.validate_box_helper_handoff_config()
                self.assertTrue(
                    box_helper_handoff.helper_owns_qbittorrent_lifecycle()
                )

    def test_exact_durable_handoff_pair_passes_startup_validation(self):
        env = {
            box_helper_handoff.BOX_HELPER_HANDOFF_PROTOCOL_ENV:
                box_helper_handoff.BOX_HELPER_HANDOFF_PROTOCOL,
            box_helper_handoff.QBITTORRENT_LIFECYCLE_OWNER_ENV: 'helper',
        }
        with patch.dict('os.environ', env, clear=True):
            self.assertIsNone(
                box_helper_handoff.validate_box_helper_handoff_config()
            )
            self.assertTrue(box_helper_handoff.helper_owns_qbittorrent_lifecycle())

    def test_download_client_delete_task_obeys_helper_lifecycle_owner(self):
        env = {
            box_helper_handoff.BOX_HELPER_HANDOFF_PROTOCOL_ENV:
                box_helper_handoff.BOX_HELPER_HANDOFF_PROTOCOL,
            box_helper_handoff.QBITTORRENT_LIFECYCLE_OWNER_ENV: 'helper',
        }
        with (
            patch.dict('os.environ', env, clear=True),
            patch.object(qbittorrent, 'get_client') as get_client,
        ):
            download_client.delete_task('QBITTORRENT', 'a' * 40, True)

        get_client.assert_not_called()

    def test_missing_ownership_config_fails_closed_before_qbittorrent_client(self):
        with (
            patch.dict('os.environ', {}, clear=True),
            patch.object(qbittorrent, 'get_client') as get_client,
        ):
            with self.assertRaises(RuntimeError):
                box_helper_handoff.validate_box_helper_handoff_config()
            removed = qbittorrent.remove_torrent('a' * 40, True)

        self.assertFalse(removed)
        get_client.assert_not_called()


if __name__ == '__main__':
    import unittest
    unittest.main()
