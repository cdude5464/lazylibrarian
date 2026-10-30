#  This file is part of Lazylibrarian.
#
# Purpose:
#   Issue #3114: tell the user what changed since the version they last saw.
#   Docker and source installs get a new version from outside, so the update check
#   finds nothing; whatsnew compares the running version with WHATS_NEW_SEEN.

import os
from unittest import mock

import lazylibrarian
from lazylibrarian import whatsnew
from unittests.unittesthelpers import LLTestCase

OLD = 'a' * 40
NEW = 'b' * 40


def commit(sha, title, parents=1, author='Phil Borman', date='2026-10-25T10:00:00.000+00:00'):
    return {'id': sha, 'short_id': sha[:8], 'title': title, 'author_name': author,
            'committed_date': date, 'parent_ids': ['p'] * parents}


class FakeConfig(dict):
    def get_int(self, key):
        return int(self.get(key) or 0)

    def get_bool(self, key):
        return bool(self.get(key))

    def set_str(self, key, value):
        self[key] = value


def config(**kwargs):
    cfg = FakeConfig(CURRENT_VERSION=NEW, WHATS_NEW_SEEN=OLD, GIT_HOST='gitlab.com', GIT_USER='LazyLibrarian',
                     GIT_REPO='lazylibrarian', GIT_PROJECT='9317860', GIT_BRANCH='master', HTTP_TIMEOUT=30,
                     SSL_VERIFY=True, SSL_CERTS='')
    cfg.update(kwargs)
    cfg.save_config_and_backup_old = mock.Mock(return_value=1)
    return cfg


