import os
import sqlite3
import tempfile
import types
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

    # ---- WALANG DUPLIKASYON, WALANG HILAW NA HTML ----
    def test_clean_ai_text_removes_duplicate_list_items(self):
        raw = "Narito ang mga pangungusap.\n\n1. Ang pula ay kulay ng puso.\n2. Si Juan ay magaling.\n1. Ang pula ay kulay ng puso.\n2. Si Juan ay magaling.\n3. Ang libro ay nasa mesa."
        cleaned = bot_logic._clean_ai_text(raw)
        self.assertEqual(cleaned.count("Ang pula ay kulay ng puso."), 1)
        self.assertEqual(cleaned.count("Si Juan ay magaling."), 1)
        self.assertIn("1. Ang pula ay kulay ng puso.", cleaned)
        self.assertIn("2. Si Juan ay magaling.", cleaned)
        self.assertIn("3. Ang libro ay nasa mesa.", cleaned)

    def test_clean_ai_text_converts_br_tags_to_newlines(self):
        raw = "1. Ang pula ay kulay ng puso.<br>2. Si Juan ay magaling.<br>3. Ang libro ay nasa mesa."
        cleaned = bot_logic._clean_ai_text(raw)
        self.assertNotIn("<br>", cleaned)
        self.assertNotIn("&lt;", cleaned)
        self.assertIn("Ang pula ay kulay ng puso.", cleaned)
        self.assertIn("Si Juan ay magaling.", cleaned)

    def test_clean_ai_text_strips_br_variants_without_gluing_sentences(self):
        # Kahit may attributes o ibang porma ang <br>, hindi ito dapat makita
        # at hindi pwedeng magkadikit ang dalawang pangungusap.
        raw = (
            'Naiintindihan kita.<br class="x">Mahalaga ang pahinga mo. '
            "<BR />Uminom ka ng tubig.<br/>Mag-aral nang maayos."
        )
        cleaned = bot_logic._clean_ai_text(raw)
        lowered = cleaned.lower()
        self.assertNotIn("<br", lowered)
        self.assertNotIn("&lt;", cleaned)
        self.assertNotIn("kita.Mahalaga", cleaned)
        self.assertNotIn("tubig.Mag-aral", cleaned)
        self.assertIn("Naiintindihan kita.", cleaned)
        self.assertIn("Mahalaga ang pahinga mo.", cleaned)
        self.assertIn("Uminom ka ng tubig.", cleaned)
        self.assertIn("Mag-aral nang maayos.", cleaned)

    def test_clean_ai_text_decodes_escaped_br_entities(self):
        raw = "Unang pangungusap.&lt;br&gt;Ikalawang pangungusap.&#60;br&#62;Ikatlong pangungusap."
        cleaned = bot_logic._clean_ai_text(raw)
        self.assertNotIn("<br", cleaned.lower())
        self.assertNotIn("&lt;", cleaned)
        self.assertNotIn("&#60;", cleaned)
        lines = [l.strip() for l in cleaned.split("\n") if l.strip()]
        self.assertIn("Unang pangungusap.", lines)
        self.assertIn("Ikalawang pangungusap.", lines)
        self.assertIn("Ikatlong pangungusap.", lines)

    def test_clean_ai_text_replaces_nbsp_with_plain_space(self):
        raw = "Pahinga muna.&nbsp;Uminom ng tubig."
        cleaned = bot_logic._clean_ai_text(raw)
        self.assertNotIn("&nbsp;", cleaned)
        self.assertIn("Pahinga muna. Uminom ng tubig.", cleaned)

    def test_system_prompt_requires_complete_grammatical_sentences(self):
        for language in ("tagalog", "english", "waray"):
            prompt = bot_logic._build_openai_system_prompt(language).lower()
            self.assertIn("complete, grammatically correct sentences", prompt)
            self.assertIn("never cut a sentence mid-way", prompt)

    # ---- SIMPLE, MADALING MAINTINDIHAN NA TAGALOG ----
    def test_system_prompt_requires_simple_tagalog_words(self):
        for language in ("tagalog", "english", "waray"):
            prompt = bot_logic._build_openai_system_prompt(language).lower()
            self.assertIn("malalalim na tagalog", prompt)
            self.assertIn("nararapat", prompt)
            self.assertIn("natural taglish", prompt)

    def test_canned_tagalog_responses_avoid_deep_words(self):
        # Dapat hindi na lumitaw ang mga malalalim o nakakalitang salita
        # sa anumang naka-prepare na sagot (dataset + crisis + FAQ).
        import re

        hard_patterns = [
            r"\bkatinuan\b", r"\bnararapat\b", r"\bkaligtaan\b", r"\bsumisikad\b",
            r"\bnangangahulugang\b", r"\bnauunawaan\b", r"\bsamantalahin\b",
            r"\bsukatan\b", r"\bipagkatiwala\b", r"\bpagtugon\b", r"\bprioritization\b",
            r"biyaya ang sarili", r"nang walang hiya", r"tungkulin din",
            r"diaphragmatic", r"progressive muscle relaxation", r"gawing gawi",
            r"lumalaban ito", r"padalos-dalos", r"magagatalinong",
        ]
        blobs = []
        for responses in bot_logic.TAGALOG_RESPONSES.values():
            blobs.extend(responses)
        blobs.append(bot_logic.CRISIS_RESPONSE_TL)
        blobs.extend(bot_logic.DEFAULT_FAQ_ANSWERS_TL.values())
        for entry in bot_logic.INTENTS.values():
            blobs.extend(entry.get("response", []))
        text = "\n".join(str(b) for b in blobs).lower()
        for pattern in hard_patterns:
            match = re.search(pattern, text)
            if match:
                snippet = text[match.start():match.end() + 60]
                self.fail(
                    f"Nakakita ng malalalim na salita na tumugma sa '{pattern}': {snippet}"
                )

    def test_system_prompt_forbids_repeats_and_html(self):
        for language in ("tagalog", "english", "waray"):
            prompt = bot_logic._build_openai_system_prompt(language).lower()
            self.assertIn("never repeat", prompt)
            self.assertIn("never output html", prompt)

    # ---- LINE-AWARE REPAIR: WALANG DUPLIKASYON, WALANG PAGKAWALA NG NILALAMAN ----
    def test_clean_ai_text_does_not_duplicate_list_when_tail_is_cut_off(self):
        raw = "Naiintindihan kita.\n\n1. Magpahinga muna\n2. Hatiin ang gawain sa maliliit na hakbang na hind"
        cleaned = bot_logic._clean_ai_text(raw)
        # Hindi na-uulit ang listahan at walang blangkong "2." na naiwan
        self.assertEqual(cleaned.count("Magpahinga muna"), 1)
        stripped_lines = [l.strip() for l in cleaned.split("\n")]
        self.assertNotIn("2.", stripped_lines)
        # Tinanggal lang ang bitin na salita, hindi ang buong linya
        self.assertNotIn("hind", cleaned)
        self.assertIn("1. Magpahinga muna", cleaned)
        self.assertTrue(cleaned.rstrip().endswith("."))

    def test_clean_ai_text_does_not_treat_list_numbers_as_sentence_ends(self):
        raw = "Narito ang mga tip.\n\n1. Pahinga muna.\n2. Gawin mo ito bawat araw hanggang sa makaka"
        cleaned = bot_logic._clean_ai_text(raw)
        self.assertEqual(cleaned.count("Pahinga muna."), 1)
        stripped_lines = [l.strip() for l in cleaned.split("\n")]
        self.assertNotIn("2.", stripped_lines)
        self.assertTrue(cleaned.rstrip().endswith("."))

    def test_clean_ai_text_keeps_bullet_list_without_trailing_periods(self):
        raw = "Subukan mo ito:\n\n- Magpahinga nang 10 minuto\n- Uminom ng tubig\n- Maglakad sandali"
        cleaned = bot_logic._clean_ai_text(raw)
        self.assertIn("- Magpahinga nang 10 minuto", cleaned)
        self.assertIn("- Uminom ng tubig", cleaned)
        self.assertIn("- Maglakad sandali", cleaned)
        self.assertTrue(cleaned.rstrip().endswith("."))

    def test_clean_ai_text_appends_period_to_complete_final_line(self):
        raw = "Naiintindihan kita.\n\nSubukan mong magpahinga nang kaunti"
        cleaned = bot_logic._clean_ai_text(raw)
        self.assertIn("Subukan mong magpahinga nang kaunti.", cleaned)

    def test_clean_ai_text_drops_dangling_heading_at_the_end(self):
        raw = "Naiintindihan kita.\n\n**Mga Hakbang**"
        cleaned = bot_logic._clean_ai_text(raw)
        self.assertEqual(cleaned, "Naiintindihan kita.")

    def test_clean_ai_text_balances_unmatched_bold_markers(self):
        raw = "Ang **burnout ay normal sa estudyante. Maari kang magpahinga."
        cleaned = bot_logic._clean_ai_text(raw)
        self.assertNotIn("**", cleaned)
        self.assertIn("burnout ay normal", cleaned)

    def test_clean_ai_text_keeps_balanced_bold_markers(self):
        raw = "Ang **burnout** ay normal sa estudyante."
        cleaned = bot_logic._clean_ai_text(raw)
        self.assertIn("**burnout**", cleaned)

    def test_clean_ai_text_removes_duplicate_sentences_in_same_line(self):
        raw = "Ang pula ay kulay ng puso. Ang pula ay kulay ng puso. Tama ka dito."
        cleaned = bot_logic._clean_ai_text(raw)
        self.assertEqual(cleaned.count("Ang pula ay kulay ng puso."), 1)
        self.assertIn("Tama ka dito.", cleaned)

    def test_clean_ai_text_restarts_numbering_after_a_paragraph(self):
        raw = "Paliwanag natin.\n\n1. Una\n2. Dalawa\nIpaliwanag natin ang susunod.\n1. Tatlo\n2. Apat"
        cleaned = bot_logic._clean_ai_text(raw)
        self.assertIn("\n1. Tatlo", cleaned)
        self.assertNotIn("\n3. Tatlo", cleaned)

    # ---- CONTINUATION: KAPAG NA-CUT ANG SAGOT, ISANG BESES ITINUOY ----
    def _restore_env_var(self, key, original):
        if original is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original

    def _fake_openai_module(self, replies):
        """Fake openai module: bawat create() ay kukuha ng susunod na
        (content, finish_reason) mula sa ``replies`` at nag-iipon ng messages."""
        calls = []

        class FakeMessage:
            def __init__(self, content):
                self.content = content

        class FakeChoice:
            def __init__(self, content, finish_reason):
                self.message = FakeMessage(content)
                self.finish_reason = finish_reason

        class FakeCompletion:
            def __init__(self, choices):
                self.choices = choices

        class FakeCompletions:
            def create(self, model=None, messages=None, max_tokens=None,
                       temperature=None, **kwargs):
                content, finish_reason = replies[len(calls)]
                calls.append(messages)
                return FakeCompletion([FakeChoice(content, finish_reason)])

        class FakeChat:
            def __init__(self):
                self.completions = FakeCompletions()

        class FakeClient:
            def __init__(self, api_key=None):
                self.chat = FakeChat()

        class FakeOpenAI:
            OpenAI = FakeClient

            class RateLimitError(Exception):
                pass

        return FakeOpenAI, calls

    @staticmethod
    def _fake_gemini_response(text, finish_reason):
        response = types.SimpleNamespace(text=text, parts=[object()])
        response.candidates = [types.SimpleNamespace(finish_reason=finish_reason)]
        return response

    def test_openai_reply_requests_continuation_when_cut_off(self):
        original_key = os.environ.get("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = "sk-test-1234567890"
        self.addCleanup(self._restore_env_var, "OPENAI_API_KEY", original_key)

        fake_module, calls = self._fake_openai_module([
            ("Narito ang mga hakbang na hindi", "length"),
            (" natutupad ko pa ngayon. Kaya mo ito!", "stop"),
        ])
        original_import = bot_logic._import_openai
        bot_logic._import_openai = lambda: fake_module
        self.addCleanup(setattr, bot_logic, "_import_openai", original_import)

        reply = bot_logic._run_openai_chat("Paano ako mag-focus?", language="tagalog")

        # 2 tawag: una na-cut, pangalawa ang nagpatuloy
        self.assertEqual(len(calls), 2)
        last_messages = calls[1]
        self.assertEqual(last_messages[-2]["role"], "assistant")
        self.assertIn("hindi", last_messages[-2]["content"])
        self.assertEqual(last_messages[-1]["role"], "user")
        self.assertIn("cut off", last_messages[-1]["content"])
        # Kumpleto na ang pinagsamang sagot
        self.assertIn("natutupad ko pa", reply)
        self.assertTrue(reply.rstrip()[-1] in ".!?")

    def test_openai_reply_skips_continuation_when_finished(self):
        original_key = os.environ.get("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = "sk-test-1234567890"
        self.addCleanup(self._restore_env_var, "OPENAI_API_KEY", original_key)

        fake_module, calls = self._fake_openai_module([
            ("Narito ang mga tip. 1. Magpahinga. 2. Pumunta sa counselor.", "stop"),
        ])
        original_import = bot_logic._import_openai
        bot_logic._import_openai = lambda: fake_module
        self.addCleanup(setattr, bot_logic, "_import_openai", original_import)

        reply = bot_logic._run_openai_chat("Paano ako mag-focus?", language="tagalog")

        self.assertEqual(len(calls), 1)
        self.assertIn("counselor", reply)

    def test_gemini_reply_requests_continuation_when_cut_off(self):
        original_key = os.environ.get("GEMINI_API_KEY")
        os.environ["GEMINI_API_KEY"] = "AIza-test-1234567890"
        self.addCleanup(self._restore_env_var, "GEMINI_API_KEY", original_key)

        responses = [
            self._fake_gemini_response("Narito ang mga hakbang na hindi", finish_reason=2),
            self._fake_gemini_response(" natutupad ko pa. Kaya mo!", finish_reason=1),
        ]
        generate_calls = []

        class FakeModel:
            def generate_content(self, contents=None):
                generate_calls.append(contents)
                return responses[len(generate_calls) - 1]

        fake_genai = types.SimpleNamespace(
            configure=lambda api_key=None: None,
            GenerativeModel=lambda name: FakeModel(),
        )
        original_import = bot_logic._import_genai
        bot_logic._import_genai = lambda: fake_genai
        self.addCleanup(setattr, bot_logic, "_import_genai", original_import)

        reply = bot_logic._call_gemini_api("Paano ako mag-focus?", "tagalog")

        self.assertEqual(len(generate_calls), 2)
        self.assertIn("cut off", generate_calls[1])
        self.assertIn("natutupad ko pa", reply)
        self.assertTrue(reply.rstrip()[-1] in ".!?")


if __name__ == "__main__":
    unittest.main()
