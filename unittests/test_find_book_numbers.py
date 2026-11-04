#  This file is part of Lazylibrarian.
#
# Purpose:
#   Test find_book_in_db against numbered volumes of a series (#3103)

from lazylibrarian import database, librarysync
from unittests.unittesthelpers import LLTestCaseWithStartup

# a mix of plain and subtitled volume names, as hardcover returns them
PRIMAL_HUNTER = {
    'PH1': 'The Primal Hunter',
    'PH2': 'The Primal Hunter 2',
    'PH3': 'The Primal Hunter 3: A LitRPG Adventure',
    'PH4': 'The Primal Hunter 4',
    'PH5': 'The Primal Hunter 5',
    'PH6': 'The Primal Hunter 6: A LitRPG Adventure',
    'PH7': 'The Primal Hunter 7',
    'PH12': 'The Primal Hunter 12',
}

OTHERS = {
    'HW1': 'He Who Fights With Monsters',
    'HW7': 'He Who Fights With Monsters 7',
    'SS6': 'The Secret of Secrets',
}


class FindBookNumbersTest(LLTestCaseWithStartup):

    def setUp(self):
        db = database.DBConnection()
        try:
            for authorid, authorname, books in (('Z1', 'Zogarth', PRIMAL_HUNTER), ('X1', 'Other Writer', OTHERS)):
                db.action("INSERT OR REPLACE INTO authors (AuthorID, AuthorName, Status) VALUES (?, ?, 'Active')",
                          (authorid, authorname))
                for bookid, name in books.items():
                    db.action("INSERT OR REPLACE INTO books (BookID, AuthorID, BookName, BookSub, Status, "
                              "AudioStatus) VALUES (?, ?, ?, '', 'Wanted', 'Wanted')", (bookid, authorid, name))
        finally:
            db.close()

    def tearDown(self):
        db = database.DBConnection()
        try:
            db.action("DELETE from books WHERE AuthorID IN ('Z1', 'X1')")
            db.action("DELETE from authors WHERE AuthorID IN ('Z1', 'X1')")
        finally:
            db.close()

    @staticmethod
    def find(title: str, author: str = 'Zogarth'):
        return librarysync.find_book_in_db(author, title, library='AudioBook')[0]

    def test_chapter_title_matches_its_own_volume(self):
        self.assertEqual(self.find('The Primal Hunter 3: A LitRPG Adventure - 01 - Opening Credits'), 'PH3')
        self.assertEqual(self.find('The Primal Hunter 6: A LitRPG Adventure - 01 - Opening Credits'), 'PH6')
        self.assertEqual(self.find('The Primal Hunter 3: A LitRPG Adventure - 12 - Chapter 11'), 'PH3')
        self.assertEqual(self.find('The Primal Hunter 6: A LitRPG Adventure - 33 - Chapter 32 - Mana Bolt'),
                         'PH6')

    def test_chapter_title_never_matches_another_volume(self):
        # each of these went to a sibling volume before. None names its volume the way the
        # database does, so no match is the safe answer
        for title in ('5 - The Primal Hunter 3: Chapter 4 - Mana Bolt',
                      'The Primal Hunter 6 - 01 - Opening Credits',
                      'The Primal Hunter 9 - 04 - Chapter 3'):
            with self.subTest(title=title):
                self.assertEqual(self.find(title), 0)

    def test_chapter_title_of_plain_volume(self):
        self.assertEqual(self.find('The Primal Hunter 5 - 02 - Chapter 1'), 'PH5')
        self.assertEqual(self.find('The Primal Hunter 12 - 14 - Chapter 13'), 'PH12')

    def test_whole_titles_unchanged(self):
        self.assertEqual(self.find('The Primal Hunter'), 'PH1')
        self.assertEqual(self.find('The Primal Hunter 3'), 'PH3')
        self.assertEqual(self.find('The Primal Hunter 12'), 'PH12')
        self.assertEqual(self.find('The Primal Hunter 4'), 'PH4')

    def test_ebook_number_rules_unchanged(self):
        self.assertEqual(librarysync.find_book_in_db('Zogarth', 'The Primal Hunter 4 - 01 - Opening Credits')[0], 0)

    def test_number_rules_unchanged(self):
        # different volume numbers, or a number only one side has, still don't match
        self.assertEqual(self.find('He Who Fights With Monsters #2', 'Other Writer'), 0)
        self.assertEqual(self.find('He Who Fights With Monsters 05', 'Other Writer'), 0)
        self.assertEqual(self.find('He Who Fights With Monsters #7', 'Other Writer'), 'HW7')
        # series details in brackets are still accepted
        self.assertEqual(self.find('The Secret of Secrets (Robert Langdon, #6)', 'Other Writer'), 'SS6')

    def test_title_has_volume(self):
        title = 'the primal hunter 3: a litrpg adventure - 01 - opening credits'
        self.assertTrue(librarysync.title_has_volume(title, 'the primal hunter 3: a litrpg adventure'))
        self.assertTrue(librarysync.title_has_volume(title, 'the primal hunter #03'))
        self.assertTrue(librarysync.title_has_volume('the primal hunter 3_ a litrpg adventure - 01 - x',
                                                     'the primal hunter 3: a litrpg adventure'))
        self.assertFalse(librarysync.title_has_volume(title, 'the primal hunter 6'))
        self.assertFalse(librarysync.title_has_volume(title, 'the primal hunter'))
        self.assertFalse(librarysync.title_has_volume('the primal hunter 30 - 01 - x', 'the primal hunter 3'))
        self.assertFalse(librarysync.title_has_volume('the primal hunter 2.5 - 01 - x', 'the primal hunter 2'))
        self.assertTrue(librarysync.title_has_volume('the primal hunter 2.5 - 01 - x', 'the primal hunter 2.5'))
        # the whole candidate has to be there, not just its first number
        self.assertFalse(librarysync.title_has_volume('the 7 deadly sins - 01 - x', 'the 7 habits'))
        self.assertFalse(librarysync.title_has_volume('1q84 book 3 - 01 - x 2', '1q84 book 2'))
        # ranges, omnibus editions and sequels aren't the single volume
        self.assertFalse(librarysync.title_has_volume('the primal hunter 3-5 - 01 - x', 'the primal hunter 3'))
        self.assertFalse(librarysync.title_has_volume('the primal hunter 3 and 4 - 01 - x', 'the primal hunter 3'))
        self.assertFalse(librarysync.title_has_volume('the primal hunter 3 & 4 - 01 - x', 'the primal hunter 3'))
        self.assertFalse(librarysync.title_has_volume('the primal hunter 3 part 2 - 01 - x', 'the primal hunter 3'))
        self.assertTrue(librarysync.title_has_volume('the primal hunter 3: a litrpg adventure - 01 - x',
                                                     'the primal hunter 3'))
        self.assertFalse(librarysync.title_has_volume('the 3 musketeers 2 - 01 - x', 'the 3 musketeers'))
        self.assertTrue(librarysync.title_has_volume('the 3 musketeers - 01 - x', 'the 3 musketeers'))
        self.assertFalse(librarysync.title_has_volume('book 2.05 - 01 - x', 'book 2.5'))
        # brackets are series details, not part of the candidate's name
        self.assertFalse(librarysync.title_has_volume(title, 'the primal hunter (the primal hunter, #6)'))
        self.assertTrue(librarysync.title_has_volume('the secret of secrets - 01 - 4 x', 'the secret of secrets'))
