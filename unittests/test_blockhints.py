#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test the advice shown with a blocked provider

import unittest

from lazylibrarian.blockhints import block_hint


class BlockHintsTest(unittest.TestCase):

    def test_timeout_names_the_provider_timeout_for_newznab_and_torznab(self):
        reason = 'Exception Timeout: Failed to perform, curl: (28) Operation timed out after 30000'
        self.assertIn('Config → Providers', block_hint('torznab_0', reason))
        self.assertIn('Interface → Timeouts', block_hint('torznab_0', reason))
        self.assertIn('FlareSolverr', block_hint('newznab_2', reason))

    def test_timeout_elsewhere_names_the_general_timeout_only(self):
        hint = block_hint('kat', 'Timeout HTTPSConnectionPool read timed out')
        self.assertIn('Interface → Timeouts', hint)
        self.assertNotIn('Providers', hint)
        self.assertIn('Interface → Timeouts', block_hint('', 'Timeout'))

    def test_rate_limit_needs_no_change(self):
        self.assertIn('Nothing to change', block_hint('torznab_0', 'Too Many Requests'))
        self.assertIn('Nothing to change', block_hint('tpb', 'Response status 429: Too Many Requests'))

    def test_unauthorized(self):
        self.assertIn('API key', block_hint('torznab_0', 'Response status 401: Unauthorized'))
        self.assertNotIn('API key', block_hint('tpb', 'Response status 401: Unauthorized'))

    def test_forbidden(self):
        self.assertIn('tag', block_hint('torznab_1', 'Response status 403: Forbidden'))
        self.assertIn('through Prowlarr', block_hint('lime', 'Response status 403: Forbidden'))

    def test_site_down(self):
        self.assertIn('down', block_hint('kat', 'Response status 523: <!DOCTYPE html> <!--[if lt IE 7]>'))
        self.assertIn('down', block_hint('torznab_0', 'Error 503'))

    def test_unreachable(self):
        self.assertIn('host', block_hint('newznab_0', 'Exception ConnectionError: Connection refused'))

    def test_not_found(self):
        self.assertIn('another one', block_hint('tpb', 'Response status 404: Not Found'))

    def test_ssl(self):
        reason = 'Exception ConnectionError: Failed to perform, curl: (60) SSL certificate problem'
        self.assertIn('SSL settings', block_hint('kat', reason), 'SSL, not just unreachable')
        self.assertIn('SSL settings', block_hint('torznab_0', 'Exception SSLError: certificate verify failed'))

    def test_cloudflare_code(self):
        self.assertIn('down', block_hint('kat', 'Response status 523: Origin Is Unreachable'))

    def test_nothing_to_say(self):
        self.assertEqual(block_hint('torznab_0', 'Got an empty response'), '')
        self.assertEqual(block_hint('torznab_0', ''), '')
        self.assertEqual(block_hint('torznab_0', None), '')
        # a number in the text is not a status code
        self.assertEqual(block_hint('kat', 'Found 4030 bad results'), '')

    def test_provider_advice_is_not_given_to_other_sources(self):
        self.assertEqual(block_hint('', 'Response status 403: Forbidden'), '')
        self.assertEqual(block_hint('', 'Error 503'), '')


if __name__ == '__main__':
    unittest.main()
