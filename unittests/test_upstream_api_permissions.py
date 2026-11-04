from unittest import TestCase
from unittest.mock import Mock,patch
from lazylibrarian import api

class UpstreamApiPermissionsTest(TestCase):
    def test_magazine_cleanup_requires_write_key(self):
        cfg=Mock()
        cfg.get_bool.return_value=True
        cfg.get_str.side_effect=lambda k:{'API_KEY':'w'*32,'API_RO_KEY':'r'*32}[k]
        with patch.object(api,'CONFIG',cfg),patch.object(api.TELEMETRY,'record_usage_data'):
            readonly=api.Api();readonly.check_params(apikey='r'*32,cmd='cleanMagLibrary')
            self.assertEqual(readonly.data['Error']['Code'],405)
            writable=api.Api();writable.check_params(apikey='w'*32,cmd='cleanMagLibrary')
            self.assertEqual(writable.data,'OK')
