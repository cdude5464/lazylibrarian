import tempfile
import sqlite3
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

from lazylibrarian import annas, searchbook, resultlist
from lazylibrarian import anna_download_policy as policy


class Config(dict):
    def get_int(self, name): return int(self.get(name, 0))
    def get_bool(self, name): return bool(self.get(name, False))
    def set_int(self, name, value): self[name] = value
    def total_active_providers(self): return 1
    def use_direct(self): return True
    def use_nzb(self): return False
    def use_tor(self): return False
    def use_rss(self): return False
    def use_irc(self): return False


def response(status, payload=None, content=b''):
    r = Mock(status_code=status, content=content)
    r.json.return_value = payload
    return r


class AnnaApiRecoveryTest(TestCase):
    def setUp(self):
        self.config = Config(ANNA_HOST='https://annas-archive.gl,https://annas-archive.pk',
                             ANNA_KEY='SENTINEL_SECRET', ANNA_MAX_SERVERS=3, BLOCKLIST_TIMER=300)

    def test_missing_partner_path_is_file_scoped_and_does_not_consume_quota(self):
        r = response(400, {'error': 'Invalid domain_index or path_index'})
        with (patch.object(annas, 'CONFIG', self.config), patch.object(annas, 'get', return_value=r) as get,
              patch.object(annas, 'block_annas') as quota,
              patch.object(annas.BLOCKHANDLER, 'block_provider') as block,
              patch.dict(annas.lazylibrarian.TIMERS, ANNA_REMAINING=12)):
            ok, error = annas.annas_download('a'*32, '', 'Book', '.epub')
            self.assertEqual(annas.lazylibrarian.TIMERS['ANNA_REMAINING'], 12)
        self.assertFalse(ok)
        self.assertEqual(error, policy.ANNA_PARTNER_UNAVAILABLE)
        self.assertNotIn('subscription', error.lower())
        self.assertEqual(get.call_count, 1)
        self.assertNotIn('domain_index', get.call_args.kwargs['params'])
        quota.assert_not_called()
        block.assert_not_called()

    def test_authentication_stops_requests_without_faking_quota_exhaustion(self):
        for status in (401, 403):
            with self.subTest(status=status):
                with (patch.object(annas, 'CONFIG', self.config),
                      patch.object(annas, 'get', return_value=response(status, {'error':'SENTINEL_SECRET'})) as get,
                      patch.object(annas, 'block_annas') as quota,
                      patch.object(annas.BLOCKHANDLER, 'block_provider') as block,
                      patch.dict(annas.lazylibrarian.TIMERS, ANNA_REMAINING=12)):
                    ok, error = annas.annas_download('a'*32, '', 'Book', '.epub')
                    self.assertEqual(annas.lazylibrarian.TIMERS['ANNA_REMAINING'], 12)
                self.assertFalse(ok)
                self.assertIn(error, policy.ANNA_AUTH_FAILURES)
                self.assertNotIn('SENTINEL_SECRET', error)
                self.assertEqual(get.call_count, 1)
                block.assert_called_once_with('annas', error, delay=300)
                quota.assert_not_called()

    def test_unknown_api_error_never_echoes_body_or_signed_url(self):
        r = response(400, {'error':'https://evil.invalid/?key=SENTINEL_SECRET'})
        with (patch.object(annas, 'CONFIG', self.config), patch.object(annas, 'get', return_value=r),
              self.assertLogs('lazylibrarian.annas', level='ERROR') as logs):
            ok, error = annas.annas_download('a'*32, '', 'Book', '.epub')
        self.assertFalse(ok)
        self.assertEqual(error, 'Anna file API request failed (HTTP 400)')
        self.assertNotIn('SENTINEL_SECRET', error+str(logs.output))

    def test_success_keeps_file_bytes_and_does_not_send_key_to_file_server(self):
        data = b'file bytes'*100
        api = response(200, {'account_fast_download_info':{'downloads_per_day':50,'downloads_left':12},
                             'download_url':'https://files.invalid/payload?signature=SENTINEL_SECRET'})
        with tempfile.TemporaryDirectory() as tmp:
            with (patch.object(annas, 'CONFIG', self.config),
                  patch.object(annas, 'get', side_effect=[api,response(200,content=data)]) as get,
                  patch.object(annas, 'get_directory', return_value=tmp),
                  patch.object(annas, 'annas_hosts_prefer')):
                ok, filename = annas.annas_download('a'*32, 'Book', 'Book', '.epub')
            self.assertTrue(ok)
            self.assertEqual(Path(filename).read_bytes(), data)
            self.assertEqual(set(get.call_args_list[1].kwargs), {'timeout'})


