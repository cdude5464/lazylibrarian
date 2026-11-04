#  This file is part of Lazylibrarian.
#
# Purpose:
#   The CI pages job publishes changes.json with scripts/ci/changes_json.py, for installs without git.
#   What it writes has to read the same as git log does, merges included.

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from lazylibrarian import whatsnew
from unittests.unittesthelpers import LLTestCase

SCRIPT = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'ci', 'changes_json.py')


@unittest.skipUnless(shutil.which('git'), 'needs git')
class ChangesJsonTest(LLTestCase):

    def git(self, *args):
        env = dict(os.environ, GIT_AUTHOR_NAME='miško', GIT_AUTHOR_EMAIL='m@example.com',
                   GIT_COMMITTER_NAME='m', GIT_COMMITTER_EMAIL='m@example.com')
        return subprocess.run(['git', '-c', 'commit.gpgsign=false', *args], cwd=self.repo, check=True,
                              capture_output=True, text=True, env=env).stdout.strip()

    def commit(self, title):
        self.git('commit', '-q', '--allow-empty', '-m', title)
        return self.git('rev-parse', 'HEAD')

    def setUp(self):
        super().setUp()
        self.repo = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.repo, True)
        self.git('init', '-q', '-b', 'master')

    def test_written_like_git_log(self):
        first = self.commit('First')
        self.git('checkout', '-q', '-b', 'side')
        self.commit('Side fix \x1f with a separator')
        self.git('checkout', '-q', 'master')
        installed = self.commit('Installed')
        self.git('merge', '-q', '--no-ff', '-m', "Merge branch 'side'", 'side')
        latest = self.commit('Newest')
        out = os.path.join(self.repo, 'changes.json')
        subprocess.run([sys.executable, SCRIPT, 'HEAD', 'master', out], cwd=self.repo, check=True,
                       capture_output=True)
        with open(out, encoding='utf-8') as f:
            data = json.load(f)

        self.assertEqual((data['branch'], data['latest']), ('master', latest))
        self.assertEqual(data['commits'][0]['title'], 'Newest')
        self.assertEqual(data['commits'][0]['author_name'], 'miško')
        self.assertEqual(data['commits'][-1]['id'], first)
        # same commits as git log installed..latest
        expected = self.git('log', '--format=%H', f'{installed}..{latest}').split()
        between = whatsnew.commits_between(data['commits'], installed, latest)
        self.assertEqual(sorted(c['id'] for c in between), sorted(expected))
        self.assertEqual(between[-1]['id'], latest)
        self.assertIn('Side fix \x1f with a separator', [c['title'] for c in data['commits']])
