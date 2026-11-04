from http.cookies import SimpleCookie
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock,patch
import cherrypy
from lazylibrarian import webServe

class ProxyFirstRequestTest(TestCase):
    def check(self, registered=True, permissions=65535, stale=False):
        cfg=Mock();cfg.get_bool.side_effect=lambda k:k in ('USER_ACCOUNTS','PROXY_AUTH')
        cfg.get_str.return_value='X-Forwarded-User'
        request=SimpleNamespace(cookie=SimpleCookie(),headers={'X-Forwarded-User':'registered@example.invalid'})
        response=SimpleNamespace(cookie=SimpleCookie())
        db=Mock()
        if stale: request.cookie['ll_uid']='stale-user'
        db.match.side_effect=([None] if stale else [])+[{'Perms':permissions,'UserID':'user42'} if registered else None]
        with patch.object(webServe,'CONFIG',cfg),patch.object(webServe.database,'DBConnection',return_value=db),patch.object(cherrypy,'request',request),patch.object(cherrypy,'response',response),patch.object(webServe.TELEMETRY,'record_usage_data'):
            if not registered or not permissions:
                with self.assertRaises(cherrypy.HTTPError) as error:
                    webServe.WebInterface.check_permitted(64,redirect_unauth=True)
                self.assertEqual(error.exception.status,403)
            else:
                webServe.WebInterface.check_permitted(64,redirect_unauth=True)
                self.assertEqual(request.cookie['ll_uid'].value,'user42')
                self.assertEqual(response.cookie['ll_uid'].value,'user42')
        if not registered:db.action.assert_not_called()

    def test_known_proxy_user_first_request_is_authorized(self):self.check()
    def test_unknown_proxy_user_stays_denied(self):self.check(registered=False)
    def test_registered_user_does_not_gain_permissions(self):self.check(permissions=0)

    def test_stale_cookie_recovers_only_registered_proxy_user(self):self.check(stale=True)
