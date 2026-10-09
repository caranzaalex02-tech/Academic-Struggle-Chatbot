# bot_responses_i18n.py
"""Language-aware response tables for the Academic Struggle Chatbot.

Ang chatbot ay dapat sumagot sa parehong wika ng tanong ng user:
  - Tanong na English  -> English na sagot
  - Tanong na Tagalog  -> Tagalog na sagot
  - Tanong na Waray    -> Waray na sagot

Dito nakalagay ang mga translation tables at ang maliit na language
detector na ginagamit ng ``utils/bot_logic.py``.
"""

import re

# Mga wikang sinusuportahan ng app.
LANGUAGE_CHOICES = ("english", "tagalog", "waray")


# ---------------------------------------------------------------------------
# LANGUAGE MARKERS
# ---------------------------------------------------------------------------
# Function words lang ang nilalagay natin dito (hindi content words gaya ng
# "exam", "stress", "assignment") para hindi ma-contaminate ang detection
# kapag may hiram na English na salita ang Tagalog/Waray na tanong.
ENGLISH_MARKERS = {
    "the", "is", "are", "am", "was", "were", "be", "been",
    "i", "i'm", "im", "i've", "me", "my", "mine", "you", "you're", "your",
    "we", "our", "us", "they", "them", "their", "he", "she", "his", "her",
    "it", "its", "this", "that", "these", "those", "there", "here",
    "what", "how", "why", "when", "where", "who", "which", "because",
    "but", "and", "or", "so", "very", "really", "just", "from", "about",
    "with", "without", "for", "of", "in", "on", "at", "to", "not",
    "don't", "dont", "can't", "cant", "didn't", "doesn't", "won't",
    "should", "would", "could", "will", "have", "has", "had", "do",
    "does", "did", "get", "got", "make", "need", "want", "feel",
    "feeling", "help", "please", "thanks", "thank", "much", "many",
    "too", "more", "some", "any", "all", "always", "never", "still",
    "again", "now", "today", "tomorrow", "if", "then", "than", "as",
    "might", "must", "there's",
    # Maikling English replies at particles — dating "0 marker" kaya napupunta
    # sa Tagalog na setting kapag puro ito ang laman ng mensahe ("okay", "yes").
    "ok", "okay", "yes", "yeah", "yep", "no", "nope", "maybe", "sure", "fine",
    "right", "exactly", "actually", "definitely", "probably", "honestly",
    "welcome", "agree", "same", "later", "soon", "already", "ever",
    "something", "anything", "everything", "nothing", "someone", "anyone",
    "everyone",
}
TAGALOG_MARKERS = {
    "ang", "ng", "mga", "ako", "ko", "mo", "kami", "namin", "natin",
    "ninyo", "niya", "siya", "sila", "nila", "ito", "iyan", "iyon",
    "iyong", "iyo", "akin", "ating", "atin", "po", "opo", "oo",
    "hindi", "wala", "meron", "mayroon", "naman", "kasi", "dahil",
    "para", "yung", "yun", "din", "rin", "lang", "lamang", "ngayon",
    "pero", "sana", "gusto", "ayaw", "kaya", "pwede", "puwede",
    "salamat", "kamusta", "kumusta", "mahalaga", "paano", "bakit",
    "saan", "kailan", "sino", "marami", "sobra", "sobrang", "parang",
    "siguro", "talaga", "muna", "nang", "hanggang", "tuwing", "kahit",
    "aking", "naku", "grabe", "ano", "nasaan", "sabi", "buong",
    "lahat", "iba", "dapat", "kailangan", "ayoko", "yata", "mahirap",
    "napaka", "araw", "gabi", "umaga", "pagod", "tulong", "aral",
    "walang", "kong", "bukas", "kahapon", "hapon", "tanghali", "oras",
    "panahon", "klase", "problema", "puyat", "hirap", "nahihirapan",
    "takot", "natatakot", "lungkot", "malungkot", "galit", "kaba",
    "tulog", "iyak", "umiiyak", "masaya", "sakit", "masakit",
    "eksam", "grado", "bagsak", "bumagsak", "pumasa", "guro",
    "kaklase", "kaibigan", "magulang", "pamilya", "trabaho", "pera",
    "baon", "utang", "aralin", "proyekto", "paaralan", "eskwela",
    "pasukan", "depensa",
}

WARAY_MARKERS = {
    "waray", "ngan", "hin", "han", "hira", "imo", "iton", "hiton",
    "ini", "hini", "diri", "damo", "gud", "ngatanan", "maupay",
    "bulig", "makakabulig", "pahuway", "kwarta", "kagrupo", "sangkay",
    "upod", "kaupod", "adlaw", "gab-i", "kun", "bisan", "didto",
    "ngano", "mabug-at", "kulba", "alayon", "nira", "naton", "nimo",
    "ha", "hito", "sugad", "tungod", "hin-o", "oman", "liwat", "la",
    "kabug-at", "mga", "hini",
}


