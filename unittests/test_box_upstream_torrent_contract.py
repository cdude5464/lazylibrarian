"""Exact helper ownership around upstream's canonical-id/adoption add API."""
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

from lazylibrarian import downloadmethods, qbittorrent


class MinimalConfig(dict):
    def get_bool(self, key):
        return bool(self.get(key, False))
    def __getitem__(self, key):
        return self.get(key, '')


class BoxUpstreamTorrentContractTest(TestCase):
    def setUp(self):
        self.env = patch.dict('os.environ', {
            'BOX_LL_HANDOFF_PROTOCOL': 'box-qbit-durable-intent-v1',
            'BOX_LL_QBIT_LIFECYCLE_OWNER': 'helper',
        })
        self.env.start(); self.addCleanup(self.env.stop)
        self.config = MinimalConfig(QBITTORRENT_HOST='qbit.invalid',
                                    TOR_DOWNLOADER_QBITTORRENT=True,
                                    QBITTORRENT_LABEL='books')
        self.root = Path(__file__).parent / 'testdata' / 'torrents'

    def run_grab(self, data, *, existing=False, no_policy=False):
        events = []
        hashid = downloadmethods.calculate_torrent_hash('', data)
        client = Mock()
        client.get_torrent.return_value = {'hash': hashid} if existing else None
        limits = {'hash': hashid, 'ratio_limit': -1, 'seeding_time_limit': 20160,
                  'inactive_seeding_time_limit': -1}
        client.torrents.side_effect = lambda **kw: [limits] if existing or any(event[0] == 'add' for event in events) else []
        def added(*args, **kwargs):
            events.append(('add', hashid))
            client.get_torrent.return_value = {'hash': hashid}
            return {'success_count': 1, 'added_torrent_ids': [hashid]}
        client.download_from_file.side_effect = added
        db = Mock()
        response = Mock(status_code=200, content=data,
                        headers={'Content-Type': 'application/x-bittorrent'})
        with (
            patch.object(downloadmethods, 'CONFIG', self.config),
            patch.object(qbittorrent, 'CONFIG', self.config),
            patch.object(downloadmethods.requests, 'get', return_value=response),
            patch.object(downloadmethods, 'torrent_provider_options', return_value={} if no_policy else {'seed_duration': 20160}),
            patch.object(downloadmethods, 'seed_requirement', return_value=(0, 0)),
            patch.object(downloadmethods, 'previously_rejected_archive', return_value=False),
            patch.object(downloadmethods, 'check_contents', return_value=''),
            patch.object(downloadmethods, 'record_usage_data'),
            patch.object(downloadmethods.database, 'DBConnection', return_value=db),
            patch.object(downloadmethods, 'use_label', return_value='books'),
            patch.object(downloadmethods, 'emit_box_helper_spool', side_effect=lambda hid, title, bid, lib, prov, phase, **kw: events.append((phase, hid))),
            patch.object(qbittorrent, 'get_client', return_value=client),
            patch.object(qbittorrent.time, 'sleep'),
        ):
            result = downloadmethods.tor_dl_method(
                bookid='book42', tor_title='Requested Work',
                tor_url='https://provider.invalid/release.torrent',
                provider='exact-provider', requested_author='Requested Author',
                requested_title='Requested Work')
        return result, events, client, db

    def test_v1_preserves_durable_order_and_upstream_origin_fields(self):
        result, events, client, db = self.run_grab((self.root/'v1.torrent').read_bytes())
        self.assertTrue(result[0], result)
        self.assertEqual([x[0] for x in events], ['intent', 'add', 'final'])
        self.assertEqual(len({x[1] for x in events}), 1)
        self.assertEqual(client.download_from_file.call_args.kwargs['inactiveSeedingTimeLimit'], -1)
        self.assertTrue(any('Origin=?,Category=?' in call.args[0] and
                            call.args[1][2:4] == ('new', 'books')
                            for call in db.action.call_args_list))

    def test_v2_and_hybrid_refused_before_intent_or_add(self):
        for name in ('v2', 'hybrid'):
            with self.subTest(format=name):
                result, events, client, db = self.run_grab((self.root/f'{name}.torrent').read_bytes())
                self.assertFalse(result[0])
                self.assertIn('Unsupported v2/hybrid', result[1])
                self.assertEqual(events, [])
                client.download_from_file.assert_not_called()
                db.action.assert_not_called()

    def test_existing_hash_is_not_adopted_or_mutated(self):
        result, events, client, db = self.run_grab((self.root/'v1.torrent').read_bytes(), existing=True)
        self.assertFalse(result[0])
        self.assertIn('pre-existing', result[1])
        self.assertEqual(events, [])
        client.download_from_file.assert_not_called()
        client._post.assert_not_called()
        db.action.assert_not_called()

    def test_missing_explicit_policy_does_not_add_or_emit_intent(self):
        result, events, client, db = self.run_grab((self.root/'v1.torrent').read_bytes(), no_policy=True)
        self.assertFalse(result[0])
        self.assertIn('explicit provider share policy', result[1])
        self.assertEqual(events, [])
        client.download_from_file.assert_not_called()

    def test_missing_owner_pair_fails_before_client(self):
        with patch.dict('os.environ', {}, clear=True), patch.object(qbittorrent, 'get_client') as client:
            result = qbittorrent.add_torrent('magnet:?xt=urn:btih:'+'a'*40, 'a'*40,
                                             {'seed_duration': 20160})
        self.assertFalse(result[0])
        self.assertIn('paired durable helper', result[1])
        client.assert_not_called()

    def test_post_add_alias_does_not_emit_false_canonical_success(self):
        client = Mock()
        with patch.object(qbittorrent, 'repair_provider_share_limits', return_value='') as repair, \
             patch.object(qbittorrent, 'quarantine_unverified_provider_torrent') as quarantine:
            result = qbittorrent.verify_provider_add_result(
                client, ('b'*40, '', False), {'seed_duration': 20160}, 'a'*40)
        self.assertFalse(result[0])
        self.assertIn('identity differs', result[1])
        quarantine.assert_not_called()
        repair.assert_not_called()
        client.assert_not_called()

    def test_unexpected_add_response_is_not_paused_repaired_or_quarantined(self):
        client = Mock()
        client.download_from_link.return_value = {
            'success_count': 1, 'added_torrent_ids': ['b'*40]}
        config = MinimalConfig(TORRENT_PAUSED=True, QBITTORRENT_LABEL='books')
        with (
            patch.object(qbittorrent, 'CONFIG', config),
            patch.object(qbittorrent, 'get_client', return_value=client),
            patch.object(qbittorrent, 'helper_add_preflight', return_value=''),
            patch.object(qbittorrent, 'repair_provider_share_limits') as repair,
            patch.object(qbittorrent, 'quarantine_unverified_provider_torrent') as quarantine,
        ):
            result = qbittorrent.add_torrent('magnet:?xt=urn:btih:'+'a'*40,
                                             'a'*40, {'seed_duration': 20160})
        self.assertFalse(result[0])
        self.assertIn('identity differs', result[1])
        client.get_torrent.assert_not_called()
        client.pause.assert_not_called()
        client._post.assert_not_called()
        repair.assert_not_called()
        quarantine.assert_not_called()

    def test_legacy_full_scan_foreign_alias_is_not_paused(self):
        client = Mock()
        client.get_torrent.return_value = None
        with (
            patch.object(qbittorrent, 'QBIT_ADD_POLL_SECONDS', 1),
            patch.object(qbittorrent.time, 'sleep'),
            patch.object(qbittorrent, 'find_torrent', return_value={'hash': 'b'*40}),
        ):
            result = qbittorrent.wait_for_torrent(client, Mock(), 'a'*40, 'Ok.', 'add_file')
        self.assertFalse(result[0])
        client.pause.assert_not_called()
        client._post.assert_not_called()
