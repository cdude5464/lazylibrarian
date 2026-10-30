#  This file is part of Lazylibrarian.
#
# Purpose:
#   The update check reads the latest commit and the commit titles with the git command line.
#   A configured git program, package installs and installs without git must not break it.

import os
import subprocess
from unittest import mock

from lazylibrarian import versioncheck
from unittests.unittesthelpers import LLTestCase

CURRENT = 'a' * 40
LATEST = 'b' * 40


class FakeConfig(dict):
    def get_int(self, key):
        return int(self.get(key) or 0)

    def get_bool(self, key):
        return bool(self.get(key))

    def set_str(self, key, value):
        self[key] = value

    def set_int(self, key, value):
        self[key] = value


def config(**kwargs):
    cfg = FakeConfig(GIT_PROGRAM='', GIT_HOST='gitlab.com', GIT_USER='LazyLibrarian', GIT_REPO='lazylibrarian',
                     GIT_BRANCH='master', INSTALL_TYPE='source', CURRENT_VERSION=CURRENT, LATEST_VERSION=LATEST)
    cfg.update(kwargs)
    return cfg


def git_ok(stdout=''):
    def run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout if cmd[1] == 'log' else '', stderr='')
    return run


class VersionCheckTest(LLTestCase):

    def test_git_program_is_not_quoted(self):
        # subprocess gets an argument list, quotes would become part of the file name
        with mock.patch.object(versioncheck, 'CONFIG', config(GIT_PROGRAM='/opt/my git/git')), \
                mock.patch.object(versioncheck.platform, 'system', return_value='Linux'):
            self.assertEqual(versioncheck.git_programs(), ['/opt/my git/git'])
        with mock.patch.object(versioncheck, 'CONFIG', config()), \
                mock.patch.object(versioncheck.platform, 'system', return_value='Darwin'):
            self.assertEqual(versioncheck.git_programs(), ['git', '/usr/local/git/bin/git'])

    def test_remote_url_and_branch_from_config(self):
        with mock.patch.object(versioncheck, 'CONFIG', config(GIT_USER='someone', GIT_REPO='fork')):
            self.assertEqual(versioncheck.git_remote_url(), 'https://gitlab.com/someone/fork.git/')
        for branch, expected in (('Package', 'master'), ('', 'master'), ('dev', 'dev')):
            with mock.patch.object(versioncheck, 'CONFIG', config(GIT_BRANCH=branch)):
                self.assertEqual(versioncheck.git_remote_branch(), expected)

    def test_commit_titles_are_counted(self):
        with mock.patch.object(versioncheck, 'CONFIG', config()), \
                mock.patch.object(versioncheck.subprocess, 'run', side_effect=git_ok('First\nSecond\n\n')) as run:
            commits, commit_list = versioncheck.get_commit_difference_from_git()
        self.assertEqual((commits, commit_list), (2, 'First\nSecond'))
        log_cmd = run.call_args_list[-1].args[0]
        self.assertEqual(log_cmd[:3], ['git', 'log', f'{CURRENT}..{LATEST}'])

    def test_package_install_fetches_master(self):
        with mock.patch.object(versioncheck, 'CONFIG', config(GIT_BRANCH='Package', INSTALL_TYPE='package')), \
                mock.patch.object(versioncheck.subprocess, 'run', side_effect=git_ok()) as run:
            versioncheck.get_commit_difference_from_git()
        fetch = [c.args[0] for c in run.call_args_list if c.args[0][1] == 'fetch'][0]
        self.assertEqual(fetch[-1], 'refs/heads/master')

    def test_missing_git_program_does_not_raise(self):
        with mock.patch.object(versioncheck, 'CONFIG', config(GIT_PROGRAM='/no/such/git')), \
                mock.patch.object(versioncheck.platform, 'system', return_value='Linux'), \
                mock.patch.object(versioncheck.subprocess, 'run', side_effect=FileNotFoundError(2, 'missing')):
            self.assertEqual(versioncheck.get_commit_difference_from_git(), (-1, ''))

    def test_second_git_location_is_tried(self):
        def run(cmd, **kwargs):
            if cmd[0] == 'git':
                raise FileNotFoundError(2, 'missing')
            return git_ok('Only one')(cmd)
        with mock.patch.object(versioncheck, 'CONFIG', config()), \
                mock.patch.object(versioncheck.platform, 'system', return_value='Darwin'), \
                mock.patch.object(versioncheck.subprocess, 'run', side_effect=run):
            self.assertEqual(versioncheck.get_commit_difference_from_git(), (1, 'Only one'))

    def test_git_error_gives_unknown(self):
        err = subprocess.CalledProcessError(128, ['git', 'log'], stderr='fatal: bad revision\n')
        with mock.patch.object(versioncheck, 'CONFIG', config()), \
                mock.patch.object(versioncheck.subprocess, 'run', side_effect=err):
            self.assertEqual(versioncheck.get_commit_difference_from_git(), (-1, ''))

    def test_unavailable_latest_version_is_kept(self):
        # the update banner tells the user it couldn't reach git, rather than calling it a local version
        cfg = config(LATEST_VERSION='Not_Available_From_Git : https://gitlab.com/x.git/')
        with mock.patch.object(versioncheck, 'CONFIG', cfg), \
                mock.patch.object(versioncheck.subprocess, 'run') as run:
            commits, _ = versioncheck.get_commit_difference_from_git()
        self.assertEqual(commits, -1)
        self.assertTrue(cfg['LATEST_VERSION'].startswith('Not_Available_From_Git'))
        run.assert_not_called()
        base = os.path.join(os.path.dirname(__file__), '..', 'data', 'interfaces', 'bookstrap', 'base.html')
        with open(base, encoding='utf-8') as f:
            self.assertIn("CONFIG['LATEST_VERSION'].startswith('Not_Available_From_Git')", f.read())

    def test_latest_version_from_ls_remote(self):
        # url and branch come from config, so no shell
        def run(stdout):
            return lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr='')
        for stdout, expected in ((f'{LATEST}\trefs/heads/master\n', LATEST), ('', None)):
            with mock.patch.object(versioncheck, 'CONFIG', config(GIT_BRANCH='Package')), \
                    mock.patch.object(versioncheck.subprocess, 'run', side_effect=run(stdout)) as git:
                latest, _ = versioncheck.get_latest_version_from_git()
            self.assertEqual(git.call_args.args[0][1:],
                             ['ls-remote', 'https://gitlab.com/LazyLibrarian/lazylibrarian.git/', 'refs/heads/master'])
            self.assertNotIn('shell', git.call_args.kwargs)
            if expected:
                self.assertEqual(latest, expected)
            else:
                self.assertTrue(latest.startswith('Not_Available_From_Git'))

    def test_latest_version_without_git(self):
        with mock.patch.object(versioncheck, 'CONFIG', config()), \
                mock.patch.object(versioncheck.platform, 'system', return_value='Linux'), \
                mock.patch.object(versioncheck.subprocess, 'run', side_effect=FileNotFoundError(2, 'missing')):
            latest, _ = versioncheck.get_latest_version_from_git()
        self.assertTrue(latest.startswith('Not_Available_From_Git'))

    def test_versions_that_are_not_hashes_are_not_given_to_git(self):
        for current, latest in (('No Version File', LATEST), (CURRENT, '--upload-pack=touch x')):
            with mock.patch.object(versioncheck, 'CONFIG', config(CURRENT_VERSION=current, LATEST_VERSION=latest)), \
                    mock.patch.object(versioncheck.subprocess, 'run') as run:
                commits, commit_list = versioncheck.get_commit_difference_from_git()
            run.assert_not_called()
            self.assertEqual(commits, -1)
            self.assertIn('Unknown version', commit_list)

    def test_git_does_not_wait_on_the_remote(self):
        # a password prompt or a dead connection would hold the version check thread
        with mock.patch.object(versioncheck, 'CONFIG', config()), \
                mock.patch.object(versioncheck.subprocess, 'run', side_effect=git_ok('One')) as run:
            versioncheck.get_commit_difference_from_git()
        for call in run.call_args_list:
            self.assertTrue(call.kwargs['timeout'])
            self.assertEqual(call.kwargs['env']['GIT_TERMINAL_PROMPT'], '0')
        timeout = subprocess.TimeoutExpired(['git', 'fetch'], 300)
        with mock.patch.object(versioncheck, 'CONFIG', config()), \
                mock.patch.object(versioncheck.subprocess, 'run', side_effect=timeout):
            self.assertEqual(versioncheck.get_commit_difference_from_git(), (-1, ''))
            latest, _ = versioncheck.get_latest_version_from_git()
        self.assertTrue(latest.startswith('Not_Available_From_Git'))

    def test_git_commits_parsed_like_the_api(self):
        out = (f'{LATEST}\x1f{LATEST[:9]}\x1f2026-10-28T12:32:00+01:00\x1f{CURRENT}\x1fmiško\x1fShow the date\0'
               f'{CURRENT}\x1f{CURRENT[:9]}\x1f2026-10-27T10:00:00+01:00\x1fp1 p2\x1fphil\x1fOdd \x1f title\0')

        def run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, stdout=out if cmd[1] == 'log' else '', stderr='')
        with mock.patch.object(versioncheck, 'CONFIG', config()), \
                mock.patch.object(versioncheck.subprocess, 'run', side_effect=run) as git:
            res = versioncheck.git_commits(['-n', '5', 'FETCH_HEAD'], [f'{CURRENT}..FETCH_HEAD'], branch='dev')
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0][0], {'id': LATEST, 'short_id': LATEST[:9], 'title': 'Show the date',
                                     'author_name': 'miško', 'committed_date': '2026-10-28T12:32:00+01:00',
                                     'parent_ids': [CURRENT]})
        # a separator inside a title stays part of it
        self.assertEqual((res[0][1]['parent_ids'], res[0][1]['title']), (['p1', 'p2'], 'Odd \x1f title'))
        cmds = [c.args[0] for c in git.call_args_list]
        self.assertEqual(sum(1 for c in cmds if c[1] == 'fetch'), 1)
        self.assertIn('refs/heads/dev', [c for c in cmds if c[1] == 'fetch'][0])
        self.assertEqual([c[4:] for c in cmds if c[1] == 'log'], [['-n', '5', 'FETCH_HEAD'], [f'{CURRENT}..FETCH_HEAD']])
        self.assertEqual({(c[2], git.call_args.kwargs['encoding']) for c in cmds if c[1] == 'log'}, {('-z', 'utf-8')})

    def test_git_commits_none_without_git_or_on_error(self):
        err = subprocess.CalledProcessError(128, ['git', 'log'], stderr='fatal: bad object\n')
        for effect in (FileNotFoundError(2, 'missing'), err, subprocess.TimeoutExpired(['git'], 300)):
            with mock.patch.object(versioncheck, 'CONFIG', config()), \
                    mock.patch.object(versioncheck.platform, 'system', return_value='Linux'), \
                    mock.patch.object(versioncheck.subprocess, 'run', side_effect=effect):
                self.assertIsNone(versioncheck.git_commits(['FETCH_HEAD']))