# ---------------------------------------------------------------------------
# ENGLISH CONTENT WORDS (single-word / short-phrase fallback)
# ---------------------------------------------------------------------------
# Mga karaniwang English na content words (academic + mental health + general).
# Ginagamit LANG ito kapag walang Tagalog/Waray o English function-word marker
# (hal. "time management", "burnout", "hello") para hindi ma-contaminate ang
# Taglish na tanong (hal. "Na-stress ako sa exam") — kapag may Tagalog/Waray
# marker, marker path pa rin ang masusunod.
ENGLISH_CONTENT_WORDS = {
    "time", "management", "exam", "exams", "quiz", "quizzes", "thesis",
    "dissertation", "assignment", "assignments", "homework", "deadline",
    "deadlines", "grades", "grade", "failed", "failure", "fail", "study",
    "studies", "studying", "student", "students", "school", "college",
    "university", "class", "classes", "course", "courses", "subject",
    "subjects", "lesson", "lessons", "lecture", "lectures", "semester",
    "scholarship", "tuition", "enrollment", "attendance", "absent",
    "stress", "stressed", "stressful", "struggle", "struggles",
    "struggling", "anxiety", "anxious", "depressed", "depression", "sad",
    "sadness", "lonely", "loneliness", "tired", "tiredness", "fatigue",
    "exhausted", "exhaustion", "overwhelmed", "burnout", "pressure",
    "pressured", "worry", "worried", "fear", "afraid", "nervous", "panic",
    "crying", "hopeless", "worthless", "perfectionism", "perfectionist",
    "homesick", "confused", "confusion", "confusing", "angry", "anger",
    "frustrated", "frustration", "procrastination", "procrastinate",
    "procrastinating", "motivation", "motivated", "unmotivated", "motivate",
    "focus", "focused", "concentrate", "concentration", "distracted",
    "distraction", "sleep", "sleepy", "sleepless", "insomnia", "headache",
    "health", "healthy", "sick", "illness", "hospital", "doctor",
    "therapy", "therapist", "counselor", "counseling", "psychologist",
    "hello", "hey", "hi", "morning", "afternoon", "evening", "friend",
    "friends", "family", "parents", "teacher", "teachers", "adviser",
    "mentor", "advice", "support", "supportive", "happy", "happiness",
    "excited", "grateful", "thankful", "sorry", "goodbye", "bye",
    "project", "projects", "presentation", "presentations", "workload",
    "balance", "routine", "habit", "habits", "goal", "goals", "future",
    "career", "job", "jobs", "interview", "allowance", "budget",
    "dorm", "roommate", "bully", "bullying", "cheating", "plagiarism",
    "graduate", "graduation", "freshman", "relationship", "relationships",
    "partner", "boyfriend", "girlfriend", "crush", "love", "heartbreak",
    "breakup", "challenge", "challenges", "challenging", "overcome",
    "improve", "improvement", "progress", "success", "successful",
    "perfect", "mistake", "mistakes", "forget", "forgetful", "remember",
    "late", "absence", "notes", "review", "reviewer", "memorize",
    "difficult", "difficulty", "easy", "hard", "defense", "panel",
    "guidance", "clinic", "games", "gaming", "phone", "online",
    "overthink", "overthinker", "overthinking", "thinker", "worrier",
    "mind", "thoughts", "thought", "brain", "head", "heart",
    "mood", "moody", "emotion", "emotions", "emotional", "feelings",
    "feeling", "cope", "coping", "calm", "calmness", "relax", "relaxing",
    "rest", "break", "pause", "breathe", "breathing", "grounding",
    # Karaniwang English content words na madalas maging buong mensahe
    # (dating walang marker kaya nakikita itong ambiguous -> Tagalog setting).
    "research", "paper", "papers", "report", "reports", "essay", "essays",
    "module", "modules", "requirement", "requirements", "reading", "readings",
    "library", "laboratory", "experiment", "experiments", "argument",
    "question", "questions", "answer", "answers", "explain", "understand",
    "understood", "problem", "problems", "issue", "issues", "tip", "tips",
    "guide", "guides", "practice", "alone", "proud", "brave", "miss",
    "final", "finals", "midterm", "seatwork", "quarter", "grading",
}


def score_content_words(text):
    """Ibinalik ang bilang ng English content words sa isang text."""
    tokens = set(re.findall(r"[a-z]+(?:'[a-z]+)?", (text or "").lower()))
    return len(tokens & ENGLISH_CONTENT_WORDS)


def english_content_hits(text):
    """Ibinalik ang set ng English content words na nakita sa text."""
    tokens = set(re.findall(r"[a-z]+(?:'[a-z]+)?", (text or "").lower()))
    return tokens & ENGLISH_CONTENT_WORDS


def is_taglish_borrowed_use(text, content_hits):
    """True kapag ang English content word ay hiram lang sa Tagalog na pangungusap.

    Hal. "Na-overthinker ako" -> Tagalog pa rin (hindi English).
    """
    lowered = (text or "").lower()
    if not content_hits:
        return False
    for hit in content_hits:
        # May Tagalog verb affix na nakadikit (hal. "na-overthinker", "nagpanic").
        for prefix in ("na-", "nag-", "mag-", "nakaka-", "napaka-", "pinaka-",
                       "na", "nag", "mag", "naka", "napa", "pina", "kina"):
            if re.search(rf"(?<!\w){re.escape(prefix)}{re.escape(hit)}(?!\w)", lowered):
                return True
            if re.search(rf"(?<!\w){re.escape(prefix.rstrip('-'))}{re.escape(hit)}(?!\w)", lowered):
                return True
    for suffix in ("ako", "ka", "ko", "mo", "kami", "tayo", "siya"):
        if re.search(rf"(?<!\w){re.escape(suffix)}(?!\w)", lowered):
            return True
    return False


def score_languages(text):
    """Ibinalik ang (english, tagalog, waray) marker counts ng isang text."""
    tokens = set(re.findall(r"[a-z]+(?:'[a-z]+)?", (text or "").lower()))
    english = len(tokens & ENGLISH_MARKERS)
    tagalog = len(tokens & TAGALOG_MARKERS)
    waray = len(tokens & WARAY_MARKERS)
    return english, tagalog, waray


def detect_language(text):
    """Tinutukoy ang wika ng tanong.

    Returns one of ``'english'``, ``'tagalog'``, ``'waray'`` o ``None`` kung
    hindi sigurado (mahina ang signal).
    """
    english, tagalog, waray = score_languages(text)

    # Waray detection: kailangan malakas ang signal dahil maraming salitang
    # Waray ang kahawig ng Tagalog.
    if waray >= 2 and waray >= tagalog and waray >= english:
        return "waray"

    if english == 0 and tagalog == 0:
        # Walang function-word marker (hal. "time management" lang ang type).
        if waray >= 1:
            # Kahit isang Waray marker (hal. "maupay", "bulig") ay sapat na.
            return "waray"
        # Kahit isang English content word (hal. "burnout", "overthinker") ay sapat
        # na para ituring na English — MALIBAN kung hiram lang ito sa Tagalog na
        # pangungusap (hal. "Na-overthinker ako" -> Tagalog pa rin).
        content_hits = english_content_hits(text)
        if content_hits:
            if is_taglish_borrowed_use(text, content_hits):
                return "tagalog"
            return "english"
        return None

    if english > tagalog:
        return "english"
    if tagalog > english:
        return "tagalog"
    return None


