from unittest import TestCase
from lazylibrarian.configtypes import ConfigStr

class ConfigSecretLoggingTest(TestCase):
    def test_read_write_and_type_errors_do_not_log_values(self):
        item=ConfigStr('API','API_KEY','INITIAL_SECRET')
        with self.assertLogs(level='DEBUG') as logs:
            self.assertEqual(item.get_str(),'INITIAL_SECRET')
            self.assertTrue(item.set_str('NEW_SECRET'))
            item._on_type_mismatch('TYPE_SECRET',str)
        output=' '.join(logs.output)
        for secret in ('INITIAL_SECRET','NEW_SECRET','TYPE_SECRET'):
            self.assertNotIn(secret,output)
        self.assertIn('API_KEY',output)
        self.assertEqual(item.get_str(),'NEW_SECRET')
