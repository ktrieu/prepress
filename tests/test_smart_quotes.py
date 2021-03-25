import unittest
from prepress import replace_smart_quotes

class TestSmartQuotes(unittest.TestCase):

    def test_basic(self):
        self.assertEqual(
            replace_smart_quotes(
                'He said, "no".'
            ),
            'He said, “no”.'
        )

    def test_sentence_start(self):
        self.assertEqual(
            replace_smart_quotes(
                '"Weird, right?", he said.'
            ),
            '“Weird, right?”, he said.'
        )

    def test_sentence_end(self):
        self.assertEqual(
            replace_smart_quotes(
                'Said he, "Weird, right?"'
            ),
            'Said he, “Weird, right?”'
        )

    def test_short_quote(self):
        self.assertEqual(
            replace_smart_quotes(
                '"a", "a", "a"'
            ),
        '“a”, “a”, “a”'
        )

    def test_nested_quotes(self):
        self.assertEqual(
            replace_smart_quotes(
                '"He said, "pog"?"'
            ),
            '“He said, “pog”?”'
        )

    def test_question_mark(self):
        self.assertEqual(
            replace_smart_quotes(
                'He said, "why"?'
            ),
            'He said, “why”?'
        )

    def test_exclamation_mark(self):
        self.assertEqual(
            replace_smart_quotes(
                'He said, "why"!'
            ),
            'He said, “why”!'
        )