# ---------------------------------------------------------------------------
# POST-CHECK: output validation ng wika ng AI reply
# ---------------------------------------------------------------------------
# Kapag English ang hiningi pero Tagalog ang binigay ng AI (o kabaligtaran),
# hindi ito ipapakita sa user. Magre-retry muna na may correction prompt,
# at kapag mali pa rin, language-matched fallback ang gagamitin.
# Tinitingnan lang ang unang N characters para hindi maapektuhan ng 1-2
# hiram na salita sa mahabang reply.
POST_CHECK_HEAD_CHARS = 500
# Kailangan ng malinaw na kabaligtaran (hindi 1 salita lang) bago ituring na mali.
POST_CHECK_MIN_OPPOSITE_MARKERS = 2


def _head_text(text, limit=POST_CHECK_HEAD_CHARS):
    return (text or "")[:limit]


def ai_reply_matches_language(reply, expected):
    """True kapag ang AI reply ay tumutugma sa hininging wika.

    Mahigpit sa kabaligtaran (hal. hiningi English pero malinaw na Tagalog),
    pero maluwag sa halo (Taglish na may English markers ay pasado sa English).
    Kapag hindi malinaw (None), pasado — hindi natin pine-penalize ang AI
    sa ambiguous na sagot.
    """
    expected = (expected or "tagalog").lower()
    if expected not in LANGUAGE_CHOICES:
        expected = "tagalog"
    head = _head_text(reply)
    english, tagalog, waray = score_languages(head)
    content_hits = english_content_hits(head)
    if expected == "english":
        # Mas mahigpit kapag English ang hiningi: kahit ISANG malinaw na
        # Tagalog/Waray marker lang na nangunguna sa English markers ay
        # sapat na para ituring na mali ang wika (hal. "Salamat!",
        # "Oo nga, tama ka.", "Maupay!"). Dati ay kailangan ng 2 markers kaya
        # napapalampas ang mga maikling Tagalog na sagot sa English na tanong.
        # Pinapayagan pa rin ang Taglish (mas mataas ang English marker count).
        if tagalog >= 1 and tagalog > english:
            return False
        if waray >= 1 and waray > english and waray >= tagalog:
            return False
        return True
    if expected == "tagalog":
        if english >= POST_CHECK_MIN_OPPOSITE_MARKERS and english > tagalog and waray < 2:
            # Purong English ang sagot kahit Tagalog ang hiningi.
            # Pero kapag Taglish (may Tagalog markers din), pasado pa rin.
            if tagalog == 0 and not is_taglish_borrowed_use(head, content_hits):
                return False
        if waray >= POST_CHECK_MIN_OPPOSITE_MARKERS and waray >= max(english, tagalog):
            return False
        return True
    # expected == "waray"
    if waray >= 1 and waray >= tagalog:
        return True
    if tagalog >= POST_CHECK_MIN_OPPOSITE_MARKERS and tagalog > max(english, waray):
        return False
    if english >= POST_CHECK_MIN_OPPOSITE_MARKERS and english > max(tagalog, waray):
        return False
    return True


def _post_check_correction_prompt(user_input, expected):
    """Correction prompt para sa retry kapag mali ang wika ng unang AI reply."""
    lang_name = {"english": "English", "tagalog": "Tagalog/Taglish", "waray": "Waray"}.get(expected, "Tagalog/Taglish")
    return (
        f"You answered in the WRONG language. The user wrote: {user_input!r}. "
        f"This message is {lang_name}. Rewrite your previous answer fully in {lang_name} only. "
        f"Do not mix languages."
    )


def pick(language, english, tagalog, waray=None):
    """Pumipili ng string base sa language code (fallback sa Tagalog)."""
    if language == "english":
        return english
    if language == "waray":
        return waray if waray is not None else tagalog
    return tagalog


