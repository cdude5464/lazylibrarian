#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test per-user UI language handling in webServe.py

import contextlib
from http.cookies import SimpleCookie
from unittest import mock

import cherrypy

from lazylibrarian import webServe
from lazylibrarian.database import DBConnection
from lazylibrarian.dbupgrade import db_upgrade, upgrade_needed
from lazylibrarian.filesystem import DIRS, remove_file
from unittests.unittesthelpers import LLTestCaseWithConfigandDIRS


class FakeRequest:
    def __init__(self, cookies: dict):
        self.cookie = SimpleCookie()
        for key, value in cookies.items():
            self.cookie[key] = value
        self.headers = {}


class FakeResponse:
    def __init__(self):
        self.cookie = SimpleCookie()


class UILangTest(LLTestCaseWithConfigandDIRS):

    def setUp(self):
        DIRS.DBFILENAME = "test-uilang.db"
        with contextlib.suppress(FileNotFoundError):
            remove_file(DIRS.get_dbfile())
        db_upgrade(upgrade_needed(), restartjobs=False)
        db = DBConnection()
        try:
            # ui_lang left NULL, as it is for every user that existed before the column was added
            db.action("INSERT into users (UserID, UserName, Name, Password, Email, SendTo, BookType, "
                      "Theme, hc_token, Perms, Prefs, Login_Count) VALUES "
                      "('u1', 'alice', 'Alice', '', '', '', 'epub', '', '', 65535, 0, 0)")
        finally:
            db.close()
        self.request = FakeRequest({'ll_uid': 'u1'})
        self.response = FakeResponse()
        patches = [mock.patch.object(cherrypy, 'request', self.request),
                   mock.patch.object(cherrypy, 'response', self.response)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        remove_file(DIRS.get_dbfile())

    @staticmethod
    def user_field(field: str):
        db = DBConnection()
        try:
            return db.match(f'SELECT {field} from users where UserID=?', ('u1',))[field]
        finally:
            db.close()

    @staticmethod
    def profile_save(**changes) -> str:
        # the same fields profile.html sends, which doesn't include ui_lang
        kwargs = {'username': 'alice', 'fullname': 'Alice', 'password': '', 'password2': '',
                  'email': '', 'sendto': '', 'booktype': 'epub', 'theme': '', 'hc_token': ''}
        kwargs.update(changes)
        return webServe.WebInterface().user_update(**kwargs)

    def test_valid_ui_lang(self):
        self.assertTrue(webServe.valid_ui_lang(''))
        self.assertTrue(webServe.valid_ui_lang('auto'))
        self.assertFalse(webServe.valid_ui_lang('None'))
        self.assertFalse(webServe.valid_ui_lang('xx_YY'))

    def test_profile_save_without_ui_lang(self):
        result = self.profile_save(booktype='mobi', password='newpassword', password2='newpassword')
        self.assertIn('BookType', result)
        self.assertIn('password', result)
        self.assertEqual(self.user_field('BookType'), 'mobi')
        self.assertIsNone(self.user_field('UI_Lang'))

    def test_profile_save_rejects_unknown_ui_lang(self):
        self.assertEqual(self.profile_save(ui_lang='xx_YY'), 'No changes made')
        self.assertIsNone(self.user_field('UI_Lang'))

    def test_profile_save_empty_ui_lang_is_not_a_change(self):
        self.assertEqual(self.profile_save(ui_lang=''), 'No changes made')

    def admin_save(self, ui_lang: str) -> str:
        kwargs = {'user': 'alice', 'username': 'alice', 'fullname': 'Alice', 'email': '', 'sendto': '',
                  'password': '', 'perms': '65535', 'calread': '', 'caltoread': '', 'booktype': 'epub',
                  'theme': '', 'hc_token': '', 'ui_lang': ui_lang}
        with mock.patch.object(webServe.WebInterface, 'check_permitted'):
            return webServe.WebInterface().admin_users(**kwargs)

    def test_admin_can_set_and_clear_ui_lang(self):
        self.assertIn('UI_Language', self.admin_save('auto'))
        self.assertEqual(self.user_field('UI_Lang'), 'auto')
        self.assertIn('UI_Language', self.admin_save(''))
        self.assertEqual(self.user_field('UI_Lang'), '')

    def test_admin_rejects_unknown_ui_lang(self):
        self.assertNotIn('UI_Language', self.admin_save('xx_YY'))
        self.assertIsNone(self.user_field('UI_Lang'))

    def test_cookie_login_without_ui_lang_sends_empty_cookie(self):
        with mock.patch.object(webServe.CONFIG, 'get_bool', side_effect=lambda key: key == 'USER_ACCOUNTS'), \
                mock.patch.object(webServe, 'TemplateLookup') as lookup:
            webServe.serve_template(templatename='index.html', title='test')
        lookup.return_value.get_template.assert_called_with('index.html')
        self.assertEqual(self.response.cookie['ll_uid'].value, 'u1')
        self.assertEqual(self.response.cookie['ll_uilang'].value, '')
