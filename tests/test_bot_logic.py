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
        c.execute("INSERT INTO faq_dataset (question, answer) VALUES (?, ?)", ("what is this app for", "This app is an academic struggle support chatbot for students."))
        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_generate_response_returns_faq_answer(self):
        response, intent, is_crisis, is_abusive = bot_logic.generate_response("what is this app for", None, "tagalog")
        self.assertIn("academic struggle support chatbot", response)
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

    # ---- LANGUAGE MATCHING (Tagalog question -> Tagalog, English -> English) ----

    def test_detect_language_recognizes_english(self):
        self.assertEqual(bot_logic.detect_language("I am so stressed about my exam tomorrow"), "english")

    def test_detect_language_recognizes_tagalog(self):
        self.assertEqual(bot_logic.detect_language("Sobrang stress ko sa thesis namin ngayon"), "tagalog")

    def test_detect_language_recognizes_waray(self):
        self.assertEqual(bot_logic.detect_language("Maupay nga adlaw, kumusta ka?"), "waray")

    def test_detect_language_returns_none_for_ambiguous_text(self):
        self.assertIsNone(bot_logic.detect_language("zzz qqq"))

    def test_resolve_response_language_follows_the_question(self):
        # Waray ang setting ng user pero English ang tanong -> English ang sagot.
        self.assertEqual(bot_logic.resolve_response_language("I am tired and stressed", "waray"), "english")
        # Tagalog ang setting pero Waray ang tanong -> Waray ang sagot.
        self.assertEqual(bot_logic.resolve_response_language("Maupay nga adlaw ha imo", "tagalog"), "waray")
        # Hindi malinaw ang wika -> gamitin ang setting ng user.
        self.assertEqual(bot_logic.resolve_response_language("zzz qqq", "english"), "english")

    def test_english_question_gets_english_intent_response(self):
        response, intent, is_crisis, is_abusive = bot_logic.generate_response(
            "I am so stressed about my exam tomorrow", None, "tagalog"
        )
        self.assertEqual(intent, "stress_exams")
        self.assertIn(response, bot_logic.ENGLISH_RESPONSES["stress_exams"])
        self.assertNotIn("Naiintindihan ko", response)
        self.assertEqual(is_crisis, 0)
        self.assertEqual(is_abusive, 0)

    def test_english_question_stays_english_even_if_setting_is_waray(self):
        response, intent, _, _ = bot_logic.generate_response(
            "I am so stressed about my exam tomorrow", None, "waray"
        )
        self.assertEqual(intent, "stress_exams")
        self.assertIn(response, bot_logic.ENGLISH_RESPONSES["stress_exams"])

    def test_tagalog_question_gets_tagalog_intent_response(self):
        response, intent, is_crisis, is_abusive = bot_logic.generate_response(
            "Hindi ako nakakapag-focus, laging distracted", None, "tagalog"
        )
        self.assertEqual(intent, "adhd_concentration")
        self.assertIn(response, bot_logic.TAGALOG_RESPONSES["adhd_concentration"])
        self.assertEqual(is_crisis, 0)
        self.assertEqual(is_abusive, 0)

    def test_tagalog_question_uses_tagalog_follow_up(self):
        # Tagalog-bodied intent -> Tagalog na sagot at Tagalog na follow-up.
        response, intent, _, _ = bot_logic.generate_response(
            "Sobrang stress ko sa thesis namin ngayon", None, "tagalog"
        )
        self.assertEqual(intent, "stress")
        self.assertIn("Mukhang mabigat", response)

    def test_english_question_uses_english_follow_up(self):
        response, intent, _, _ = bot_logic.generate_response(
            "I feel so much pressure and stress right now", None, "tagalog"
        )
        self.assertEqual(intent, "stress")
        self.assertIn(bot_logic.ENGLISH_RESPONSES["stress"][0], response)
        self.assertTrue(
            any(follow_up in response for follow_up in bot_logic.ENGLISH_FOLLOW_UPS["stress"])
        )

    def test_waray_question_gets_waray_response(self):
        response, intent, _, _ = bot_logic.generate_response(
            "Hello po, maupay nga adlaw ha imo", None, "tagalog"
        )
        self.assertEqual(intent, "greetings")
        self.assertIn(response, bot_logic.WARAY_RESPONSES["greetings"])

    def test_crisis_response_matches_question_language(self):
        response_en, _, is_crisis_en, _ = bot_logic.generate_response("i want to kill myself", None, "tagalog")
        self.assertEqual(is_crisis_en, 1)
        self.assertEqual(response_en, bot_logic.CRISIS_RESPONSE)

        response_tl, _, is_crisis_tl, _ = bot_logic.generate_response("gusto ko mamatay", None, "english")
        self.assertEqual(is_crisis_tl, 1)
        self.assertEqual(response_tl, bot_logic.CRISIS_RESPONSE_TL)

    def test_tagalog_greeting_gets_tagalog_response(self):
        response, intent, _, _ = bot_logic.generate_response("kamusta ka po", None, "english")
        self.assertEqual(intent, "greetings")
        self.assertTrue(
            any(response.startswith(greeting) for greeting in bot_logic.TAGALOG_RESPONSES["greetings"])
        )

    def test_tagalog_gratitude_gets_tagalog_response(self):
        response, intent, _, _ = bot_logic.generate_response("salamat po", None, "english")
        self.assertEqual(intent, "gratitude")
        self.assertIn(response, bot_logic.TAGALOG_RESPONSES["gratitude"])

    def test_english_gratitude_gets_english_response(self):
        response, intent, _, _ = bot_logic.generate_response("thank you so much", None, "tagalog")
        self.assertEqual(intent, "gratitude")
        self.assertIn(response, bot_logic.ENGLISH_RESPONSES["gratitude"])

    def test_tagalog_faq_answer_is_used_for_tagalog_question(self):
        response, intent, _, _ = bot_logic.generate_response("para saan ang app na ito", None, "tagalog")
        self.assertIsNone(intent)
        self.assertIn("chatbot", response)


if __name__ == "__main__":
    unittest.main()