# ---------------------------------------------------------------------------
# ENGLISH RESPONSES
# ---------------------------------------------------------------------------
# Para sa mga intent na Tagalog ang default na sagot sa bot_logic.INTENTS,
# para English din ang sagot kapag English ang tanong.
ENGLISH_RESPONSES = {
    "greetings": [
        "Hello! 🤍 How are you feeling today?",
        "Hi! 😊 How is everything going for you right now?",
        "Hey there! I'm glad you reached out. How can I support you today?",
    ],
    "gratitude": [
        "You're very welcome 🤍 I'm proud of you for taking care of yourself. I'm here whenever you need me again.",
        "I'm really glad I could help! Remember, you're stronger than you think. Keep taking care of yourself! 💙",
        "Thank you for trusting me. You deserve all the support in the world—keep going!",
    ],
    "stress": [
        "It sounds like things are really heavy for you right now.\nWhen you're stressed:\n• Pause and take a slow breath\n• You don't have to fix everything at once\n• One step at a time",
    ],
    "school_assignment": [
        "You sound pressured by your assignments.\nLet's try this:\n• Break it into small tasks\n• Start with the easiest one\n• Progress first, not perfection",
    ],
    "school_project": [
        "Projects are really stressful, especially group work.\nRemember:\n• You can't control everything\n• Just do what you can\n• Communicate when possible",
    ],
    "school_activity": [
        "Sometimes the load gets too heavy because of activities.\nRemember:\n• You don't have to join everything\n• It's okay to say no\n• Choose what matters to you",
    ],
    "financial_problem": [
        "Financial problems are truly heavy.\nRemember:\n• This does not measure your worth\n• Many students go through this\n• You are not alone",
    ],
    "grounding_request": [
        "Okay, I'm right here with you 🤍\n\n🌬️ **4–4–6 Breathing Exercise**\n"
        "1️⃣ Breathe in slowly through your nose (count 4)\n"
        "2️⃣ Hold your breath (count 4)\n"
        "3️⃣ Breathe out through your mouth (count 6)\n\n"
        "Let's do this three times. It doesn't have to be perfect—we'll do it together."
    ],
    "stress_exams": [
        "I understand how heavy exam stress can be. It's normal, but there are ways to make it lighter. 🤍\n\n"
        "Try this:\n"
        "🧠 **Mind:** When you think \"I'm going to fail,\" replace it with \"I'm doing my best.\"\n"
        "🌬️ **Breath:** Before the exam, breathe deeply. Inhale (4 seconds), hold (4 seconds), exhale (6 seconds). Repeat 3 times.\n"
        "📚 **Study:** Study in small blocks (25 minutes study, 5 minutes break). It works better than cramming.\n"
        "😴 **Sleep:** Prioritize 7–8 hours of sleep. A rested brain performs better.\n\n"
        "Your exam score is not the measure of who you are. What matters is your effort. You can do this! 💪"
    ],
    "procrastination": [
        "Procrastination isn't laziness; it's how our mind avoids stress. But there are ways to fight it.\n\n"
        "Try the **\"5-Minute Rule\"**:\n"
        "1. Pick one small part of your task.\n"
        "2. Set a timer for 5 minutes and do just that. No pressure.\n"
        "3. After 5 minutes, you're allowed to stop.\n\n"
        "Usually the hardest part is starting. Once you start, it's easier to keep going. Just one small step first. 👟"
    ],
    "burnout": [
        "Burnout is your body and mind's serious warning sign that you need rest. 🛑\n\n"
        "Listen to it. This isn't weakness; it's being human.\n\n"
        "Try this:\n"
        "• **Schedule \"do nothing\" time.** Even just 15 minutes.\n"
        "• **Say \"no\"** to things you can no longer carry.\n"
        "• **Sleep.** Sleep is the most effective cure.\n\n"
        "Rest isn't laziness. It's what you need to keep going. 🔋"
    ],
    "time_management": [
        "Help yourself by planning ahead. Use a planner, prioritize your top 3 tasks daily, and say 'no' to extra commitments.\n"
        "Time is your most valuable resource. Protect it fiercely. Even 10 minutes of planning saves hours of stress.\n"
        "\"The key is in not spending time, but in investing it.\" – Stephen R. Covey"
    ],
    "overthinking": [
        "I hear you. Overthinking can feel so heavy, like your mind won't stop running. That's normal, and you're not alone here.\n\n"
        "Here are a few simple ways to slow it down:\n"
        "1. **Write it down.** Put everything on paper. When you see it written, it often looks clearer and less scary.\n"
        "2. **5-4-3-2-1 grounding.** Name 5 things you see, 4 you can touch, 3 you hear, 2 you smell, and 1 you taste. It pulls you back to the present.\n"
        "3. **Give worry a time limit.** Tell yourself, \"I have 10 minutes to think about this.\" When time is up, switch to another task.\n"
        "4. **Check the thought.** Ask yourself, \"Is my fear real, or is it just in my head?\" Often, it's just the mind exaggerating.\n"
        "If it already affects your sleep or appetite, consider talking to your school counselor for deeper support. 💙"
    ],
    "failing_subject": [
        "Seeing a failing grade hurts, and what you feel is valid. But remember: this is not the end.\n\n"
        "This is **feedback**, not a verdict on who you are.\n\n"
        "What you can do:\n"
        "1. **Talk to your professor.** Ask how you can recover.\n"
        "2. **Ask for help.** Find a tutor or study with a classmate who understands.\n\n"
        "Rising from this will make you stronger. You're not alone in this. 🫂"
    ],
    "stress_exam_tl": [
        "I understand the pressure you're feeling. Exam stress is normal for every student. "
        "Try to stay organized—make a study schedule and take regular breaks.\n"
        "What matters is your effort, not a perfect score. You can do this!\n"
        "\"Success is the sum of small efforts repeated day in and day out.\" – Robert Collier"
    ],
    "imposter_syndrome_tl": [
        "Imposter syndrome hits even the most talented people. If you are here, it means you truly deserve it. "
        "Everyone feels it—they just don't say it out loud.\n"
        "Give yourself credit and remember your wins. You are genuine, and you are capable.\n"
        "\"Imposter syndrome is an illusion, not the truth.\" – Unknown"
    ],
    "homesick_tl": [
        "Feeling alone is natural, especially when you're far from home. Stay in touch with your family regularly—video call, chat, even just a message.\n"
        "But also make the most of the people around you now. The mix of family and new friends creates a new home. You've got this!\n"
        "\"You keep three homes: where you came from, where you are now, and where you're going.\" – Unknown"
    ],
    "struggling_grades_tl": [
        "Grades that aren't improving are tiring, but it isn't the end for you. Talk to your teacher about extra credit, tutoring, or what you should focus on.\n"
        "Many students have risen from a low point. Mistakes aren't permanent—they're a chance to improve.\n"
        "\"Every expert was once a beginner.\" – Unknown"
    ],
    "financial_stress_tl": [
        "Financial stress is real, but it isn't forever. Look for school resources: scholarships, grants, student loans, or work-study programs.\n"
        "Make a budget, ask family for help if they can, and accept the help being offered. Being smart with money starts with planning today.\n"
        "\"Money is a tool, not your identity. Use it wisely.\" – Unknown"
    ],
    "burnout_tl": [
        "Burnout is a sign that you need rest. This isn't weakness—it's a sign that you're human. Start with a very small break: just 10 minutes for yourself.\n"
        "Say 'no' to some things. Prioritize your health. No achievement is worth destroying your life for.\n"
        "\"Rest is not neglect. It's an investment in your future.\" – Unknown"
    ],
    "fear_of_failure_tl": [
        "Fear of failing is normal, especially when something truly matters to you. Remember, mistakes aren't the end—they're part of learning.\n"
        "What matters is your courage to try. Your worth does not decrease because of a mistake.\n"
        "\"Failure is a chance to start again more wisely.\" – Henry Ford"
    ],
    "thesis_topic_struggle": [
        "Choosing a thesis topic is a big step, and it's normal to feel pressure. Ask yourself: what topics truly interest you?\n"
        "Start with a broad idea and slowly make it more specific. Talk to your adviser; they're there to guide you.\n"
        "\"The secret of getting ahead is getting started.\" – Mark Twain"
    ],
    "recitation_anxiety": [
        "Nerves during recitation are very common. You're not alone. One way to reduce them is preparation.\n"
        "Try studying the likely questions and thinking through your answers. Remember, you're not expected to be perfect. What matters is that you try.\n"
        "\"Courage is resistance to fear, mastery of fear – not absence of fear.\" – Mark Twain"
    ],
    "feeling_behind": [
        "It's normal to feel behind, especially when lessons move fast. Don't panic.\n"
        "Try talking to your professor or a classmate who understands the topic. Asking for help is a sign of strength.\n"
        "\"It does not matter how slowly you go as long as you do not stop.\" – Confucius"
    ],
    "org_work_overload": [
        "Being active in student organizations is great, but it can easily become overwhelming. Learning to prioritize matters.\n"
        "Which tasks are most important? It's also okay to learn to say no to other responsibilities to protect your time and peace of mind.\n"
        "\"You can do anything, but not everything.\" – David Allen"
    ],
    "groupmate_problem": [
        "It's really frustrating when groupmates don't help. It's normal to feel annoyed.\n"
        "Try setting clear roles and deadlines in your group. If that still doesn't work, calmly talk to the member or raise it with your professor.\n"
        "\"You cannot control the actions of others, but you can control your response.\" – Unknown"
    ],
    "reading_overload": [
        "It's overwhelming when readings pile up. You don't have to read every word.\n"
        "Try skimming—read the introduction, headings, and conclusion to get the main idea. The concept matters, not every detail.\n"
        "\"The goal is to understand, not just to finish.\" – Unknown"
    ],
    "career_anxiety": [
        "It's normal to feel anxious about what happens after college. You're not alone in that.\n"
        "Use this time to explore your interests. Talk to your school's career services; they have many resources for you.\n"
        "\"Your career is a journey, not a destination. It's okay to not have it all figured out.\" – Unknown"
    ],
    # English bersyon ng dalawang Tagalog-default na _tl intent — may English
    # signals ang mga ito kaya umaabot dito ang English na tanong (dating
    # Tagalog ang naibibigay kasi wala silang entry dito).
    "stress_management_tl": [
        "Ongoing stress affects your body and mind—but there are ways to lighten it.\n"
        "Try these:\n"
        "- Write down what's stressing you (a brain dump clears your head)\n"
        "- Move your body for 10 minutes (walk, stretch, breathe deeply)\n"
        "- Cut screen time 30 minutes before sleeping\n"
        "- Talk to a trusted friend, mentor, or school counselor\n\n"
        "If the stress continues and it's already affecting your studies, talk to your guidance counselor or doctor."
    ],
    "motivation_tl": [
        "Motivation follows action—you don't have to feel it first. In the brain, movement comes before the feeling.\n\n"
        "Do this:\n"
        "1. Start with just 2 minutes of the task (the hardest part is starting)\n"
        "2. Put your phone in another room while studying\n"
        "3. Set a small reward for yourself after you finish\n"
        "4. Review your progress every night—one step forward is still progress\n\n"
        "If you've felt no drive to do things you used to enjoy for a long time now, talk to a guidance counselor or doctor. Sometimes it's more than just motivation—and that's okay."
    ],
}


