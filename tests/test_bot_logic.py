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
        os.environ.pop("MENTALHEALTHWEB_AI_FIRST", None)

    def _set_ai_first(self, enabled):
        os.environ["MENTALHEALTHWEB_AI_FIRST"] = "true" if enabled else "false"
        bot_logic.AI_FIRST_ENABLED = bot_logic._ai_first_enabled()

    def _stub_ai_reply(self, reply):
        self._original_ai_reply = bot_logic._call_ai_reply
        bot_logic._call_ai_reply = lambda user_input, language="tagalog", *args, **kwargs: reply  # noqa: E731
        self.addCleanup(self._restore_ai_reply)

    def _restore_ai_reply(self):
        bot_logic._call_ai_reply = self._original_ai_reply

    def test_generate_response_returns_faq_answer(self):
        self._set_ai_first(False)
        response, intent, is_crisis, is_abusive = bot_logic.generate_response("what is this app for", None, "tagalog")
        self.assertIn("academic struggle support chatbot", response)
        self.assertEqual(is_crisis, 0)
        self.assertEqual(is_abusive, 0)

    def test_generate_response_returns_greeting_response(self):
        self._set_ai_first(False)
        response, intent, is_crisis, is_abusive = bot_logic.generate_response("hi", None, "tagalog")
        self.assertEqual(intent, "greetings")
        self.assertTrue(response)
        self.assertNotIn("academic struggle", response.lower())
        self.assertEqual(is_crisis, 0)
        self.assertEqual(is_abusive, 0)

    def test_generate_response_returns_gratitude_response(self):
        self._set_ai_first(False)
        response, intent, is_crisis, is_abusive = bot_logic.generate_response("thank you", None, "tagalog")
        self.assertEqual(intent, "gratitude")
        self.assertTrue(response)
        self.assertNotIn("academic struggle", response.lower())
        self.assertEqual(is_crisis, 0)
        self.assertEqual(is_abusive, 0)

    def test_ai_first_answers_normal_questions_before_the_dataset(self):
        self._set_ai_first(True)
        self._stub_ai_reply("Musna ini an akon AI nga baton para ha imo yana.")
        response, intent, is_crisis, is_abusive = bot_logic.generate_response(
            "I am so stressed about my exam tomorrow", None, "tagalog"
        )
        self.assertEqual(response, "Musna ini an akon AI nga baton para ha imo yana.")
        self.assertIsNone(intent)
        self.assertEqual(is_crisis, 0)
        self.assertEqual(is_abusive, 0)

    def test_ai_first_still_uses_dataset_when_the_ai_has_no_reply(self):
        self._set_ai_first(True)
        self._stub_ai_reply(None)
        response, intent, _, _ = bot_logic.generate_response("thank you so much", None, "tagalog")
        self.assertEqual(intent, "gratitude")
        self.assertIn(response, bot_logic.ENGLISH_RESPONSES["gratitude"])

    def test_dataset_mode_is_still_available_when_ai_first_is_disabled(self):
        self._set_ai_first(False)
        response, intent, _, _ = bot_logic.generate_response(
            "I am so stressed about my exam tomorrow", None, "tagalog"
        )
        self.assertEqual(intent, "stress_exams")
        self.assertIn(response, bot_logic.ENGLISH_RESPONSES["stress_exams"])

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
        self._set_ai_first(False)
        response, intent, is_crisis, is_abusive = bot_logic.generate_response(
            "I am so stressed about my exam tomorrow", None, "tagalog"
        )
        self.assertEqual(intent, "stress_exams")
        self.assertIn(response, bot_logic.ENGLISH_RESPONSES["stress_exams"])
        self.assertNotIn("Naiintindihan ko", response)
        self.assertEqual(is_crisis, 0)
        self.assertEqual(is_abusive, 0)

    def test_english_question_stays_english_even_if_setting_is_waray(self):
        self._set_ai_first(False)
        response, intent, _, _ = bot_logic.generate_response(
            "I am so stressed about my exam tomorrow", None, "waray"
        )
        self.assertEqual(intent, "stress_exams")
        self.assertIn(response, bot_logic.ENGLISH_RESPONSES["stress_exams"])

    def test_tagalog_question_gets_tagalog_intent_response(self):
        self._set_ai_first(False)
        response, intent, is_crisis, is_abusive = bot_logic.generate_response(
            "Hindi ako nakakapag-focus, laging distracted", None, "tagalog"
        )
        self.assertEqual(intent, "adhd_concentration")
        self.assertIn(response, bot_logic.TAGALOG_RESPONSES["adhd_concentration"])
        self.assertEqual(is_crisis, 0)
        self.assertEqual(is_abusive, 0)

    def test_tagalog_question_uses_tagalog_follow_up(self):
        self._set_ai_first(False)
        # Tagalog-bodied intent -> Tagalog na sagot at Tagalog na follow-up.
        response, intent, _, _ = bot_logic.generate_response(
            "Sobrang stress ko sa thesis namin ngayon", None, "tagalog"
        )
        self.assertEqual(intent, "stress")
        self.assertIn("Mukhang mabigat", response)

    def test_english_question_uses_english_follow_up(self):
        self._set_ai_first(False)
        response, intent, _, _ = bot_logic.generate_response(
            "I feel so much pressure and stress right now", None, "tagalog"
        )
        self.assertEqual(intent, "stress")
        self.assertIn(bot_logic.ENGLISH_RESPONSES["stress"][0], response)
        self.assertTrue(
            any(follow_up in response for follow_up in bot_logic.ENGLISH_FOLLOW_UPS["stress"])
        )

    def test_waray_question_gets_waray_response(self):
        self._set_ai_first(False)
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
        self._set_ai_first(False)
        response, intent, _, _ = bot_logic.generate_response("kamusta ka po", None, "english")
        self.assertEqual(intent, "greetings")
        self.assertTrue(
            any(response.startswith(greeting) for greeting in bot_logic.TAGALOG_RESPONSES["greetings"])
        )

    def test_tagalog_gratitude_gets_tagalog_response(self):
        self._set_ai_first(False)
        response, intent, _, _ = bot_logic.generate_response("salamat po", None, "english")
        self.assertEqual(intent, "gratitude")
        self.assertIn(response, bot_logic.TAGALOG_RESPONSES["gratitude"])

    def test_english_gratitude_gets_english_response(self):
        self._set_ai_first(False)
        response, intent, _, _ = bot_logic.generate_response("thank you so much", None, "tagalog")
        self.assertEqual(intent, "gratitude")
        self.assertIn(response, bot_logic.ENGLISH_RESPONSES["gratitude"])

    def test_tagalog_faq_answer_is_used_for_tagalog_question(self):
        self._set_ai_first(False)
        response, intent, _, _ = bot_logic.generate_response("para saan ang app na ito", None, "tagalog")
        self.assertIsNone(intent)
        self.assertIn("chatbot", response)

    # ---- SIMPLE, NON-TECHNICAL LANGUAGE (madaling maintindihan) ----

    def test_intent_responses_do_not_use_technical_jargon(self):
        technical_words = {
            "cortisol", "dopamine", "serotonin", "neuroplasticity", "anhedonia",
            "dopaminergic", "hypothalamic", "allostatic", "vagal", "amygdala",
            "physiological", "efficacy", "pharmacological", "psychotherapy",
            "clinician", "allostatic load", "reward pathways",
        }
        responses = []
        for choices in list(bot_logic.ENGLISH_RESPONSES.values()):
            responses.extend(choices)
        for choices in list(bot_logic.TAGALOG_RESPONSES.values()):
            responses.extend(choices)
        for _, intent_data in bot_logic.INTENTS.items():
            responses.extend(intent_data.get("response", []))
        for text in responses:
            lowered = text.lower()
            for word in technical_words:
                self.assertNotIn(
                    word, lowered,
                    f"Technical word '{word}' found in a student-facing reply",
                )

    def test_system_prompt_requires_simple_student_friendly_words(self):
        for language in ("tagalog", "english", "waray"):
            prompt = bot_logic._build_openai_system_prompt(language).lower()
            self.assertIn("very simple", prompt)
            self.assertIn("cortisol", prompt)
            self.assertIn("short sentences", prompt)

    # ---- MALINAW, ON-TOPIC, WALANG SPECIAL CHARACTERS ----
    def test_system_prompt_requires_plain_text_and_on_topic_replies(self):
        for language in ("tagalog", "english", "waray"):
            prompt = bot_logic._build_openai_system_prompt(language).lower()
            self.assertIn("format like chatgpt", prompt)
            self.assertIn("stay on topic", prompt)
            self.assertIn("same topic", prompt)

    def test_clean_ai_text_keeps_chatgpt_structure_without_raw_symbols(self):
        raw = "### Study Tips\n\n**Hello!** Here is help.\n\n1. First tip\n2. Second tip\n\n```code``` 😊 <b>hi</b>"
        cleaned = bot_logic._clean_ai_text(raw)
        # ChatGPT structure ay napanatili (bold + numbered list)
        self.assertIn("**Study Tips**", cleaned)
        self.assertIn("**Hello!**", cleaned)
        self.assertIn("1. First tip", cleaned)
        # Magugulong symbols ay tinanggal
        for bad in ("###", "```", "😊", "<b>", "`"):
            self.assertNotIn(bad, cleaned)

    def test_ai_reply_receives_conversation_history_for_follow_ups(self):
        seen = {}

        def fake_ai(user_input, language="tagalog", history=None, **kwargs):
            seen["history"] = history
            return "Naiintindihan kita. Ipagpatuloy natin ang tungkol sa exam mo."

        self._set_ai_first(True)
        self._original_ai_reply = bot_logic._call_ai_reply
        bot_logic._call_ai_reply = fake_ai
        self.addCleanup(self._restore_ai_reply)
        history = [("Na-stress ako sa exam", "Naiintindihan kita tungkol sa exam.")]
        response, _, _, _ = bot_logic.generate_response("paano pa", None, "tagalog", history=history)
        self.assertEqual(seen.get("history"), history)
        self.assertIn("exam", response)

    def test_history_to_prompt_lines_keeps_only_recent_exchanges(self):
        history = [(f"q{i}", f"a{i}") for i in range(10)]
        lines = bot_logic._history_to_prompt_lines(history, limit=6)
        self.assertEqual(len(lines), 12)
        self.assertIn("q9", lines[-2])
        self.assertIn("a9", lines[-1])
        self.assertNotIn("q0", "\n".join(lines))

    # ---- KUMPLETO AT HINDI PUTOL NA SAGOT ----
    def test_clean_ai_text_removes_trailing_cut_off_sentence(self):
        raw = "Naiintindihan kita.\n\n1. Magpahinga muna\n2. Hatiin ang gawain sa maliit na hakbang na hind"
        cleaned = bot_logic._clean_ai_text(raw)
        self.assertTrue(cleaned.rstrip().endswith((".", "!", "?", ";", ":", ")")))
        self.assertNotIn("hind", cleaned.split()[-1])

    def test_clean_ai_text_keeps_complete_reply_intact(self):
        raw = "Naiintindihan kita.\n\n1. Magpahinga muna.\n2. Hatiin ang gawain."
        cleaned = bot_logic._clean_ai_text(raw)
        self.assertIn("Magpahinga muna.", cleaned)
        self.assertIn("Hatiin ang gawain.", cleaned)

    def test_system_prompt_requires_complete_answers(self):
        for language in ("tagalog", "english", "waray"):
            prompt = bot_logic._build_openai_system_prompt(language).lower()
            self.assertIn("finish your answer completely", prompt)


if __name__ == "__main__":
    unittest.main()
