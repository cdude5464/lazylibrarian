#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test status_mark_targets() in webServe.py

import unittest

from lazylibrarian.webServe import FORMAT_STATUS_ACTIONS, status_mark_targets


def _libraries(targets):
    status, library = targets
    return status, 'eBook' in library, 'AudioBook' in library


class StatusMarkTargetsTest(unittest.TestCase):

    def test_per_format_actions_ignore_page_library(self):
        expected = {
            'HaveEbook': ('Have', True, False),
            'HaveAudio': ('Have', False, True),
            'HaveBoth': ('Have', True, True),
            'SkipEbook': ('Skipped', True, False),
            'SkipAudio': ('Skipped', False, True),
            'SkipBoth': ('Skipped', True, True),
            'IgnoreEbook': ('Ignored', True, False),
            'IgnoreAudio': ('Ignored', False, True),
            'IgnoreBoth': ('Ignored', True, True),
        }
        self.assertEqual(set(expected), set(FORMAT_STATUS_ACTIONS))
        for action, result in expected.items():
            for library in ('eBook', 'AudioBook', 'eBook+AudioBook'):
                with self.subTest(action=action, library=library):
                    self.assertEqual(_libraries(status_mark_targets(action, library)), result)

    def test_plain_actions_follow_page_library(self):
        for action in ('Have', 'Skipped', 'Ignored'):
            with self.subTest(action=action):
                self.assertEqual(_libraries(status_mark_targets(action, 'eBook')), (action, True, False))
                self.assertEqual(_libraries(status_mark_targets(action, 'AudioBook')), (action, False, True))
                self.assertEqual(_libraries(status_mark_targets(action, 'eBook+AudioBook')), (action, True, True))

    def test_plain_action_with_no_library_marks_nothing(self):
        self.assertEqual(_libraries(status_mark_targets('Skipped', None)), ('Skipped', False, False))

    def test_members_page_combined_marktype_covers_audio(self):
        # members.html posts eBook+AudioBook for its combined option
        self.assertEqual(_libraries(status_mark_targets('Have', 'eBook+AudioBook')), ('Have', True, True))

    def test_other_actions_return_none(self):
        for action in ('Wanted', 'WantEbook', 'WantAudio', 'WantBoth', 'Remove', 'Delete',
                       'NoDelay', 'Read', 'ToRead', 'Leave', '', None, 'haveaudio'):
            with self.subTest(action=action):
                self.assertIsNone(status_mark_targets(action, 'eBook'))


if __name__ == '__main__':
    unittest.main()