# ---------------------------------------------------------------------------
# TAGALOG RESPONSES
# ---------------------------------------------------------------------------
# Para sa mga intent na English ang default na sagot sa bot_logic.INTENTS,
# para Tagalog din ang sagot kapag Tagalog ang tanong.
TAGALOG_RESPONSES = {
    "perfectionism": [
        "Mabigat ang pagiging perfectionist, at hindi mo kailangang dalhin 'yan mag-isa. Ang pagkakamali ay paraan natin para matuto at lumago.\n"
        "Walang taong perpekto, at 'yan ang nagpapatao sa atin. Ang pag-usad ay laging mas mahalaga kaysa pagiging perpekto.\n"
        "\"Ang pagiging perpekto ay hindi lang tungkol sa kontrol—may takot at sakit ding nakatago sa ilalim nito.\" – Brené Brown"
    ],
    "unmotivated_study": [
        "Normal lang na mawalan ng gana. Subukan mong hanapin ang iyong 'bakit'—i-connect ang mga gawain sa mas malaking pangarap mo.\n"
        "Palitan ang kapaligiran ng pag-aaral, mag-aral kasama ng kaibigan, o magpahinga nang maayos. Ang maliliit na tagumpay ay bumubuo ng momentum.\n"
        "\"Ang motibasyon ang nagpapaumpisa. Ang paulit-ulit na ginagawa ang nagpapatuloy.\" – Jim Ryun"
    ],
    "major_uncertainty": [
        "Okay lang na hindi ka pa sigurado sa kurso mo! Naghahanap ka pa lang ng sarili mo. Kausapin ang adviser, kumuha ng electives, at mag-explore.\n"
        "Maraming estudyante ang nagpapalit ng direksyon—tanda ito na kilala mo ang sarili mo, hindi kabiguan. Magtiwala ka lang sa proseso.\n"
        "\"Ang tanging paraan para magawa ang dakilang gawain ay mahalin ang ginagawa mo.\" – Steve Jobs"
    ],
    "financial_stress": [
        "Totoo ang problema sa pera, pero hindi ito panghabang-buhay. Tingnan ang mga scholarship, part-time work, o tulong mula sa campus.\n"
        "Gumawa ng simpleng budget at humingi ng tulong. Hindi pera ang batayan ng halaga mo o ng kinabukasan mo. Maraming estudyante ang dumaan dito.\n"
        "\"Ang tunay na isyu ay hindi ang pera kundi ang kapayapaan ng isip na nabibili nito.\" – Unknown"
    ],
    "work_school_balance": [
        "Hindi ka makakapagbigay mula sa walang laman na baso. Okay lang bawasan ang mga commitment, kahit pansamantala. Kalidad kaysa dami, lagi.\n"
        "Unahin ang tulog, kalusugan, at malinaw na pag-iisip kaysa sa sobrang pagod. Mas malaking oras ang nasasayang sa burnout kaysa sa pahinga.\n"
        "\"Ang pahinga ay hindi katamaran. Ito ay maintenance.\" – Unknown"
    ],
    "time_management": [
        "Tulungan ang sarili mo sa pagpaplano. Gumamit ng planner, unahin ang tatlong pinakamahalagang gawain araw-araw, at mag-'no' sa dagdag na commitment.\n"
        "Ang oras ang pinakamahalagang resource mo. Protektahan mo ito. Kahit 10 minutong pagpaplano, nakakatipid ng oras at stress.\n"
        "\"Ang sikreto ay hindi sa paggastos ng oras, kundi sa pag-invest dito.\" – Stephen R. Covey"
    ],
    "overthinking": [
        "Naiintindihan ko. Minsan, ang bigat ng mga isip na parang hindi na pwedeng hintayin. Normal lang 'to, at hindi ka mag-isa dito.\n\n"
        "Narito ang ilang simpleng paraan para mapababa ang overthinking:\n"
        "1. **Ibura sa papel.** Isulat ang lahat ng nakaliligalig sa isip mo. Kapag nakita mo ito sa papel, madalas mas malinaw at mas mababa ang takot.\n"
        "2. **5-4-3-2-1 grounding.** Hanapin 5 bagay na nakikita mo, 4 na nararamdaman mo, 3 na naririnig mo, 2 na amoy, at 1 na lasa. Ito ay tumutulong upang bumalik ka sa kasalukuyan.\n"
        "3. **Limitado ang oras ng pag-iisip.** Sabihin sa sarili mo, \"May 10 minutes lang ako para mag-isip dito.\" Pag tapos ang oras, gawin ang ibang gawain.\n"
        "4. **Kumustahan ang sarili.** Tanungin mo ang sarili, \"Totoo ba ang takot ko, o kaya lang ba ito sa isip ko?\" Minsan, kaya lang ito sa isip.\n"
        "Kung sobrang lala na at nakakaapekto sa pagtulog o pagkain, maaari kang kumonsulta sa school counselor para sa mas malalim na tulong. 💙"
    ],
    "imposter_syndrome": [
        "Sobrang karaniwan ang imposter syndrome, lalo na sa mga mahuhusay. Tunay at pinaghirapan mo ang mga naabot mo.\n"
        "Dapat ka rito. Palitan ang 'nagkukunwari lang ako' ng 'natututo pa ako.' Lahat nakakaramdam nito—hindi ka nag-iisa.\n"
        "\"Hindi ka impostor. Ikaw ay nag-aaral. At ang pag-aaral ay paglago.\" – Unknown"
    ],
    "adhd_concentration": [
        "Kung nahihirapan kang mag-focus, maaaring ADHD ito o iba pang dahilan. Magpatingin sa propesyonal.\n"
        "Makakatulong ang mga accommodation gaya ng mas mahabang oras sa test o tahimik na lugar. Maraming matatalinong tao ang may ADHD. Hindi ka sirang tao.\n"
        "\"Hindi tayo binubuhat ng mga paghihirap natin; ang mahalaga ay kung paano tayo tumugon dito.\" – Unknown"
    ],
    "freshman_adjustment": [
        "Ang pag-adjust sa kolehiyo ay hamon para sa lahat. Normal lang na mamiss ang bahay at maligaw. Maging mabait ka sa sarili mo.\n"
        "Sumali sa mga komunidad, i-explore ang campus, at dahan-dahang sumubok ng bago. Ang unang semestre ang pinakamahirap; unti-unti itong magiging madali paglaon.\n"
        "\"Mamulaklak ka kung saan ka itinanim, kahit hindi pamilyar sa'yo ang lupa.\" – Unknown"
    ],
    "impending_deadline": [
        "Kahit dikit ang deadline, hindi makakatulong ang pag-panic. Gawin ang kaya mo ngayon, humingi ng extension kung kailangan, at mag-focus sa isang bagay.\n"
        "Sa susunod, mag-umpisa nang mas maaga. Ginagawa mo ang makakaya mo, at sapat na 'yon. Temporaryo lang ang deadline na ito.\n"
        "\"Pag-usad, hindi pagiging perpekto.\" – Unknown"
    ],
    "test_anxiety": [
        "Karaniwan at nagagamot ang test anxiety. Mag-deep breathing bago at habang nagte-test. Gawing excitement ang kaba.\n"
        "Mag-review gamit ang practice tests, matulog nang sapat, at maging mabait sa sarili mo habang nagte-test. Nag-f-freeze ang utak dahil sa pressure—hindi dahil sa kakulangan ng kaalaman.\n"
        "\"Hindi kaaway ang nervous system mo. Makipagtulungan ka rito.\" – Unknown"
    ],
    "feeling_unmotivated": [
        "Ang mababang motibasyon ay senyales na kailangan mo ng pahinga, break, o pagtingin sa mas malalim na bagay gaya ng depresyon. Pakinggan ang katawan mo.\n"
        "Magsimula sa pinakamaliit: isang 5-minutong gawain. Ang aksyon ang nagdudulot ng motibasyon, hindi baliktad. Maging mabait sa sarili mo.\n"
        "\"Ang motibasyon ay hindi pinagmumulan ng aksyon. Ang aksyon ang pinagmumulan ng motibasyon.\" – Unknown"
    ],
    "loud_roommate": [
        "Kailangan ng komunikasyon at kompromiso ang pakikisama. Kausapin nang mahinahon ang roommate tungkol sa quiet hours at maghanap ng oras na komportable sa inyong dalawa.\n"
        "Gumamit ng earplugs, white noise, o mag-aral sa ibang lugar. Ang pagtatakda ng boundary ay malusog, hindi masama. Dapat din siyang makinig.\n"
        "\"Ang magandang relasyon ay nabubuo sa tapat at malinaw na pag-uusap.\" – Unknown"
    ],
    "difficult_professor": [
        "Nagtuturo ng tibay ang mahihirap na propesor. Kausapin sila sa office hours nang magalang, itanong kung paano ka makakabawi, at dumalo sa tutoring.\n"
        "Tandaan: hindi sinusukat ng grado nila ang talino mo. Marami ka pang magiging propesor—isa lang ito sa mga kabanata ng buhay mo.\n"
        "\"Ang hamon ang nagpapalaki sa'yo.\" – Unknown"
    ],
    "group_project_stress": [
        "Nakakafrustrate ang group projects, pero may natututunan tayong tunay na kasanayan dito. Mag-set ng malinaw na expectations, hatiin nang patas ang gawain, at mag-usap.\n"
        "Kung may hindi tumutulong, harapin ito agad. Hindi mo kontrolado ang iba—ang pagsisikap at ugali mo lang ang kontrolado mo.\n"
        "\"Teamwork makes the dream work.\" – John C. Maxwell"
    ],
    "presentation_fear": [
        "Normal ang takot sa public speaking—kahit ang mga sikat na speaker ay kinakabahan! I-practice ang presentasyon nang maraming beses bago ang araw nito.\n"
        "Tandaan: gusto ng audience na magtagumpay ka. Iniisip nila ang sarili nila, hindi hinuhusgahan ka nang matindi. Kaya mo 'to!\n"
        "\"Mas matapang ka kaysa sa iniisip mo, mas malakas kaysa sa hitsura mo, at mas matalino kaysa sa tingin mo.\" – A.A. Milne"
    ],
    "grades_not_improving": [
        "Hindi tinutukoy ng isang semestre ang buong academic career mo. Kausapin ang propesor, maghanap ng tutor, o magpa-assess para sa learning disability.\n"
        "May mga estudyanteng kailangan ng ibang paraan ng pagtuturo—hindi ito kabiguan, pagtuklas ito. Mahalaga ang pagsisikap at paglago mo.\n"
        "\"Hindi final ang tagumpay, hindi nakamamatay ang kabiguan: ang tapang na magpatuloy ang mahalaga.\" – Winston Churchill"
    ],
    "crisis_situation": [
        "Kung tunay itong emergency, tumawag agad sa emergency services o pumunta sa pinakamalapit na ER ngayon.\n"
        "Mahalaga ka. May tulong na available 24/7. Sinanay ang mga crisis counselor para suportahan ka sa sandaling ito. Mangyaring mag-reach out ngayon.\n"
        "\"Sa krisis, mag-reach out. May mga taong gustong tumulong sa'yo ngayon.\" – Crisis Support"
    ],
    "assignment_overload": [
        "Sabay-sabay dumadating ang mga assignment sa lahat. Unahin ayon sa deadline, at humingi ng extension sa propesor kung kailangan.\n"
        "Huwag ka nang mahiyang humingi ng tulong. Hatiin ang gawain sa araw-araw na bahagi. Hindi mo kailangang tapusin lahat ngayon. Pag-usad kaysa bilis.\n"
        "\"Isang hakbang sa isang pagkakataon. Isang gawain sa isang pagkakataon.\" – Unknown"
    ],
    "fear_of_failure": [
        "Nakaka-paralyze ang takot mabigo, pero senyales ito na malaki ang pinahahalagahan mo. Tandaan, ang kabiguan ay hindi kabaligtaran ng tagumpay; bahagi ito nito.\n"
        "Bawat pagsubok ay pagkakataon para matuto. Hindi nakatali ang halaga mo sa resulta. Maglakas-loob na maging hindi perpekto.\n"
        "\"Ang kabiguan ay tagumpay na nasa proseso.\" – Albert Einstein"
    ],
    "stress_management_tl": [
        "Ang tuloy-tuloy na stress ay nakakaapekto sa katawan at isip—pero may mga paraan para mapagaan ito.\n\n"
        "Subukan ang mga ito:\n"
        "• **Malalim na paghinga (4-7-8):** Huminga nang malalim gamit ang tiyan—4 na bilang habang humihinga, 7 habang hawak ang hangin, 8 habang naglalabas.\n"
        "• **Pahinga ng katawan:** Higpitan nang dahan-dahan ang bawat grupo ng kalamnan, pagkatapos pakawalan.\n"
        "• **Ehersisyo:** Ang 20-30 minutong paggalaw ay tumutulong sa mood at pagtulog.\n"
        "• **Magtakda ng limitasyon:** Bawasan ang mga dagdag na responsibilidad.\n"
        "• **Matulog:** Panatilihin ang regular na oras ng tulog.\n\n"
        "Kung nagpapatuloy ang stress at naaapektuhan na ang pag-aaral mo, makipag-usap sa guidance counselor o sa doktor."
    ],
    "motivation_tl": [
        "Ang motibasyon ay resulta ng aksyon, hindi kinakailangang bago ito. Sa utak, nauuna ang kilos bago ang pakiramdam.\n\n"
        "Gawin ito:\n"
        "1. **Hatiin ang goal:** Gawing napakaliit na gawain (isang talata, 5-minutong lakad).\n"
        "2. **Magsimula ngayon:** Ang momentum ay bumubuo ng momentum. Hindi kailangan ang \"tamang pakiramdam.\"\n"
        "3. **I-celebrate ang maliit na tagumpay:** Bawat natapos na gawain ay nagpapatibay ng nakagawian mo.\n"
        "4. **Gawin itong ugali:** Kapag paulit-ulit mong ginagawa ito sa loob ng 21-66 araw, magiging nakasanayan na ng katawan at isip mo.\n\n"
        "Kung tuloy-tuloy pa rin ang kawalan ng ganang gawin ang dating kinagigiliwan mo, ipa-assess ito sa propesyonal."
    ],
    # Ang dalawang ito ay halo (Tagalog + English) sa bot_logic.INTENTS,
    # kaya kailangan ng purong Tagalog na bersyon.
    "greetings": [
        "Hello! 🤍 Kamusta ka ngayon?",
        "Hi! 😊 Anong balita sa'yo ngayon?",
        "Kamusta! 🤗 Sana okay ka ngayon.",
        "Kumusta ka? Lagi mong tandaan na mahalaga ka at may mga taong handang makinig sa iyo. Ano ang maitutulong ko sa iyo ngayon?",
        "Hello! Bago tayo magsimula, isang paalala para sa iyong seguridad: iwasan ang pagbabahagi ng personal na impormasyon tulad ng buong pangalan, address, o contact details dito. Handa na akong makinig. 🤍",
    ],
    "gratitude": [
        "Walang anuman 🤍 Proud ako sa'yo dahil inaalagaan mo ang sarili mo. Nandito lang ako kung kailangan mo ulit.",
        "Masaya akong nakatulong! Karapat-dapat ka sa lahat ng suporta. Patuloy ka lang—mahalaga ang kalusugan mo!",
        "Salamat sa pagtitiwala sa akin! Proud ako sa iyo dahil nag-effort ka. Lagi kang may suporta dito! 💙",
        "Mahalaga ka, kaya alagaan mo ang sarili mo. Nandito lang ako para sa'yo.",
    ],
}