class AnnaCooldownTest(TestCase):
    def row(self, **extra):
        return dict(Status='Failed',NZBprov='annas',DLResult=policy.ANNA_PARTNER_UNAVAILABLE,
                    completed=1000,**extra)

    def test_six_hour_boundary(self):
        self.assertFalse(policy.anna_file_retry_due(self.row(),1000+policy.ANNA_FILE_RETRY_SECONDS-1))
        self.assertTrue(policy.anna_file_retry_due(self.row(),1000+policy.ANNA_FILE_RETRY_SECONDS))

    def test_invalid_missing_future_timestamps_fail_closed(self):
        for timestamp in (None,'invalid',0,-1,float('nan'),float('inf'),100000):
            with self.subTest(timestamp=timestamp):
                row=self.row();row['completed']=timestamp
                self.assertFalse(policy.anna_file_retry_due(row,30000))

    def test_manual_content_and_other_provider_failures_are_not_retryable(self):
        for field,value in (('DLResult','Blocked by user'),('DLResult','Wrong author'),
                            ('DLResult','Blocked: '+policy.ANNA_PARTNER_UNAVAILABLE),
                            ('Status','Ignored'),('NZBprov','other')):
            with self.subTest(field=field,value=value):
                row=self.row();row[field]=value
                self.assertFalse(policy.anna_file_retry_due(row,30000))

    def test_resultlist_retries_only_aged_ebook_file_not_audio(self):
        with patch.object(policy.time,'time',return_value=30000):
            self.assertTrue(resultlist._failed_source_retryable(self.row(),'eBook'))
            self.assertFalse(resultlist._failed_source_retryable(self.row(),'AudioBook'))
        with patch.object(policy.time,'time',return_value=1001):
            self.assertFalse(resultlist._failed_source_retryable(self.row(),'eBook'))

    def test_file_api_gateway_failures_retry_after_cooldown(self):
        for status in (502, 503, 504, 404, 500):
            with self.subTest(status=status):
                row = self.row()
                row['DLResult'] = policy.anna_api_failure(status, None)
                boundary = row['completed'] + policy.ANNA_FILE_RETRY_SECONDS
                with patch.object(policy.time, 'time', return_value=boundary - 1):
                    self.assertFalse(resultlist._failed_source_retryable(row, 'eBook'))
                with patch.object(policy.time, 'time', return_value=boundary):
                    self.assertEqual(resultlist._failed_source_retryable(row, 'eBook'),
                                     status in (502, 503, 504))
                    self.assertFalse(resultlist._failed_source_retryable(row, 'AudioBook'))


class AnnaCandidateFallbackTest(TestCase):
    def setUp(self):
        self.book={'bookid':'42','library':'eBook','bookName':'Book','authorName':'Author'}
        self.config=Config(MATCH_RATIO=85,PRIORITY_WEIGHT=0)

    def candidate(self, identifier, score=100):
        return [score,{'NZBprov':'annas','NZBmode':'direct','NZBtitle':'Author Book.epub',
                      'BookID':'42','AuxInfo':'eBook'},
                {'NZBurl':identifier},5,0]

    def pool(self, *identifiers):
        return ([{'tor_prov':'annas','tor_url':x} for x in identifiers],self.book,'book')

    def run_matches(self, initial, pool, outcomes, matcher, states=None, blocked=None):
        db=Mock();db.match.side_effect=states or [{'Status':'Wanted'}]*5
        with (patch.object(searchbook,'CONFIG',self.config),
              patch.object(searchbook.database,'DBConnection',return_value=db),
              patch.object(searchbook.BLOCKHANDLER,'is_blocked',side_effect=blocked or (lambda _:False)),
              patch.object(searchbook,'download_result',side_effect=outcomes) as download,
              patch.object(searchbook,'find_best_result',side_effect=matcher) as best):
            result=searchbook._download_candidate_matches(initial,self.book,pool)
        return result,download,best

    def test_next_file_is_revalidated_and_downloaded_in_same_cycle(self):
        result,download,best=self.run_matches([self.candidate('a')],self.pool('a','A','b'),[0,2],
                                              lambda *_:self.candidate('b',99))
        self.assertEqual(result,2)
        self.assertEqual(download.call_count,2)
        self.assertEqual(best.call_args.args[0],[{'tor_prov':'annas','tor_url':'b'}])

    def test_success_never_attempts_alternatives(self):
        result,download,best=self.run_matches([self.candidate('a')],self.pool('a','b'),[2],lambda *_:None)
        self.assertEqual(result,2)
        best.assert_not_called()

    def test_rejected_alternative_is_not_downloaded(self):
        result,download,best=self.run_matches([self.candidate('a')],self.pool('a','blocked'),[0],lambda *_:None)
        self.assertEqual(result,0)
        self.assertEqual(download.call_count,1)

    def test_quota_or_auth_block_prevents_poisoning_unused_candidates(self):
        # The first attempt sets a provider block. No second source is attempted.
        checks=iter([False,True])
        result,download,best=self.run_matches([self.candidate('a')],self.pool('a','b'),[0],lambda *_:None,
                                              blocked=lambda _:next(checks))
        self.assertEqual(download.call_count,1)
        best.assert_not_called()

    def test_fallback_stops_if_user_changes_wanted_status(self):
        result,download,best=self.run_matches([self.candidate('a')],self.pool('a','b'),[0],
                                              lambda *_:self.candidate('b'),
                                              states=[{'Status':'Wanted'},{'Status':'Ignored'}])
        self.assertEqual(result,1)
        self.assertEqual(download.call_count,1)

    def test_at_most_three_distinct_files_per_book(self):
        def next_best(pool,*_):return self.candidate(pool[0]['tor_url'])
        result,download,best=self.run_matches([self.candidate('a')],self.pool('a','b','c','d'),[0,0,0],next_best)
        self.assertEqual(result,0)
        self.assertEqual(download.call_count,3)

    def test_auth_failure_stops_even_with_disabled_timed_provider_blocks(self):
        db=Mock()
        db.match.side_effect=lambda query,*_: {'Status':'Wanted'} if query.startswith('SELECT Status') else None
        self.config['BLOCKLIST_TIMER']=0
        with (patch.object(searchbook,'CONFIG',self.config),
              patch.object(searchbook.database,'DBConnection',return_value=db),
              patch.object(searchbook.BLOCKHANDLER,'is_blocked',return_value=False),
              patch.object(resultlist,'direct_dl_method',return_value=(False,next(iter(policy.ANNA_AUTH_FAILURES)))),
              patch.object(searchbook,'download_result',wraps=resultlist.download_result) as download,
              patch.object(searchbook,'find_best_result') as best):
            result=searchbook._download_candidate_matches([self.candidate('a')],self.book,self.pool('a','b'))
        self.assertEqual(result,0)
        self.assertEqual(download.call_count,1)
        self.assertEqual(db.upsert.call_count,1)
        best.assert_not_called()


