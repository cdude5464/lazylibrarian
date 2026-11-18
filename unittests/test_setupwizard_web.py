#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test the setup wizard handlers in webServe.py

from unittest import mock

import cherrypy

from lazylibrarian import webServe
from unittests.unittesthelpers import LLTestCaseWithStartup


class SetupWizardWebTest(LLTestCaseWithStartup):

    def setUp(self):
        self.ws = webServe.WebInterface()
        p = mock.patch.object(webServe.WebInterface, 'check_permitted')
        self.permitted = p.start()
        self.addCleanup(p.stop)
        method = cherrypy.request.method
        self.addCleanup(setattr, cherrypy.request, 'method', method)

    def test_presets_guess_from_langs(self):
        res = self.ws.wizard_presets(langs='sk-SK,en')
        self.assertEqual(res['country'], 'SK')
        self.assertEqual([s['id'] for s in res['steps']], ['language', 'sources', 'books', 'dates', 'providers', 'other'])
        self.assertIn('SK', [c['code'] for c in res['countries']])
        self.assertIn('title', res['strings'])
        self.assertIn(res['lang'], [lang['code'] for lang in res['languages']])

    def test_repeated_params_use_first(self):
        self.assertEqual(self.ws.wizard_presets(country=['PL', 'SK'], langs=['de', 'sk'])['country'], 'PL')

    def test_presets_given_country_wins(self):
        self.assertEqual(self.ws.wizard_presets(country='PL', langs='sk-SK')['country'], 'PL')
        self.assertEqual(self.ws.wizard_presets(country='nope', langs='de-AT')['country'], 'AT')

    def test_apply_parses_json(self):
        with mock.patch('lazylibrarian.setupwizard.apply', return_value={'ok': True}) as ap:
            cherrypy.request.method = 'POST'
            self.ws.wizard_apply(values='{"DATE_FORMAT": "$d.$m.$Y"}')
            ap.assert_called_once_with({'DATE_FORMAT': '$d.$m.$Y'}, finish=True)
            self.ws.wizard_apply(values='{"UI_LANGUAGE": "en"}', finish='0')
            ap.assert_called_with({'UI_LANGUAGE': 'en'}, finish=False)

    def test_apply_post_only(self):
        with mock.patch('lazylibrarian.setupwizard.apply') as ap:
            cherrypy.request.method = 'GET'
            self.assertFalse(self.ws.wizard_apply(values='{}')['ok'])
            ap.assert_not_called()

    def test_apply_bad_json(self):
        cherrypy.request.method = 'POST'
        self.assertFalse(self.ws.wizard_apply(values='{not json')['ok'])

    def test_check_folder(self):
        self.assertEqual(self.ws.wizard_check_folder(path='')['status'], 'empty')

    def test_endpoints_require_config_permission(self):
        self.permitted.side_effect = cherrypy.HTTPError(403)
        cherrypy.request.method = 'POST'
        for call in (self.ws.wizard_presets, self.ws.wizard_dismiss,
                     lambda: self.ws.wizard_check_folder(path='/'), lambda: self.ws.wizard_apply(values='{}')):
            self.assertRaises(cherrypy.HTTPError, call)