# ---------------------------------------------------------------------------
# FOLLOW-UP QUESTIONS (English)
# ---------------------------------------------------------------------------
# Kapag English ang tanong pero Tagalog ang naka-store na follow_up sa
# bot_logic.INTENTS, ito ang gagamitin.
ENGLISH_FOLLOW_UPS = {
    "greetings": [
        "Would you like to share what's weighing on you right now?",
        "Is there something you'd like to talk about today?",
        "We can start with how you're feeling right now.",
    ],
    "stress": [
        "What's stressing you out the most right now?",
        "When was the last time you gave yourself a break?",
    ],
    "school_assignment": [
        "Which subject has the heaviest assignment?",
        "When is it due?",
    ],
    "school_project": [
        "Is this a group project or an individual one?",
        "What's the biggest problem with the project right now?",
    ],
    "school_activity": [
        "Is this activity mandatory?",
        "How do you feel when you think about it?",
    ],
    "financial_problem": [
        "Are these school-related expenses or personal ones?",
        "Do you have a scholarship or any support right now?",
    ],
    "grounding_request": [
        "Just tell me when you're done.",
        "How does your body feel now compared to earlier?",
    ],
}


# ---------------------------------------------------------------------------
# GENERIC FALLBACKS
# ---------------------------------------------------------------------------
GENERIC_FALLBACKS_EN = [
    "I hear you. I'm here to listen to you. 💙",
    "I understand. Please tell me more about how you're feeling.",
    "What you're feeling matters. I'm ready to listen.",
    "Thank you for sharing. I'm here to support you.",
    "You don't have to face everything alone. You can talk to me about this.",
]

