import os
import sqlite3
import tempfile
import unittest

from utils import bot_logic


class BotLogicTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_database.db")
        os.environ["MENTALHEALTHWEB_DB"] = self.db_path

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS faq_dataset (id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT, answer TEXT)")
        c.execute("INSERT INTO faq_dataset (question, answer) VALUES (?, ?)", ("what is this app for", "This app is a mental health support chatbot for students."))
        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_generate_response_returns_faq_answer(self):
        response, intent, is_crisis, is_abusive = bot_logic.generate_response("what is this app for", None, "tagalog")
        self.assertIn("mental health support chatbot", response)
        self.assertEqual(is_crisis, 0)
        self.assertEqual(is_abusive, 0)

    def test_generate_response_returns_greeting_response(self):
        response, intent, is_crisis, is_abusive = bot_logic.generate_response("hi", None, "tagalog")
        self.assertEqual(intent, "greetings")
        self.assertTrue(response)
        self.assertNotIn("academic struggle", response.lower())
        self.assertEqual(is_crisis, 0)
        self.assertEqual(is_abusive, 0)

    def test_generate_response_returns_gratitude_response(self):
        response, intent, is_crisis, is_abusive = bot_logic.generate_response("thank you", None, "tagalog")
        self.assertEqual(intent, "gratitude")
        self.assertTrue(response)
        self.assertNotIn("academic struggle", response.lower())
        self.assertEqual(is_crisis, 0)
        self.assertEqual(is_abusive, 0)


if __name__ == "__main__":
    unittest.main()