class WhatsNewTest(LLTestCase):

    def setUp(self):
        super().setUp()
        lazylibrarian.WHATS_NEW = []
        whatsnew._checked.clear()
        whatsnew._page_cache.clear()
        whatsnew._changes_cache.clear()
        # no git and no changes.json unless a test gives one, so the gitlab api path is what runs
        no_git = mock.patch.object(whatsnew, 'git_commits', return_value=None)
        self.git = no_git.start()
        self.addCleanup(no_git.stop)
        self.no_pages = mock.patch.object(whatsnew, 'published_changes', return_value=None)
        self.pages = self.no_pages.start()
        self.addCleanup(mock.patch.stopall)

    def tearDown(self):
        lazylibrarian.WHATS_NEW = []
        super().tearDown()

    def test_keep_commits_drops_merges_translations_and_ci(self):
        commits = [
            commit('1' * 40, 'Fix series numbers in long titles'),
            commit('2' * 40, "Merge branch 'fix/x' into 'master'", parents=2),
            commit('3' * 40, 'chore(l10n): update translation files'),
            commit('4' * 40, 'ci: regenerate lazylibrarian.pot automatically'),
            commit('5' * 40, 'i18n: update lazylibrarian.pot (refs #3109)'),
            commit('6' * 40, 'Translated using Weblate (Slovak)'),
            commit('7' * 40, 'i18n: translate the Config page (refs #3109)'),
        ]
        kept = whatsnew.keep_commits(commits)
        # newest first, user visible translation work stays
        self.assertEqual([c['title'] for c in kept],
                         ['i18n: translate the Config page (refs #3109)', 'Fix series numbers in long titles'])
        self.assertEqual(kept[0]['date'], '2026-10-25')
        self.assertEqual(kept[0]['short_id'], '77777777')

    def test_merge_title_without_two_parents_is_dropped(self):
        # "Merge remote-tracking branch" commits on master
        self.assertEqual(whatsnew.keep_commits([commit('1' * 40, "Merge remote-tracking branch 'origin/master'")]),
                         [])

    def test_link_title_escapes_and_links(self):
        with mock.patch.object(whatsnew, 'CONFIG', config()):
            text = whatsnew.link_title('Fix <b>x</b> & "y" (#3103, !1952)')
        self.assertIn('&lt;b&gt;x&lt;/b&gt; &amp; &quot;y&quot;', text)
        self.assertIn('href="https://gitlab.com/LazyLibrarian/lazylibrarian/-/issues/3103"', text)
        self.assertIn('href="https://gitlab.com/LazyLibrarian/lazylibrarian/-/merge_requests/1952"', text)
        # the entities from escaping are not issue numbers, a hash inside a word isn't either
        with mock.patch.object(whatsnew, 'CONFIG', config()):
            self.assertNotIn('<a', whatsnew.link_title("Don't split 'C#12' names"))

    def test_new_install_marks_seen_quietly(self):
        cfg = config(WHATS_NEW_SEEN='')
        with mock.patch.object(whatsnew, 'CONFIG', cfg), mock.patch.object(whatsnew, 'compare') as cmp:
            whatsnew.check_whats_new()
        cmp.assert_not_called()
        self.assertEqual(cfg['WHATS_NEW_SEEN'], NEW)
        cfg.save_config_and_backup_old.assert_called_once()
        self.assertEqual(lazylibrarian.WHATS_NEW, [])

    def test_same_version_shows_nothing(self):
        cfg = config(WHATS_NEW_SEEN=NEW[:8])
        with mock.patch.object(whatsnew, 'CONFIG', cfg), mock.patch.object(whatsnew, 'compare') as cmp:
            whatsnew.check_whats_new()
        cmp.assert_not_called()
        self.assertEqual(lazylibrarian.WHATS_NEW, [])

    def test_unknown_version_shows_nothing(self):
        cfg = config(CURRENT_VERSION='Missing Version file')
        with mock.patch.object(whatsnew, 'CONFIG', cfg), mock.patch.object(whatsnew, 'compare') as cmp:
            whatsnew.check_whats_new()
        cmp.assert_not_called()
        self.assertEqual(cfg['WHATS_NEW_SEEN'], OLD)

    def test_new_version_lists_changes(self):
        cfg = config()
        commits = [commit('1' * 40, 'First fix'), commit('2' * 40, 'Second fix')]
        with mock.patch.object(whatsnew, 'CONFIG', cfg), \
                mock.patch.object(whatsnew, 'compare', return_value=commits) as cmp:
            whatsnew.check_whats_new()
            cmp.assert_called_once_with(OLD, NEW)
            self.assertEqual([c['title'] for c in lazylibrarian.WHATS_NEW], ['Second fix', 'First fix'])
            # not seen until the user dismisses it
            self.assertEqual(cfg['WHATS_NEW_SEEN'], OLD)
            # the next version check doesn't ask gitlab again for the same versions
            whatsnew.check_whats_new()
            cmp.assert_called_once()

    def test_closed_while_comparing_keeps_it_closed(self):
        cfg = config()

        def close_popup(*args):
            cfg['WHATS_NEW_SEEN'] = NEW
            return [commit('1' * 40, 'A fix')]

        with mock.patch.object(whatsnew, 'CONFIG', cfg), mock.patch.object(whatsnew, 'compare', side_effect=close_popup):
            whatsnew.check_whats_new()
        self.assertEqual(lazylibrarian.WHATS_NEW, [])

    def test_gitlab_unreachable_tries_again(self):
        cfg = config()
        lazylibrarian.WHATS_NEW = [{'id': 'x'}]
        with mock.patch.object(whatsnew, 'CONFIG', cfg), \
                mock.patch.object(whatsnew, 'compare', return_value=None) as cmp:
            whatsnew.check_whats_new()
            whatsnew.check_whats_new()
        self.assertEqual(cmp.call_count, 2)
        self.assertEqual(lazylibrarian.WHATS_NEW, [{'id': 'x'}])
        self.assertEqual(cfg['WHATS_NEW_SEEN'], OLD)

    def test_nothing_worth_showing_marks_seen(self):
        # a rollback gives no commits, a translation only update gives nothing to show
        for commits in ([], [commit('1' * 40, 'chore(l10n): update translation files')]):
            cfg = config()
            whatsnew._checked.clear()
            with mock.patch.object(whatsnew, 'CONFIG', cfg), \
                    mock.patch.object(whatsnew, 'compare', return_value=commits):
                whatsnew.check_whats_new()
            self.assertEqual(cfg['WHATS_NEW_SEEN'], NEW)
            self.assertEqual(lazylibrarian.WHATS_NEW, [])

    def test_mark_seen(self):
        cfg = config()
        lazylibrarian.WHATS_NEW = [{'id': 'x'}]
        with mock.patch.object(whatsnew, 'CONFIG', cfg):
            whatsnew.mark_seen()
            self.assertEqual(cfg['WHATS_NEW_SEEN'], NEW)
            self.assertEqual(lazylibrarian.WHATS_NEW, [])
            # already seen, no need to save again
            whatsnew.mark_seen()
        cfg.save_config_and_backup_old.assert_called_once()

    def test_popup_left_open_across_an_update_does_not_mark_the_new_version(self):
        # a tab showing the popup for OLD, closed after the server was updated to NEW
        cfg = config(WHATS_NEW_SEEN='c' * 40)
        lazylibrarian.WHATS_NEW = [{'id': 'x'}]
        with mock.patch.object(whatsnew, 'CONFIG', cfg):
            whatsnew.mark_seen(OLD)
            self.assertEqual(cfg['WHATS_NEW_SEEN'], 'c' * 40)
            self.assertEqual(lazylibrarian.WHATS_NEW, [{'id': 'x'}])
            whatsnew.mark_seen(NEW[:8])
            self.assertEqual(cfg['WHATS_NEW_SEEN'], NEW)
            self.assertEqual(lazylibrarian.WHATS_NEW, [])
        cfg.save_config_and_backup_old.assert_called_once()

    def test_repo_url_is_escaped(self):
        with mock.patch.object(whatsnew, 'CONFIG', config(GIT_USER='a"><b')):
            text = whatsnew.link_title('Fix #3103')
        self.assertIn('href="https://gitlab.com/a&quot;&gt;&lt;b/lazylibrarian/-/issues/3103"', text)
        page = os.path.join(os.path.dirname(__file__), '..', 'data', 'interfaces', 'bookstrap', 'whatsnew.html')
        with open(page, encoding='utf-8') as f:
            self.assertNotIn('href="${repo}', f.read())

    def test_compare_needs_a_commit_list(self):
        with mock.patch.object(whatsnew, 'gitlab_get', return_value={'message': '404 Not Found'}):
            self.assertIsNone(whatsnew.compare(OLD, NEW))
        with mock.patch.object(whatsnew, 'gitlab_get', return_value=None):
            self.assertIsNone(whatsnew.compare(OLD, NEW))
        with mock.patch.object(whatsnew, 'gitlab_get', return_value={'commits': []}) as get:
            self.assertEqual(whatsnew.compare(OLD, NEW), [])
        get.assert_called_once_with('repository/compare', {'from': OLD, 'to': NEW})

    def test_gitlab_get_failures_return_none(self):
        with mock.patch.object(whatsnew, 'CONFIG', config()):
            with mock.patch.object(whatsnew.requests, 'get', return_value=mock.Mock(status_code=404)):
                self.assertIsNone(whatsnew.gitlab_get('repository/compare'))
            with mock.patch.object(whatsnew.requests, 'get', side_effect=OSError('down')):
                self.assertIsNone(whatsnew.gitlab_get('repository/compare'))
            ok = mock.Mock(status_code=200)
            ok.json.return_value = [1]
            with mock.patch.object(whatsnew.requests, 'get', return_value=ok) as get:
                self.assertEqual(whatsnew.gitlab_get('repository/commits', {'ref_name': 'master'}), [1])
        self.assertEqual(get.call_args.args[0], 'https://gitlab.com/api/v4/projects/9317860/repository/commits')
        self.assertEqual(get.call_args.kwargs['params'], {'ref_name': 'master'})

    def test_recent_changes_splits_installed(self):
        recent = [commit('3' * 40, 'Not installed'), commit('2' * 40, "Merge branch 'x'", parents=2),
                  commit(NEW, 'Running version'), commit('1' * 40, 'Older')]
        with mock.patch.object(whatsnew, 'CONFIG', config()), \
                mock.patch.object(whatsnew, 'gitlab_get', return_value=recent) as get, \
                mock.patch.object(whatsnew, 'compare', return_value=[recent[0], recent[1]]) as cmp:
            data = whatsnew.recent_changes()
            # cached for the page
            self.assertIs(whatsnew.recent_changes(), data)
        get.assert_called_once_with('repository/commits', {'ref_name': 'master', 'per_page': 100})
        cmp.assert_called_once_with(NEW, 'master')
        self.assertFalse(data['error'])
        self.assertEqual([c['title'] for c in data['upcoming']], ['Not installed'])
        self.assertEqual([c['title'] for c in data['installed']], ['Running version', 'Older'])

    def test_recent_changes_unknown_version(self):
        with mock.patch.object(whatsnew, 'CONFIG', config(CURRENT_VERSION='No Version File')), \
                mock.patch.object(whatsnew, 'gitlab_get', return_value=[commit('1' * 40, 'A fix')]), \
                mock.patch.object(whatsnew, 'compare') as cmp:
            data = whatsnew.recent_changes()
        cmp.assert_not_called()
        self.assertFalse(data['known'])
        self.assertEqual([c['title'] for c in data['installed']], ['A fix'])

    def test_recent_changes_error_is_not_cached(self):
        with mock.patch.object(whatsnew, 'CONFIG', config()), \
                mock.patch.object(whatsnew, 'gitlab_get', return_value=None) as get:
            self.assertTrue(whatsnew.recent_changes()['error'])
            self.assertTrue(whatsnew.recent_changes()['error'])
        self.assertEqual(get.call_count, 2)

    def test_local_branch_falls_back_to_master(self):
        recent = [commit(NEW, 'Running version')]
        with mock.patch.object(whatsnew, 'CONFIG', config(GIT_BRANCH='feature/local')), \
                mock.patch.object(whatsnew, 'gitlab_get', side_effect=[[], recent]) as get, \
                mock.patch.object(whatsnew, 'compare', return_value=[]) as cmp:
            data = whatsnew.recent_changes()
        self.assertEqual(get.call_args.args, ('repository/commits', {'ref_name': 'master', 'per_page': 100}))
        cmp.assert_called_once_with(NEW, 'master')
        self.assertEqual([c['title'] for c in data['installed']], ['Running version'])

    def test_package_installs_follow_master(self):
        with mock.patch.object(whatsnew, 'CONFIG', config(GIT_BRANCH='Package')):
            self.assertEqual(whatsnew.branch(), 'master')
        with mock.patch.object(whatsnew, 'CONFIG', config(GIT_BRANCH='')):
            self.assertEqual(whatsnew.branch(), 'master')

    def test_bell_has_a_label_in_the_phone_menu(self):
        # on small screens the header turns into a drop-down list, where a bare bell sits on its own row
        base = os.path.join(os.path.dirname(__file__), '..', 'data', 'interfaces', 'bookstrap', 'base.html')
        with open(base, encoding='utf-8') as f:
            page = f.read()
        bell = page[page.index('id="whatsnew"'):]
        bell = bell[:bell.index('</a>')]
        self.assertIn('<span class="visible-xs-inline">${_("What\'s new") | h}</span>', bell)

    def test_new_version_read_from_git(self):
        commits = [commit('1' * 40, 'Fix series numbers'), commit(NEW, 'Show the date in the date format')]
        self.git.return_value = [commits]
        with mock.patch.object(whatsnew, 'CONFIG', config()), \
                mock.patch.object(whatsnew, 'compare') as api:
            whatsnew.check_whats_new()
        self.git.assert_called_once_with(['--reverse', f'{OLD}..{NEW}'])
        api.assert_not_called()
        self.assertEqual([c['title'] for c in lazylibrarian.WHATS_NEW],
                         ['Show the date in the date format', 'Fix series numbers'])

    def test_api_used_without_git(self):
        with mock.patch.object(whatsnew, 'CONFIG', config()), \
                mock.patch.object(whatsnew, 'compare', return_value=[commit(NEW, 'From the api')]) as api:
            whatsnew.check_whats_new()
        api.assert_called_once_with(OLD, NEW)
        self.assertEqual([c['title'] for c in lazylibrarian.WHATS_NEW], ['From the api'])

    def test_recent_changes_from_git(self):
        upcoming = commit('c' * 40, 'Not installed yet')
        recent = [upcoming, commit(NEW, 'Running version'), commit(OLD, 'Older')]
        self.git.return_value = [recent, [upcoming]]
        with mock.patch.object(whatsnew, 'CONFIG', config()), \
                mock.patch.object(whatsnew, 'gitlab_get') as api:
            data = whatsnew.recent_changes()
        api.assert_not_called()
        self.git.assert_called_once_with(['-n', '100', 'FETCH_HEAD'], [f'{NEW}..FETCH_HEAD'], ref='master')
        self.assertEqual([c['title'] for c in data['upcoming']], ['Not installed yet'])
        self.assertEqual([c['title'] for c in data['installed']], ['Running version', 'Older'])
        self.assertEqual(data['branch'], 'master')

    def test_recent_changes_from_git_local_branch(self):
        self.git.side_effect = [None, [[commit(NEW, 'Running version')], []]]
        with mock.patch.object(whatsnew, 'CONFIG', config(GIT_BRANCH='feature/local')), \
                mock.patch.object(whatsnew, 'gitlab_get') as api:
            data = whatsnew.recent_changes()
        api.assert_not_called()
        self.assertEqual([c.kwargs['ref'] for c in self.git.call_args_list], ['feature/local', 'master'])
        self.assertEqual(data['branch'], 'master')

    def published(self, commits):
        return {'branch': 'master', 'latest': commits[0]['id'], 'commits': commits}

    def test_new_version_read_from_changes_json_without_git(self):
        commits = [commit(NEW, 'Show the date', parents=0), commit('1' * 40, 'Fix series numbers', parents=0),
                   commit(OLD, 'Seen already', parents=0)]
        commits[0]['parent_ids'], commits[1]['parent_ids'] = ['1' * 40], [OLD]
        self.pages.return_value = self.published(commits)
        with mock.patch.object(whatsnew, 'CONFIG', config()), \
                mock.patch.object(whatsnew, 'compare') as api:
            whatsnew.check_whats_new()
        api.assert_not_called()
        self.pages.assert_called_once_with('master')
        self.assertEqual([c['title'] for c in lazylibrarian.WHATS_NEW], ['Show the date', 'Fix series numbers'])

    def test_api_used_when_changes_json_does_not_list_the_version(self):
        self.pages.return_value = self.published([commit(NEW, 'Too recent for the seen version')])
        with mock.patch.object(whatsnew, 'CONFIG', config()), \
                mock.patch.object(whatsnew, 'compare', return_value=[commit(NEW, 'From the api')]) as api:
            whatsnew.check_whats_new()
        api.assert_called_once_with(OLD, NEW)

    def test_recent_changes_from_changes_json(self):
        upcoming = commit('c' * 40, 'Not installed yet')
        upcoming['parent_ids'] = [NEW]
        running = commit(NEW, 'Running version')
        running['parent_ids'] = [OLD]
        self.pages.return_value = self.published([upcoming, running, commit(OLD, 'Older', parents=0)])
        with mock.patch.object(whatsnew, 'CONFIG', config()), \
                mock.patch.object(whatsnew, 'gitlab_get') as api:
            data = whatsnew.recent_changes(count=2)
        api.assert_not_called()
        self.assertEqual([c['title'] for c in data['upcoming']], ['Not installed yet'])
        self.assertEqual([c['title'] for c in data['installed']], ['Running version'])

    def test_commits_between_follows_merges_like_git(self):
        # m merges side branch s1 into master after b; installed at b, so s1 and m are new,
        # older side commit s0 was merged before b and is installed
        a, s0, b, s1, m = ('a' * 40, '0' * 40, 'b' * 40, '1' * 40, 'f' * 40)
        graph = [{'id': m, 'parent_ids': [b, s1]}, {'id': s1, 'parent_ids': [s0]},
                 {'id': b, 'parent_ids': [a, s0]}, {'id': s0, 'parent_ids': [a]}, {'id': a, 'parent_ids': []}]
        self.assertEqual([c['id'] for c in whatsnew.commits_between(graph, b, m)], [s1, m])
        self.assertEqual([c['id'] for c in whatsnew.commits_between(graph, b[:8], m[:8])], [s1, m])
        self.assertEqual(whatsnew.commits_between(graph, m, m), [])
        self.assertIsNone(whatsnew.commits_between(graph, 'c' * 40, m))
        self.assertIsNone(whatsnew.commits_between(graph, 'No Version File', m))

    def test_published_changes_checked_and_cached(self):
        self.no_pages.stop()
        good = {'branch': 'master', 'latest': NEW,
                'commits': [commit(NEW, 'A fix'), 'junk', dict(commit(OLD, 'Bad parents'), parent_ids='p')]}
        with mock.patch.object(whatsnew, 'CONFIG', config()), \
                mock.patch.object(whatsnew, 'get_json', return_value=good) as get:
            data = whatsnew.published_changes('master')
            self.assertIsNone(whatsnew.published_changes('develop'))
        get.assert_called_once_with('https://lazylibrarian.gitlab.io/LazyLibrarian/changes.json')
        self.assertEqual([c['title'] for c in data['commits']], ['A fix'])
        for bad in (None, [], {'branch': 'master'}, {'branch': 'master', 'latest': 'HEAD', 'commits': []}):
            whatsnew._changes_cache.clear()
            with mock.patch.object(whatsnew, 'CONFIG', config()), \
                    mock.patch.object(whatsnew, 'get_json', return_value=bad):
                self.assertIsNone(whatsnew.published_changes('master'))
        for fork in (config(GIT_HOST='git.example.com'), config(GIT_USER='someone')):
            with mock.patch.object(whatsnew, 'CONFIG', fork):
                self.assertEqual(whatsnew.changes_url(), '')