GENERIC_FALLBACKS_TL = [
    "Naririnig kita. Nandito lang ako para makinig sa'yo. 💙",
    "Naiintindihan ko. Ikwento mo pa sa akin ang nararamdaman mo.",
    "Mahalaga ang nararamdaman mo. Handa akong makinig.",
    "Salamat sa pagbabahagi. Nandito ako para suportahan ka.",
    "Hindi mo kailangang harapin ang lahat mag-isa. Pwede mo akong kausapin tungkol dito.",
]


# ---------------------------------------------------------------------------
# ABUSIVE-LANGUAGE REPLY / ACADEMIC REFERRAL
# ---------------------------------------------------------------------------
ABUSIVE_RESPONSE_EN = (
    "I understand you might be frustrated, but let's keep our conversation respectful. "
    "How can I help you in a healthy way right now?"
)

ACADEMIC_REFERRAL_EN = (
    "I can help most with academic struggles such as assignments, projects, exam stress, "
    "and time management. For other topics, try another AI like ChatGPT or Google Bard."
)


# ---------------------------------------------------------------------------
# TAGALOG CRISIS RESPONSE
# ---------------------------------------------------------------------------
CRISIS_RESPONSE_TL = """🚨 NARIRINIG KITA, AT NAGMAMALASAKIT AKO 🚨

Totoo ang sakit na nararamdaman mo, at karapat-dapat kang makatanggap ng tulong AGAD. PAKITAWAG sa kahit sino sa mga ito NGAYON:

📞 **CRISIS HOTLINE NUMBERS:**
• PNP Suicide Hotline: 0917-558-5999
• HOPELINE: 2389-6363
• In Touch Crisis Line: (02) 8969-9119
• Lifeline PH: (02) 8817-2222

🏥 **AGARANG GAGAWIN:**
1. Tumawag sa emergency (911) kung nasa panganib ka ngayon
2. Pumunta sa pinakamalapit na ER ng ospital
3. Sabihin agad sa pinagkakatiwalaang tao: magulang, kaibigan, guro, counselor
4. I-text ang HOPE sa +63917-558-5999

⏰ **NGAYON NA:**
- Wala kang kailangang madaliin. Huminga ka muna nang malalim.
- Totoo ang nararamdaman mo. Mahalaga ang buhay mo.
- Pansamantala lang ang sakit na ito. Magbabago ito, ipinapangako ko.
- May mga taong nakaramdam din ng ganito at gumaling.

💙 "Mahalaga ka nang higit sa alam mo. Mangyaring manatili. Mangyaring mag-reach out. Hindi ka nag-iisa."

PAKITAWAG sa isa sa mga numerong 'yan o pumunta sa ER. Kampi ako sa'yo. Hindi pa tapos ang kuwento mo."""


# ---------------------------------------------------------------------------
# TAGALOG DEFAULT FAQ ANSWERS
# ---------------------------------------------------------------------------
DEFAULT_FAQ_ANSWERS_TL = {
    "para saan ang app na ito": (
        "Ang app na ito ay isang chatbot na sumusuporta sa mga estudyanteng nahihirapan sa akademiko. "
        "Nagtuturo ito ng study guidance, nagbibigay ng motibasyon, at praktikal na tulong sa stress sa paaralan."
    ),
    "paano ko magagamit ang chatbot na ito": (
        "I-type mo lang dito ang mga alalahanin mo sa pag-aaral at sasagutin ka ng chatbot ng suporta, "
        "mga study tip, at praktikal na gabay kapag kailangan."
    ),
    "sino ang pwedeng gumamit ng app na ito": (
        "Ang app na ito ay para sa mga estudyanteng gustong matulungan sa mga hamon sa pag-aaral gaya ng "
        "exam, assignment, time management, at stress sa paaralan."
    ),
}
