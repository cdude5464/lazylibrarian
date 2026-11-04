from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from lazylibrarian import api


class ApiSecretLoggingTest(TestCase):
    def response(self, command, data, kwargs):
        handler = api.Api()
        handler.data = "OK"
        handler.cmd = command
        handler.kwargs = kwargs
        handler.logger = Mock()
        handler.dlcommslogger = Mock()
        setattr(handler, "_" + command.lower(), lambda **_: setattr(handler, "data", data))
        request = SimpleNamespace(headers={}, remote=SimpleNamespace(ip="127.0.0.1"))
        with (
            patch.object(api.cherrypy, "request", request),
            patch.object(api, "thread_name"),
            patch.object(api.TELEMETRY, "record_usage_data"),
        ):
            result = handler.fetch_data
        logs = str(handler.logger.mock_calls) + str(handler.dlcommslogger.mock_calls)
        return result, logs

    def test_config_responses_remain_unchanged_but_secret_values_are_not_logged(self):
        for command, data in (
            ("readCFG", "[SECRET]"),
            ("rEaDcFg", "[SECRET]"),
            ("readConfig", {"ANNA_KEY": "SECRET", "nested": {"PaSsWoRd": "SECRET"}}),
        ):
            with self.subTest(command=command):
                result, logs = self.response(command, data, {"name": "ANNA_KEY", "group": "ANNA"})
                self.assertIn("SECRET", result)
                self.assertNotIn("SECRET", logs)
                self.assertIn(command, logs)

    def test_write_arguments_and_jsonp_payload_are_not_logged(self):
        result, logs = self.response(
            "wRiTeCfG", {"value": "SECRET"},
            {"name": "ANNA_KEY", "group": "ANNA", "value": "SECRET", "callback": "cb"},
        )
        self.assertTrue(result.startswith("cb("))
        self.assertIn("SECRET", result)
        self.assertNotIn("SECRET", logs)