class AnnaManualFailureShadowTest(TestCase):
    def test_manual_or_content_failure_shadows_retryable_same_md5_in_any_row_order(self):
        for order in (False,True):
            for reason in ('Blocked by user','Embedded ebook metadata identifies a different book'):
                with self.subTest(reverse=order,reason=reason):
                    connection=sqlite3.connect(':memory:');connection.row_factory=sqlite3.Row
                    self.addCleanup(connection.close)
                    connection.execute('CREATE TABLE wanted (BookID,NZBurl,NZBprov,Status,DLResult,completed)')
                    rows=[('42','a'*32,'annas','Failed',policy.ANNA_PARTNER_UNAVAILABLE,1000),
                          ('another-book','A'*32,'annas','Failed',reason,1000)]
                    connection.executemany('INSERT INTO wanted VALUES (?,?,?,?,?,?)',list(reversed(rows)) if order else rows)
                    db=Mock();db.select.side_effect=lambda query,args:connection.execute(query,args).fetchall()
                    with patch.object(policy.time,'time',return_value=30000):
                        self.assertTrue(resultlist._anna_failure_blocks(db,'a'*32,'eBook'))

    def test_only_retryable_failures_allow_same_file_again(self):
        db=Mock();db.select.return_value=[{'NZBprov':'annas','Status':'Failed',
                         'DLResult':policy.ANNA_PARTNER_UNAVAILABLE,'completed':1000}]
        with patch.object(policy.time,'time',return_value=30000):
            self.assertFalse(resultlist._anna_failure_blocks(db,'a'*32,'eBook'))


class AnnaBackoffRecoveryTest(TestCase):
    def test_mature_file_history_can_recover_despite_old_book_search_backoff(self):
        book={'BookID':'42','AuthorName':'Author','BookName':'Book','BookSub':'',
              'Status':'Wanted','AudioStatus':'Skipped'}
        db=Mock();db.select.return_value=[book]
        db.match.side_effect=lambda query,*_: {'Count':0,'Interval':99} if 'failedsearch' in query else None
        candidate={'tor_prov':'annas','tor_url':'a'*32}
        match=[100,{'NZBprov':'annas','NZBtitle':'Author Book.epub'},{'NZBurl':'a'*32},5,0]
        config=Config(DELAYSEARCH=True,ANNA=True,MATCH_RATIO=85)
        with (patch.object(searchbook,'CONFIG',config),
              patch.object(searchbook.database,'DBConnection',return_value=db),
              patch.object(searchbook,'thread_name',return_value='SEARCHBOOKS'),
              patch.object(searchbook.BLOCKHANDLER,'is_blocked',return_value=False),
              patch.object(searchbook,'retryable_anna_history_candidates',return_value=[candidate]) as history,
              patch.object(searchbook,'find_best_result',return_value=match),
              patch.object(searchbook,'iterate_over_direct_sites') as searches,
              patch.object(searchbook,'_download_candidate_matches',return_value=2) as downloads):
            searchbook.search_book(books=[{'bookid':'42'}],library='eBook')
        history.assert_called_once()
        self.assertTrue(history.call_args.kwargs['due_only'])
        searches.assert_not_called()
        downloads.assert_called_once()
        self.assertIn('DELETE from failedsearch',db.action.call_args.args[0])
