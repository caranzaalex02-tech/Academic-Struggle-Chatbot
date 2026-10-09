# bot_logic.py
import csv
import os
import random
import re
import sqlite3
import logging
import time
from pathlib import Path

try:  # Normal package import (Flask app / pytest)
    from .bot_responses_i18n import (
        ABUSIVE_RESPONSE_EN,
        ACADEMIC_REFERRAL_EN,
        CRISIS_RESPONSE_TL,
        DEFAULT_FAQ_ANSWERS_TL,
        ENGLISH_FOLLOW_UPS,
        ENGLISH_RESPONSES,
        GENERIC_FALLBACKS_EN,
        GENERIC_FALLBACKS_TL,
        LANGUAGE_CHOICES,
        TAGALOG_RESPONSES,
        ai_reply_matches_language,
        detect_language,
        pick as _language_pick,
        score_languages,
    )
except ImportError:  # pragma: no cover - kapag direktang pinatakbo bilang script
    from bot_responses_i18n import (
        ABUSIVE_RESPONSE_EN,
        ACADEMIC_REFERRAL_EN,
        CRISIS_RESPONSE_TL,
        DEFAULT_FAQ_ANSWERS_TL,
        ENGLISH_FOLLOW_UPS,
        ENGLISH_RESPONSES,
        GENERIC_FALLBACKS_EN,
        GENERIC_FALLBACKS_TL,
        LANGUAGE_CHOICES,
        TAGALOG_RESPONSES,
        ai_reply_matches_language,
        detect_language,
        pick as _language_pick,
        score_languages,
    )


# Heavy AI SDKs are imported lazily (inside the _call_*_api functions) so that
# the web worker does NOT load google.generativeai / openai / groq at startup.
# Loading them eagerly was causing "Worker was sent SIGKILL! Perhaps out of
# memory?" on small (512 MB) Render/Heroku dynos.
openai = None
genai = None
groq = None

# Sentinel used to remember that a module failed to import, so we don't retry.
_IMPORT_FAILED = object()


def _import_openai():
    global openai
    if openai is None:
        try:
            import openai as _openai
            openai = _openai
        except ImportError:
            openai = _IMPORT_FAILED
    return None if openai is _IMPORT_FAILED else openai


def _import_genai():
    global genai
    if genai is None:
        try:
            import google.generativeai as _genai
            genai = _genai
        except ImportError:
            genai = _IMPORT_FAILED
    return None if genai is _IMPORT_FAILED else genai


def _import_groq():
    global groq
    if groq is None:
        try:
            import groq as _groq
            groq = _groq
        except ImportError:
            groq = _IMPORT_FAILED
    return None if groq is _IMPORT_FAILED else groq


try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

conversation_memory = {}


def _get_db_path():
    return os.environ.get("MENTALHEALTHWEB_DB", "database.db")

# ----------------------------
# CRISIS KEYWORDS & RESPONSE
# ----------------------------
CRISIS_KEYWORDS = {
    "i want to suicide", "suicide", "i want to kill myself", "kill myself", "kill me", "i want to end my life",
    "gusto ko mamatay", "gusto ko patayin sarili ko", "patayin ko sarili ko", "i want to die", "want to die",
    "can't go on", "hindi ko na kaya", "i can't go on", "i feel hopeless", "wala na akong pag-asa",
    "walang pag-asa", "mas mabuti na mamatay na lang ako", "feel like giving up", "give up", "feel worthless",
    "hindi na ako mahalaga", "diyos alam", "gusto ko nalang mamatay", "mag bibigti ako", "sasaksakin ko sarili ko",
    "pumatay", "gusto ko na mamatay", "ayoko na mabuhay", "magpakamatay", "wala nang silbi ang buhay ko",
    "wala na akong magawa", "sawa na ako sa buhay", "ayoko nang mabuhay", "di ko na alam", "hindi ko na gusto mabuhay",
    "maubos na ako", "patayin na ako", "umiyak na ako", "walang pag-asa na pagbabago"
}

CRISIS_RESPONSE = """🚨 I HEAR YOU, AND I CARE 🚨

Your pain is real, and you deserve immediate support. PLEASE reach out to someone RIGHT NOW:

📞 **CRISIS HOTLINE NUMBERS:**
• PNP Suicide Hotline: 0917-558-5999
• HOPELINE: 2389-6363
• In Touch Crisis Line: (02) 8969-9119
• Lifeline PH: (02) 8817-2222

🏥 **IMMEDIATE ACTION:**
1. Call emergency (911) if you're in immediate danger
2. Go to the nearest hospital ER
3. Tell a trusted person: parent, friend, teacher, counselor NOW
4. Text HOPE to +63917-558-5999

⏰ **RIGHT NOW:**
- You don't have to do anything rash. Just take one breath.
- Your feelings ARE valid. Your life IS valuable.
- This pain is temporary. It WILL change, I promise.
- Other people have felt this exact way and got better.

💙 "You matter more than you know. Please stay. Please reach out. You're not alone."

PLEASE contact one of those numbers or go to ER. I'm rooting for you. Your story isn't over yet."""

WARAY_CRISIS_RESPONSE = """🚨 NAMAMATI AKO, NGAN NAGPAPAHALAGA AKO 🚨

Tinuod an imo kasakit, ngan angay ka buligan yana dayon. PALIHOG pakipag-istorya ha iba:

📞 **CRISIS HOTLINE NUMBERS:**
• PNP Suicide Hotline: 0917-558-5999
• HOPELINE: 2389-6363
• In Touch Crisis Line: (02) 8969-9119
• Lifeline PH: (02) 8817-2222

🏥 **IMMEDIATE ACTION:**
1. Tumawag ha emergency (911) kung ikaw in aada ha peligro
2. Kumadto ha pinaka-hirani nga hospital ER
3. Sumat ha imo gintatapuran: kag-anak, sangkay, o teacher YANA
4. Text HOPE to +63917-558-5999

💙 "Importante ka. Alayon pagpabilin. Alayon pagsumat. Diri ka nag-uusahan."

PLEASE contact one of those numbers or go to ER. Diri pa tapos an imo istorya."""

# ----------------------------
# ABUSIVE KEYWORDS & RESPONSE
# ----------------------------
ABUSIVE_KEYWORDS = {
    "bobo", "tanga", "gago", "putangina", "walang kwenta", "pota", "inutil",
    "fuck you", "stupid bot", "useless bot", "tangina mo", "tanga mo", "putang ina mo", "putangina mo",
    "gago ka", "wala kang silbi"
}

# ----------------------------
# INTENT PRIORITY
# ----------------------------
INTENT_PRIORITY = {
   
    "greetings": 1,
    "gratitude": 0,
    "grounding_request": 6,
    "stress": 4,
    "overthinking": 4,
   
    "school_assignment": 4,
    "school_project": 4,
    "school_activity": 3,
    "financial_problem": 3,
   
    "stress_exams": 5,
    "procrastination": 5,
    "perfectionism": 5,
    "unmotivated_study": 5,
    "failing_subject": 5,
    "major_uncertainty": 5,
    
    "financial_stress": 5,
    "work_school_balance": 5,
    "burnout": 5,
    "time_management": 5,
    
    "imposter_syndrome": 5,
    "adhd_concentration": 5,
    "freshman_adjustment": 5,
   
    "impending_deadline": 5,
    "test_anxiety": 5,
    "feeling_unmotivated": 5,
    "loud_roommate": 5,
    "difficult_professor": 5,
    "group project stress": 5,
    "presentation_fear": 5,
    "grades_not_improving": 5,
   
    "crisis_situation": 6,
   
    "assignment_overload": 5,
   
    "stress_exam_tl": 5,
   
    "procrastination_tl": 5,
    "perfectionism_tl": 5,
    
    "imposter_syndrome_tl": 5,
    "homesick_tl": 5,
    "struggling_grades_tl": 5,
    "financial_stress_tl": 5,
    "burnout_tl": 5,
    
    "stress_management_tl": 5,
    "motivation_tl": 5,
    "fear_of_failure": 5,
    "fear_of_failure_tl": 5,
    "thesis_topic_struggle": 5,
    "recitation_anxiety": 5,
    "feeling_behind": 5,
    "org_work_overload": 5,
    "groupmate_problem": 5,
    "reading_overload": 5,
    "career_anxiety": 5,
    
}

# ----------------------------
# INTENTS
# ----------------------------
INTENTS = {
    # ------------------------
    # GREETINGS / HELLO
    # ------------------------
    "greetings": {
        "signals": [
            "hello", "hi", "kamusta", "good morning", "good afternoon", "good evening", "hey", "yo",
            "greetings", "magandang araw", "magandang gabi", "magandang umaga", "hello po", "hiii",
            "kamusta ka", "hi po", "hello there", "hey there"
        ],
        "response": [
            "Hello! 🤍 Kamusta ka ngayon?",
            "Hi! 😊 Anong balita sa’yo ngayon?",
            "Kamusta! 🤗 Sana okay ka ngayon.",
            "Hello! How are you feeling today?",
            "Hi there! I hope you're doing well. How can I support you today?",
            "Hey! It's good to hear from you. How's your day going?",
            "Kumusta ka? Palagi mo tandaan na mahalaga ka at may mga tao na handang makinig sa iyo. Ano ang maitutulong ko sa iyo ngayon?",
            "Hi! Handa akong makinig sa'yo. May alam ako na pwedeng makatulong sa iyo.",
            "Hello! Bago tayo magsimula, isang paalala para sa iyong seguridad: iwasan ang pagbabahagi ng personal na impormasyon tulad ng buong pangalan, address, o contact details dito. Handa na akong makinig. 🤍"
        ],
        "follow_up": [
            "Gusto mo bang ikwento kung ano ang bumibigat sa’yo ngayon?",
            "May gusto ka bang pag-usapan ngayon?",
            "Puwede nating simulan sa kung ano ang nararamdaman mo."
        ]
    },

    # ------------------------
    # EMOTIONAL / ACADEMIC STRUGGLE (Conversational)
    # ------------------------
    "stress": {
        "signals": ["stress", "sobrang stress", "nakaka stress", "pressure", "pagod na pagod na ako"],
        "response": [
            "Mukhang mabigat talaga ang pinagdadaanan mo ngayon.\nKapag stressed:\n• Huminto sandali at huminga\n• Hindi mo kailangang ayusin lahat agad\n• One step at a time lang"
        ],
        "follow_up": [
            "Ano ang pinaka-nakaka-stress sa’yo ngayon?",
            "Kailan mo huling binigyan ng pahinga ang sarili mo?"
        ]
    },
    "overthinking": {
        "signals": ["overthink", "overthinker", "overthinking", "isip nang isip", "di matigil kakaisip", "hindi matigil kakaisip", "panay ang isip"],
        "response": [
            "Naiintindihan ko. Minsan, ang bigat ng mga isip na parang hindi na pwedeng hintayin. Normal lang 'to, at hindi ka mag-isa dito."
        ],
        "follow_up": []
    },
    

    # ------------------------
    # ACADEMIC LIFE (Conversational)
    # ------------------------
    "school_assignment": {
        "signals": ["assignment", "homework", "deadline", "di ko matapos ang assignment", "burubuhaton", "uulohan", "damo an assignment", "damo buruhaton"],
        "response": [
            "Mukhang pressured ka sa assignments.\nTry natin ito:\n• Hatiin sa maliliit na tasks\n• Unahin ang pinakamadali\n• Progress muna, hindi perfect"
        ],
        "follow_up": [
            "Anong subject ang may pinakamabigat na assignment?",
            "Kailan ang deadline nito?"
        ]
    },
    "school_project": {
        "signals": ["project", "group project", "hirap sa project", "final project", "research", "thesis", "grupo", "mabug-at an project"],
        "response": [
            "Nakaka-stress talaga ang projects, lalo na kung group work.\nPaalala:\n• Hindi lahat kontrolado mo\n• Gawin ang kaya mo\n• Mag-communicate kung pwede"
        ],
        "follow_up": [
            "Group project ba ito o individual?",
            "Ano ang pinaka-problem sa project ngayon?"
        ]
    },
    "school_activity": {
        "signals": ["school activity", "event sa school", "extra curricular", "org work"],
        "response": [
            "Minsan sumosobra ang load dahil sa activities.\nTandaan:\n• Hindi mo kailangang salihan lahat\n• Okay lang tumanggi\n• Piliin ang mahalaga sa’yo"
        ],
        "follow_up": [
            "Mandatory ba ang activity na ito?",
            "Ano ang pakiramdam mo kapag iniisip mo ito?"
        ]
    },

    # ------------------------
    # PERSONAL / LIFE (Conversational)
    # ------------------------
    "financial_problem": {
        "signals": ["walang pera", "financial problem", "kulang ang budget", "problema sa pera", "waray kwarta", "waray balon", "pamasahe", "bayadan ha school", "tuition"],
        "response": [
            "Mabigat talaga ang problemang pinansyal.\nPaalala:\n• Hindi pera ang batayan ng halaga mo\n• Maraming students ang dumadaan dito\n• Hindi ka nag-iisa"
        ],
        "follow_up": [
            "School-related ba ang gastos o personal?",
            "May scholarship o support ka ba ngayon?"
        ]
    },
    

    # ------------------------
    # GROUNDING / BREATHING
    # ------------------------
    "grounding_request": {
        "signals": ["gusto ko kumalma", "help me calm down", "di ako mapakali", "sobrang kinakabahan", "panic ako", "breathing exercise", "grounding exercise"],
        "response": [
            "Sige, samahan kita 🤍\n\n🌬️ **4–4–6 Breathing Exercise**\n"
            "1️⃣ Huminga nang dahan-dahan sa ilong (bilang ng 4)\n"
            "2️⃣ Hawakan ang hininga (bilang ng 4)\n"
            "3️⃣ Ilabas ang hininga sa bibig (bilang ng 6)\n\n"
            "Ulitin natin ito ng 3 beses. Hindi kailangang perpekto—sabay lang tayo."
        ],
        "follow_up": [
            "Sabihin mo lang kapag tapos ka na.",
            "Ano ang pakiramdam ng katawan mo ngayon kumpara kanina?"
        ]
    },

    # ------------------------
    # GRATITUDE / CLOSING
    # ------------------------
    "gratitude": {
        "signals": [
            "salamat", "maraming salamat", "thanks", "thank you", "grateful", "thank u", "thankyou",
            "appreciate", "appreciate it", "you helped", "tulong mo", "nakatulong ka", "binigyan mo ako", "ginawa mo"
        ],
        "response": [
            "Walang anuman 🤍 Proud ako sa’yo dahil inaalagaan mo ang sarili mo. Nandito lang ako kung kailangan mo ulit.",
            "You're very welcome! I'm really glad I could help. Remember, you're stronger than you think. Keep taking care of yourself! 💙",
            "It makes me so happy to hear that! You deserve all the support in the world. Keep going—I believe in you!",
            "Thank you for trusting me with your thoughts. You're doing amazing by reaching out and taking care of yourself!",
            "Masaya akong nakatulong! Ikaw ay deserve ng lahat ng suporta. Patuloy lang at mahalaga ang iyong kalusugan!",
            "Salamat sa pagtitiwala sa akin! Proud ako sa iyo dahil nag-effort ka. Lagi kang may suporta dito! 💙",
            "Ikaw ay napakaganda ng tao dahil nag-aalaga ka sa iyong sarili. Patuloy mo lang yan!",
            "Glad I could be here for you! Remember, reaching out is a sign of strength, not weakness. You've got this! 💪"
        ],
        "follow_up": []
    },

    
    "stress_exams": {
        "signals": ["exam", "tests", "studying", "midterm", "finals", "how to manage exam", "reduce exam stress", "tips exam", "paano i-manage exam", "pano stress sa exam", "how to study", "manage exam anxiety", "test anxiety", "exam pressure", "makuri an exam", "kulba ha exam", "baraka ha test", "paso"],
        "response": ["""Naiintindihan ko ang bigat ng exam stress. Normal 'yan, pero may mga paraan para gumaan ang pakiramdam mo. 🤍

Subukan natin 'to:
🧠 **Isip:** Kapag naiisip mong "babagsak ako," palitan mo ng "ginagawa ko ang best ko."
🌬️ **Hininga:** Bago mag-exam, huminga nang malalim. Inhale (4 seconds), hold (4 seconds), exhale (6 seconds). Ulitin ng 3 beses.
📚 **Aral:** Mag-aral nang paunti-unti (e.g., 25 mins aral, 5 mins pahinga). Mas epektibo 'to kaysa sa isang bagsakan.
😴 **Tulog:** Unahin ang 7-8 oras na tulog. Mas matalino ang utak na nakapagpahinga.

Ang score mo sa exam ay hindi batayan ng pagkatao mo. Ang mahalaga ay ang iyong pagsisikap. Kaya mo 'yan! 💪"""]
,
        "follow_up": []
    },
    "procrastination": {
        "signals": ["procrastinate", "procrastinating", "deadline", "last minute", "late submission", "how to stop procrastinating", "avoid procrastination", "pano hindi magprocrastinate", "tips procrastination", "manage procrastination"],
        "response": ["""Ang procrastination ay hindi katamaran; paraan ito ng isip natin para iwasan ang stress. Pero may paraan para labanan 'yan.

Subukan ang **"5-Minute Rule"**:
1.  Piliin ang isang maliit na parte ng gawain mo.
2.  Mag-timer ng 5 minuto at gawin lang 'yun. Walang pressure.
3.  Pagkatapos ng 5 minuto, pwede kang huminto.

Kadalasan, ang pinakamahirap na parte ay ang pagsisimula. Kapag nasimulan mo na, mas madali nang magtuloy-tuloy. Isang maliit na hakbang lang muna. 👟"""]
,
        "follow_up": []
    },
    "perfectionism": {
        "signals": ["perfectionist", "perfect", "not good enough", "how to stop perfectionism", "deal with perfectionism", "pano huwag maging perfectionist", "manage perfectionism", "reduce perfectionist"],
        "response": ["""Perfectionism is a heavy burden you don't deserve to carry. Mistakes are how we learn and grow. 
Nobody is perfect, and that's what makes us human and relatable. Progress over perfection always wins.
"Perfection is not just about control, it's also about the fear and pain that may hide underneath." – Brené Brown"""],
        "follow_up": []
    },
    "unmotivated_study": {
        "signals": ["unmotivated", "lose motivation", "bored", "uninterested", "don't care"],
        "response": ["""Losing motivation is normal. Try finding your 'why'—connect assignments to bigger life goals. 
Change your study environment, study with friends, or take a strategic break. Small wins rebuild momentum.
"Motivation is what gets you started. Habit is what keeps you going." – Jim Ryun"""],
        "follow_up": []
    },
    "failing_subject": {
        "signals": ["failing", "fail", "failed", "flunking", "bad grade", "low score", "hagubo an grado", "bagsak", "waray makapasa", "singko", "diri pasar"],
        "response": ["""Masakit makakita ng bagsak na grado, at valid ang nararamdaman mo. Pero tandaan: hindi ito ang katapusan.

Ito ay **feedback**, hindi hatol sa pagkatao mo.

Mga pwedeng gawin:
1.  **Kausapin ang iyong propesor.** Magtanong kung paano ka makakabawi.
2.  **Humingi ng tulong.** Maghanap ng tutor o magpaturo sa kaklaseng nakakaintindi.

Ang pagbangon mula dito ang magpapatatag sa'yo. Hindi ka nag-iisa rito. 🫂"""]
,
        "follow_up": []
    },
    "major_uncertainty": {
        "signals": ["major", "course", "change major", "wrong major", "unsure what to study", "diri sigurado ha course", "sayop nga kurso"],
        "response": ["""It's okay to be unsure about your major! You're still discovering yourself. Talk to advisors, take electives, and explore.
Many students change directions—it shows self-awareness, not failure. Trust your journey.
"The only way to do great work is to love what you do." – Steve Jobs"""],
        "follow_up": []
    },

   
    "financial_stress": {
        "signals": ["money", "financial", "poor", "bills", "debt", "tuition", "broke"],
        "response": ["""Financial stress is real, but temporary. Look into scholarships, part-time work, or campus resources for aid.
Create a basic budget and ask for help. Money doesn't define your worth or your future. Many students have faced this.
"The real issue isn't money. It's the peace of mind money buys." – Unknown"""],
        "follow_up": []
    },
    "work_school_balance": {
        "signals": ["work", "job", "busy", "no time", "overwhelmed", "packed schedule"],
        "response": ["""You can't pour from an empty cup. It's okay to reduce commitments, even temporarily. Quality over quantity always.
Prioritize sleep, health, and sanity over grinding. Burnout wastes more time than rest ever will.
"Rest is not laziness. It's maintenance." – Unknown"""],
        "follow_up": []
    },
    "burnout": {
        "signals": ["burned out", "burnout", "exhausted", "pagod na pagod", "drained", "empty", "ikapoy", "waray gana mag-aral", "kakapoy", "bug-at an lawas"],
        "response": ["""Ang burnout ay seryosong warning sign mula sa katawan at isip mo na kailangan mo na ng pahinga. 🛑

Pakinggan mo 'yan. Hindi ito kahinaan; ito ay pagiging tao.

Subukan mo ito:
•  **Mag-iskedyul ng "walang gagawin" na oras.** Kahit 15 minuto lang.
•  **Sabihin ang "hindi"** sa mga bagay na hindi mo na kaya.
•  **Matulog.** Ang tulog ang pinakamabisang lunas.

Ang pahinga ay hindi pagiging tamad. Ito ay kailangan para makapagpatuloy ka. 🔋"""]
,
        "follow_up": []
    },
    "time_management": {
        "signals": ["time management", "manage time", "organize", "schedule", "busy"],
        "response": ["""Help yourself by planning ahead. Use a planner, prioritize your top 3 tasks daily, and say 'no' to extra commitments.
Time is your most valuable resource. Protect it fiercely. Even 10 minutes of planning saves hours of stress.
"The key is in not spending time, but in investing it." – Stephen R. Covey"""],
        "follow_up": []
    },    

    "imposter_syndrome": {
        "signals": ["imposter", "fraudster", "don't deserve", "fake", "not smart enough"],
        "response": ["""Imposter syndrome is incredibly common, especially among high achievers. Your accomplishments are real and earned by YOU.
You belong here. Replace "I'm pretending" with "I'm learning." Everyone feels this at times—you're not alone.
"You are not an imposter. You are a learner. And learnings equal growth." – Unknown"""],
        "follow_up": []
    },
    "adhd_concentration": {
        "signals": ["focus", "concentrate", "attention", "adhd", "can't focus", "distracted", "scatterbrained"],
        "response": ["""If you struggle to focus, you might have ADHD or other factors at play. Get tested by a professional.
Accommodations like longer test time or quiet spaces can help. Many brilliant people have ADHD. You're not broken.
"Our struggles don't define us. Our response to them does." – Unknown"""],
        "follow_up": []
    },
    "freshman_adjustment": {
        "signals": ["freshman", "adjustment", "homesick", "first year", "new student", "transition"],
        "response": ["""College transition is an adjustment for everyone. It's normal to miss home and feel lost. Give yourself grace.
Join communities, explore campus, and try new things slowly. First semester is the hardest; it gets easier.
"Bloom where you are planted, even if that soil feels unfamiliar." – Unknown"""],
        "follow_up": []
    },

   
    "impending_deadline": {
        "signals": ["deadline is coming", "due soon", "due tomorrow", "last minute", "running out of time"],
        "response": ["""Even with tight deadlines, panic won't help. Do what you can right now, ask for extension if needed, focus on one thing.
Next time, prioritize earlier. You're doing your best, and that's enough. This deadline is temporary.
"Progress, not perfection." – Unknown"""],
        "follow_up": []
    },
    "test_anxiety": {
        "signals": ["test anxiety", "test anxiety", "nervous test", "blank mind", "freeze on test"],
        "response": ["""Test anxiety is common and treatable. Practice deep breathing before and during. Reframe nerves as excitement.
Study with practice tests, get enough sleep, and be kind to yourself while testing. Your brain freezes from pressure—not lack of knowledge.
"Your nervous system is not your enemy. Work with it." – Unknown"""],
        "follow_up": []
    },
    "feeling_unmotivated": {
        "signals": ["no motivation", "unmotivated", "don't feel like", "lazy", "no energy"],
        "response": ["""Low motivation often signals need for rest, a break, or addressing deeper issues like depression. Listen to your body.
Start tiny: one 5-minute task. Motivation follows action, not the other way around. Be patient with yourself.
"Motivation is not the source of action. Action is the source of motivation." – Unknown"""],
        "follow_up": []
    },
    "loud_roommate": {
        "signals": ["roommate", "noisy", "loud", "living with", "dorm", "can't sleep"],
        "response": ["""Living with others requires communication and compromise. Talk calmly about quiet hours and find times that work for both.
Use earplugs, white noise, or study elsewhere. Setting boundaries is healthy, not mean. It's their job to listen too.
"Healthy relationships are built on honest communication." – Unknown"""],
        "follow_up": []
    },
    "difficult_professor": {
        "signals": ["professor", "teacher", "instructor", "difficult", "unfair", "harsh", "grading"],
        "response": ["""Difficult professors teach resilience. Talk to them during office hours respectfully, ask how to improve, attend tutoring.
Remember: their grading doesn't determine your intelligence. You'll have many professors—this is one chapter.
"Challenges are what make you grow." – Unknown"""],
        "follow_up": []
    },
    "group_project_stress": {
        "signals": ["group project", "group work", "group members", "team", "collaboration"],
        "response": ["""Group projects are frustrating, but they teach real-world skills. Set clear expectations upfront, divide work fairly, and communicate.
If someone isn't pulling weight, address it early. You can't control others—only your effort and attitude.
"Teamwork makes the dream work." – John C. Maxwell"""],
        "follow_up": []
    },
    "presentation_fear": {
        "signals": ["presentation", "present", "public speaking", "speech", "speak in front"],
        "response": ["""Public speaking fear is normal—even famous speakers get nervous! Practice your talk multiple times beforehand.
Remember: the audience wants you to succeed. They're thinking about themselves, not judging you harshly. You've got this!
"You are braver than you believe, stronger than you seem, and smarter than you think." – A.A. Milne"""],
        "follow_up": []
    },
    "grades_not_improving": {
        "signals": ["grades", "grade", "gpa", "low grades", "not improving", "struggling academically"],
        "response": ["""One semester doesn't define your academic career. Talk to your professor, find a tutor, or get tested for learning disabilities.
Some students need different teaching styles—that's not failure, it's discovery. Your effort and growth matter.
"Success is not final, failure is not fatal: it's the courage to continue that counts." – Winston Churchill"""],
        "follow_up": []
    },
  
    "crisis_situation": {
        "signals": ["crisis", "emergency", "critical", "urgent", "immediate help", "help now"],
        "response": ["""If this is truly an emergency, please contact emergency services immediately or go to an ER now.
You matter. Help is available 24/7. Crisis counselors are trained to support you through this moment. Please reach out now.
"In crisis, reach out. There are people who want to help you right now." – Crisis Support"""],
        "follow_up": []
    },
   
    "assignment_overload": {
        "signals": ["overload", "too much", "assignments", "too many projects", "drowning"],
        "response": ["""Multiple assignments hit at once for everyone. Prioritize by deadline, reach out to professors for extensions if needed.
Ask for help without shame. Break work into daily chunks. You don't have to do everything today. Progress over speed.
"One step at a time. One task at a time." – Unknown"""],
        "follow_up": []
    },
 

    # ==================== TAGALOG ENTRIES ====================
    "stress_exam_tl": {
        "signals": ["stress sa exam", "exam stress", "medyo anxious sa exam", "takot sa exam", "pressure ng test", "araw-araw binibigla", "exam na papunta"],
        "response": ["""Naiintindihan ko ang pressure na nararamdaman mo. Ang stress sa exam ay normal para sa lahat ng estudyante. Subukan mong maging organized—gumawa ng study schedule at mag-break regularly.
Ang mahalaga ay ang iyong pagsisikap, hindi ang perpektong score. Kayang-kaya mo yan!
"Ang tagumpay ay unti-unting pag-abot sa pangarap araw-araw." – Robert Collier"""],
        "follow_up": []
    },

   

    "imposter_syndrome_tl": {
        "signals": ["imposter syndrome", "hindi ko deserve", "swerte lang", "fraud", "makakadiscover sila", "hindi ako talaga magaling"],
        "response": ["""Ang imposter syndrome ay lalo sa mga magagaling na tao! Kung nandito ka, ibig sabihin, deserve mo talaga ito. Tinatamaan ang lahat, pero hindi lang nila sinasabi.
Magbigay ka sa sarili mo ng magandang feedback—tandaan ang mga nagawa mo. Ikaw ay genuine, at kaya mo talaga.
"Ang impostor syndrome ay isang ilusyon, hindi katotohanan." – Unknown"""],
        "follow_up": []
    },

    "homesick_tl": {
        "signals": ["homesick", "nag-iisa sa college", "miss home", "miss family", "college away", "layo sa bahay"],
        "response": ["""Ang pakiramdam na nag-iisa ay natural, lalo na kung malayo ka sa tahanan. Makipag-ugnayan sa pamilya regularly—video call, chat, kahit mensahe lang.
Pakinabangan mo rin ang oras na kasama mo sila ngayon. Kapag pinagsama ang pamilya at bagong mga kaibigan, may bagong tahanan ka na. Kaya mo!
"Mapapangalagaan mo ang tatlong tahanan: kung saan ka mula, kung nasaan ka ngayon, at kung saan ka papunta." – Unknown"""],
        "follow_up": []
    },

    "struggling_grades_tl": {
        "signals": ["struggling grades", "bumababa grade", "hindi nakakuha", "class standing", "exam result", "maraming E", "mababang grado"],
        "response": ["""Nakakapagod kapag hindi nag-iimprove ang grade mo, pero hindi ito katapusan ng lahat. Makipag-usap sa teacher tungkol sa extra credit, tutoring, o kung ano ang dapat mong gawin.
Maraming estudyante ang tumaas mula sa mababang punto. Ang pagkakamali ay hindi pangmatagalan—ito ay pagkakataon na mag-improve.
"Ang bawat expert ay batang nagsimula." – Unknown"""],
        "follow_up": []
    },

    "financial_stress_tl": {
        "signals": ["walang pera", "gastos", "mahirap ang bayad", "financial", "utang", "bills", "presyo", "bili hindi kaya"],
        "response": ["""Ang financial stress ay tunay, ngunit hindi ito forever. Hanapin ang resources sa school: scholarships, grants, student loans, o work-study programs.
Mag-budget, humingi ng tulong sa pamilya kung kaya nila, at tanggapin ang tulong na inaalok. Ang pagiging matalino sa pera ay nagsisimula sa pag-plano ngayon.
"Ang pera ay tool, hindi iyong identity. Gamitin ito ng matalino." – Unknown"""],
        "follow_up": []
    },

    "burnout_tl": {
        "signals": ["burnout", "pagod na sobra", "exhausted", "walang energy", "laging busy", "burnout talaga", "tired na tired", "no more fuel"],
        "response": ["""Ang burnout ay sign na kailangan mo ng rest. Hindi ito pagweak—ito ay sign na tao ka. Magsimula ng napakaliit na pahinga: 10 minuto lang para sa iyong sarili.
Sabihin ang 'no' sa ilang bagay. Bigyan ng priyoridad ang iyong kalusugan. Walang tagumpay na sulit na sirain ang iyong buhay.
"Ang pahinga ay hindi katamaran. Ito ay investment para sa iyong kinabukasan." – Unknown"""],
        "follow_up": []
    },

    

    "stress_management_tl": {
        "signals": ["stress", "stressed", "relax", "chill", "way mag destress", "meditation", "calm", "how to manage stress", "reduce stress", "paano i-manage stress", "pano mag-relax", "tips destress", "stress relief"],
        "response": ["""Naiintindihan kong mabigat at pagod na pagod ka na. Normal lang makaramdam ng stress, lalo na ngayong estudyante ka. Kaya natin itong pagaanin nang paunti-unti. 🤍

Subukan mo ito:

🧠 **Isip:** Kapag naiisip mong "hindi ko kaya," palitan mo ng "isang hakbang lang muna."
🌬️ **Hininga:** Huminga nang malalim. Pasok sa ilong (4 segundo), pigil (4 segundo), labas sa bibig (6 segundo). Ulitin ng 3 beses.
📚 **Aral:** Mag-aral nang paunti-unti (25 minuto aral, 5 minuto pahinga). Mas epektibo ito kaysa isang bagsakan.
😴 **Tulog:** Unahin ang 7-8 oras na tulog. Mas magiging malinaw ang isip mo.

Kung ilang linggo ka nang nahihirapan at apektado na ang pag-aaral mo, makipag-usap sa guidance counselor o sa doktor."""],
        "follow_up": []
    },

    "motivation_tl": {
        "signals": ["motivation", "motivate", "encourage", "push myself", "walang gana", "drive", "energy", "how to stay motivated", "increase motivation", "paano motivated", "pano mag-motivation", "tips motivation", "ways to motivate","motivational"],
        "response": ["""Naiintindihan kong wala kang gana ngayon. Normal lang yan—hindi ito katamaran. Minsan kailangan lang ng katawan at isip mo ng maliit na simula. 💙

Subukan mo ito:

1. **Hatiin ang gawain:** Gawin itong napakaliit. Isang talata, 5 minutong lakad, o isang tanong lang muna.
2. **Magsimula ngayon:** Huwag nang hintayin ang "tamang gana." Kapag nagsimula ka na, kadalasan sumusunod na ang gana.
3. **I-celebrate ang maliit:** Bawat maliit na natapos mo, ipagdiwang mo. Sumisigla ang loob kapag may natatapos.
4. **Gawin itong ugali:** Ulitin araw-araw nang paunti-unti. Sa paglipas ng panahon, mas nagiging madali ito.

Kung matagal ka nang walang ganang gawin ang mga dating gusto mo, makipag-usap sa guidance counselor o sa doktor."""],
        "follow_up": []
    },

   

    "fear_of_failure": {
        "signals": ["fear of failure", "afraid to fail", "scared of failing", "what if I fail", "don't want to disappoint"],
        "response": ["""Fear of failure can be paralyzing, but it's a sign that you care deeply. Remember, failure is not the opposite of success; it's a part of it.
Every attempt is a learning opportunity. Your worth is not tied to your outcomes. Be brave enough to be imperfect.
"Failure is success in progress." – Albert Einstein"""],
        "follow_up": []
    },

    "fear_of_failure_tl": {
        "signals": ["takot mabigo", "ayokong magkamali", "paano kung magkamali ako", "nakakatakot sumubok", "takot sa failure"],
        "response": ["""Ang takot na mabigo ay normal, lalo na kung mahalaga sa'yo ang isang bagay. Tandaan mo na ang pagkakamali ay hindi katapusan, kundi bahagi ng proseso para matuto.
Ang mahalaga ay ang tapang mong sumubok. Ang iyong halaga ay hindi nababawasan ng pagkakamali.
"Ang kabiguan ay isang pagkakataon upang magsimulang muli nang mas matalino." – Henry Ford"""],
        "follow_up": []
    },

    # ==================== NEW ACADEMIC STRUGGLES ====================
    "thesis_topic_struggle": {
        "signals": ["thesis topic", "research topic", "hirap sa topic", "walang maisip na topic", "paano pumili ng thesis topic", "research title"],
        "response": ["""Ang pagpili ng thesis topic ay isang malaking hakbang, at normal lang na makaramdam ng pressure. Subukan mong pag-isipan: Ano ang mga paksang interesado ka talaga?
Magsimula sa malawak na ideya at dahan-dahang gawin itong mas malinaw at detalyado. Makipag-usap sa iyong adviser; nandiyan sila para gabayan ka.
"The secret of getting ahead is getting started." – Mark Twain"""],
        "follow_up": []
    },

    "recitation_anxiety": {
        "signals": ["recitation", "takot sa recitation", "kinakabahan sa recitation", "anxiety in recitation", "fear of being called in class", "takot tawagin ng teacher"],
        "response": ["""Ang kaba sa recitation ay napaka-karaniwan. Hindi ka nag-iisa. Ang isang paraan para mabawasan ito ay ang paghahanda.
Subukang aralin ang posibleng itanong at isipin ang iyong sagot. Tandaan, hindi inaasahan na perpekto ka. Ang mahalaga ay sumusubok ka.
"Courage is resistance to fear, mastery of fear – not absence of fear." – Mark Twain"""],
        "follow_up": []
    },

    "feeling_behind": {
        "signals": ["feeling behind", "nahuhuli sa klase", "i'm behind", "left behind", "di ko na ma-catch up", "nalilito na ako sa lessons"],
        "response": ["""Normal lang na maramdaman na nahuhuli ka, lalo na kung mabilis ang takbo ng lessons. Huwag mag-panic.
Subukang kausapin ang iyong propesor o isang kaklase na nakakaintindi ng topic. Ang paghingi ng tulong ay tanda ng lakas.
"It does not matter how slowly you go as long as you do not stop." – Confucius"""],
        "follow_up": []
    },

    "org_work_overload": {
        "signals": ["org work", "sobrang daming org work", "org work and acads", "nahihirapan sa org", "pagod sa org", "balancing organization"],
        "response": ["""Ang pagiging aktibo sa student organizations ay maganda, pero madali itong maging overwhelming. Mahalagang matutunan kung ano ang uunahin.
Alin sa mga gawain ang pinaka-importante? Okay lang din na matutong tumanggi sa ibang responsibilidad para protektahan ang iyong oras at kapayapaan ng isip.
"You can do anything, but not everything." – David Allen"""],
        "follow_up": []
    },
    
    "groupmate_problem": {
        "signals": ["groupmate problem", "lazy groupmate", "di nagpaparamdam groupmate", "ako lahat gumagawa", "free rider", "pabuhat sa group", "problema ha kagrupo", "hubya nga kagrupo", "ako la an nabuhat"],
        "response": ["""Nakaka-frustrate talaga kapag may mga groupmate na hindi tumutulong. Normal lang na mainis ka.
Subukang mag-set ng malinaw na roles at deadlines sa inyong grupo. Kung hindi pa rin umubra, kausapin nang mahinahon ang miyembro o i-raise ito sa inyong propesor.
"You cannot control the actions of others, but you can control your response." – Unknown"""],
        "follow_up": []
    },

    "reading_overload": {
        "signals": ["too much reading", "daming babasahin", "reading overload", "can't finish readings", "tambak na readings", "damo an basahonon", "di na matapos pagbasa"],
        "response": ["""Nakaka-overwhelm talaga kapag sunod-sunod ang readings. Hindi mo kailangang basahin ang bawat salita.
Subukan ang 'skimming'—basahin ang introduction, headings, at conclusion para makuha ang main idea. Ang mahalaga ay ang konsepto, hindi ang bawat detalye.
"The goal is to understand, not just to finish." – Unknown"""],
        "follow_up": []
    },

    "career_anxiety": {
        "signals": ["anxious about future", "what after college", "career path", "anong trabaho", "takot pagka-graduate", "ano an trabaho pag-gradwar", "hadlok pagkatapos eskwela", "unsure about my career"],
        "response": ["""Normal na makaramdam ng kaba tungkol sa kung anong mangyayari pagkatapos ng kolehiyo. Hindi ka nag-iisa diyan.
Gamitin mo ang oras na ito para i-explore ang iyong mga interes. Makipag-usap sa career services ng inyong school; marami silang resources para sa'yo.
"Your career is a journey, not a destination. It's okay to not have it all figured out." – Unknown"""],
        "follow_up": []
    },

    
}


# ----------------------------
# WARAY RESPONSES (DATASET)
# ----------------------------
WARAY_RESPONSES = {
    "greetings": [
        "Maupay nga adlaw! 🤍 Kumusta ka yana?",
        "Maupay! 😊 Ano an imo gibabati?",
        "Kumusta! Hinaot nga okay ka la yana.",
        "Maupay! Aadi la ako para mamati ha imo.",
        "Kumusta ka? Hinumdumi nga importante ka. Ano an maitutulong ko ha imo yana?",
        "Maupay nga adlaw! San-o kita magtikang, usa nga pahinumdom para han imo seguridad: likayi an paghatag hin personal nga impormasyon sugad han bug-os nga ngaran, address, o contact details dinhi. Handa na ako mamati. 🤍"
    ],
    "gratitude": [
        "Waray sapayan 🤍 Nalilipay ako nga nakabulig ha imo.",
        "Salamat liwat han imo pagtapod. Aadi la ako pirmi.",
        "Dako nga kalipay ko nga makabulig ha imo. Padayon la!",
        "Salamat han pag-istorya ha akon. Maupay nga gin-aataman mo an imo sarili."
    ],
    "stress": [
        "Baga hin mabug-at an imo gin-aagian yana.\nKung stress ka:\n• Pahuway ngan ginhawa hin halawig\n• Diri mo kailangan tapuson an ngatanan dayon\n• Hinay-hinay la anay"
    ],
    # "anxiety_general": [
    #     "Baga hin gin-kakulba ka o nababaraka.\nKung may anxiety:\n• Waray ka ha peligro yana\n• Malalampasan mo ini\n• Ginhawa la hin halawig"
    # ],
    # "depression": [
    #     "Salamat han pagin bukas han imo gibabati.\nKung mabug-at an buot:\n• Diri ka maluya\n• May halaga ka bisan pa sugad an imo pag-abat\n• Diri mo kailangan mag-usahan"
    # ],
    # "overthinking": [
    #     "Nakaka-uyas gud man an overthinking.\nSuwaya ini:\n• Isurat an imo mga naiisip\n• I-lugar an kaya mo kontrolon ngan an diri\n• Balik ha presente nga oras"
    # ],
    "grounding_request": [
        "Cge, uupdan ko ikaw 🤍\n\n🌬️ **4–4–6 Breathing Exercise**\n"
        "1️⃣ Ginhawa hin hinay-hinay ha irong (bilang hin 4)\n"
        "2️⃣ Pugngi an ginhawa (bilang hin 4)\n"
        "3️⃣ Ipagawas an ginhawa ha baba (bilang hin 6)\n\n"
        "Utrohon ta ini hin 3 ka beses. Sabay la kita."
    ],
    # Add more translations here as needed to cover other intents
    "school_assignment": [
        "Baga hin napi-pressure ka ha imo mga assignment.\nSuwayan ta ini:\n• Bunga-a ha gudtiay nga mga buruhaton\n• Unaha an pinakamasanay\n• Importante an pag-uswag, diri an pagka-perpekto"
    ],
    # "family_problem": [
    #     "Mas masakit gud kun an pamilya an gintitikangan han stress.\nValid an imo gibabati.\nDiri mo kinahanglan akuon an ngatanan."
    # ],
    "school_project": [
        "Nakaka-stress gud an mga project o thesis, labi na kun grupo.\nHinumdumi:\n• Diri ngatanan kontrolado mo\n• Buhata la an imo kaya\n• Pakig-istorya ha imo mga kagrupo kun pwede"
    ],
    "financial_problem": [
        "Mabug-at gud an problema ha kwarta.\nHinumdumi:\n• Diri ini an basihan han imo halaga\n• Damo nga estudyante an naagi hini\n• Diri ka nag-uusahan"
    ],
    # "relationship_problem": [
    #     "Masakit gud an problema ha relasyon.\nHinumdumi:\n• Diri ka nagkulang komo usa ka tawo\n• Natural la an masakitan\n• May-ada panahon para ma-upay"
    # ],
    # "future_uncertainty": [
    #     "Damo nga mga estudyante ha kolehiyo an sugad hini an gibabati.\nDiri mo kinahanglan mahibaroan an ngatanan yana.\nTagsa-tagsa la anay."
    # ],
    # New Academic Waray Responses
    "stress_exams": [
        "Normal la nga kulbaan ha exam o test. An importante, nag-prepare ka. Pag-study hin maupay pero ayaw kalimti an pagkaturog. An imo score diri nagdedefine kun hin-o ka. Kaya mo ito!"
    ],
    "failing_subject": [
        "Masakit gud man an hagubo nga grado o bagsak, pero diri ito an katapusan. Pwede ka pa bumawi. Pakig-istorya ha imo teacher kun paonan-o ka makakabawi. Diri ka nag-uusahan hini nga challenge."
    ],
    "burnout": [
        "Kun waray ka na gana o kapoy ka na, pamati ha imo lawas. Bangin kinahanglan mo la hin pahuway. Diri karera an pag-eskwela. Importante an imo kalinaw han isip. Pahuway anay, tapos laban utro."
    ],
    "major_uncertainty": [
        "Okay la nga diri ka sigurado ha imo kurso. Damo nga estudyante an nakaka-agi hini. Pag-explore la ngan paki-istorya ha imo guidance counselor o mga sangkay."
    ]
    ,
    "groupmate_problem": [
        "Nakaka-frustrate gud man kun may-ada ka kagrupo nga diri nabulig. Normal la nga mapuno ka. Suwayi pagbutang hin klaro nga buruhaton ngan deadline. Kun diri la gihapon, istoryaha hin kalmado an imo kagrupo o isumat ha iyo propesor."
    ],
    "reading_overload": [
        "Maka-overwhelm gud man kun damo an basahonon. Diri mo kinahanglan basahon an kada pulong. Suwayi an 'skimming'—basa-basa la anay ha introduction, headings, ngan conclusion para makuha an dako nga ideya. An importante an konsepto."
    ],
    "career_anxiety": [
        "Normal la nga kulbaan kun ano an sunod pagkatapos han kolehiyo. Damo kita nga sugad an gibabati. Gamita ini nga oras para pag-isipan an imo mga gusto. Pakig-istorya ha career services han iyo eskwelahan, damo hira maibubulig ha imo."
    ],
    "thesis_topic_struggle": [
        "Dako gud nga butang an pagpili hin thesis topic, ngan normal la nga ma-pressure. Hunahunaa: Ano an mga topic nga interesado ka gud? Paki-istorya ha imo adviser, aada hira para giyahan ka."
    ],
    "recitation_anxiety": [
        "An kulba ha recitation kay komon gud. Diri ka nag-uusahan. Usa nga paagi para mabawasan ini an pag-andam. Pag-andam hin posible nga mga pakiana ngan hunahunaa an imo baton. Diri kinahanglan perpekto, an importante, naningkamot ka."
    ]
}

WARAY_FALLBACKS = [
    "Namamati ako. Aadi la ako para mamati ha imo. 💙",
    "Nasasabtan ko. Alayon pagsumat pa han imo gibabati.",
    "Importante an imo gibabati. Handa ako mamati.",
    "Salamat han pag-share. Aadi ako para suportahan ka.",
    "Diri ka nag-uusahan. Aadi ako para mamati."
]

DEFAULT_FAQ_ANSWERS = {
    "what is this app for": "This app is an academic struggle support chatbot for students, designed to provide study guidance, motivation, and practical help for school stress.",
    "how can i use this chatbot": "You can type your academic concerns here and the chatbot will respond with support, study tips, and practical guidance when needed.",
    "who can use this app": "This app is intended for students who want help with academic challenges like exams, assignments, time management, and school stress."
}


def _load_faq_answers():
    faq_answers = {}

    try:
        conn = sqlite3.connect(_get_db_path())
        c = conn.cursor()
        c.execute("SELECT question, answer FROM faq_dataset")
        for question, answer in c.fetchall():
            if question and answer:
                faq_answers[question.strip().lower()] = answer.strip()
        conn.close()
    except sqlite3.Error:
        faq_answers = {}

    if faq_answers:
        return faq_answers

    project_root = Path(__file__).resolve().parent.parent
    csv_candidates = [
        project_root / "data" / "faq_dataset.csv",
        project_root / "templates" / "faq_dataset.csv",
    ]
    for csv_path in csv_candidates:
        if not csv_path.exists() or csv_path.stat().st_size == 0:
            continue
        try:
            with csv_path.open("r", encoding="utf-8-sig") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    question = (row.get("question") or "").strip().lower()
                    answer = (row.get("answer") or "").strip()
                    if question and answer:
                        faq_answers[question] = answer
        except (OSError, csv.Error):
            continue

    if faq_answers:
        return faq_answers

    return DEFAULT_FAQ_ANSWERS


def get_faq_answer(text, language='tagalog'):
    normalized = text.lower().strip()
    if not normalized:
        return None

    # Sundin ang wika ng tanong: Tagalog muna para sa Tagalog na tanong.
    if language == 'tagalog':
        default_sets = (DEFAULT_FAQ_ANSWERS_TL, DEFAULT_FAQ_ANSWERS)
    else:
        default_sets = (DEFAULT_FAQ_ANSWERS,)

    for defaults in default_sets:
        for question, answer in defaults.items():
            q = question.lower().strip()
            if _has_signal(normalized, q):
                return answer

    faq_answers = _load_faq_answers()
    if not faq_answers:
        return None

    for question, answer in faq_answers.items():
        q = question.lower().strip()
        if _has_signal(normalized, q):
            return answer

    return None


def _get_openai_api_key():
    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("MENTALHEALTHWEB_OPENAI_API_KEY")
    return key if key else None

def _get_gemini_api_key():
    """Fetches the Gemini API key from environment variables."""
    # Return the key only if it's not an empty string
    key = os.environ.get("GEMINI_API_KEY")
    return key if key else None

def _gemini_available():
    """Checks if the Gemini library is installed and an API key is available."""
    return _import_genai() is not None and _get_gemini_api_key() is not None


def _openai_available():
    return _import_openai() is not None and _get_openai_api_key() is not None


def _get_groq_api_key():
    """Fetches the Groq API key from environment variables."""
    key = os.environ.get("GROQ_API_KEY")
    return key if key else None


def _groq_available():
    """Checks if the Groq library is installed and an API key is available."""
    return _import_groq() is not None and _get_groq_api_key() is not None


# ----------------------------
# AI PROVIDER LIMIT HANDLING
# ----------------------------
# Kung naubos ang limit ng provider (429 rate limit o quota/tokens), itinatala
# natin ang dahilan dito at ipinapakita lang ito sa user PAGKAPUNO ng lahat ng
# provider sa chain (Groq -> OpenAI -> Gemini). Dati, bumabalik agad ang
# "masyadong mabilis" na sagot kahit may pang-fallback na provider, kaya napupunta
# ang tanong sa error message imbes na sa aktwal na sagot.
_ai_error_kind = None

# Gaano karamihing beses uulitin ang tawag kapag TRANSIENT na rate limit lang
# (hal. requests/minute sa Groq free tier). Ito ay sandali lang — kaya imbes na
# sabihing "masyadong mabilis" ang user, maghintay at ulitin na lang natin.
_RATE_LIMIT_RETRY_DELAYS = (2.0, 4.0)


def _classify_ai_error(error, status_code=None):
    """Ibalik ang "rate_limit", "quota", o None mula sa error ng AI provider.

    * "rate_limit" = masyadong mabilis ang mga hinihiling (429) — bumabalik ito
      sa loob ng ilang segundo kaya nang i-retry.
    * "quota" = naubos ang limit/tokens ng API key (hal. "tokens per day",
      "insufficient_quota") — hindi ito aayos sa ilang segundo lang.

    Dati ay sapat na ang `'rate' in str(e)` kaya nagfi-false-positive ito sa
    kahit anong error na naglalaman ng "rate" (hal. "failed to generate").
    """
    text = str(error).lower()
    if status_code is None:
        status_code = getattr(error, "status_code", None)
    error_code = str(getattr(error, "code", "") or "").lower()

    if "insufficient_quota" in text or "insufficient_quota" in error_code:
        return "quota"

    quota_markers = (
        "tokens per day", "requests per day", "per day limit", "daily limit",
        "usage limit", "quota exceeded", "exceeded your current quota",
        "tokens_per_day", "requests_per_day",
    )
    if any(marker in text or marker in error_code for marker in quota_markers):
        return "quota"

    rate_markers = (
        "rate limit", "rate_limit", "too many requests",
        "requests per minute", "tokens per minute",
        "resource exhausted", "resource_exhausted", "429",
    )
    if (
        status_code == 429
        or type(error).__name__ == "RateLimitError"
        or any(marker in text or marker in error_code for marker in rate_markers)
    ):
        return "rate_limit"

    return None


def _note_ai_error(kind):
    """Itala ang uri ng error para magamit ng _call_ai_reply sa dulo ng chain."""
    global _ai_error_kind
    if not kind:
        return
    # Mas seryoso ang quota — siya ang laging ipapakita kung pareho ang nangyari.
    if _ai_error_kind is None or kind == "quota":
        _ai_error_kind = kind


def _clear_ai_error():
    """Burahin ang naunang limit error kapag may provider na nakasagot na."""
    global _ai_error_kind
    _ai_error_kind = None


def _ai_error_reply(language, kind):
    """Mensahe para sa user kapag sumuko na ang lahat ng AI provider."""
    if kind == "quota":
        return _language_pick(
            language,
            "The AI service has reached its limit for now. Please try again later or tomorrow, and please inform the administrator.",
            "Naabutan ng limit ang AI service ngayon. Subukan muli mamaya o bukas, at paki-abiso sa administrator.",
            "Naabutan han limit an AI service yana. Pag-try utro pagkamao o dumaha, ngan alayon pagsumat ha administrator.",
        )
    return _language_pick(
        language,
        "Too many questions at once. Let's pause for a moment and try again in a few seconds.",
        "Masyadong mabilis ang mga tanong. Magpahinga muna tayo sandali at subukan ulit pagkatapos ng ilang segundo.",
        "An AI service in nagpapahuway makadiyot. Alayon paghulat hin pipira ka segundo ngan pag-try utro.",
    )


def _create_chat_completion(client, model, messages, max_tokens=600, temperature=0.4):
    """.chat.completions.create na may retry kapag transient na rate limit lang.

    Parehong gamit ito ng Groq at OpenAI (pareho ang openai-compatible na API).
    Kapag quota ang problema, walang retry — diretso itatapon para makapag-
    fallback sa susunod na provider.
    """
    delays = _RATE_LIMIT_RETRY_DELAYS
    attempts = len(delays) + 1
    for attempt in range(attempts):
        try:
            return client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as e:
            kind = _classify_ai_error(e)
            if kind != "rate_limit" or attempt >= len(delays):
                raise
            wait = delays[attempt]
            logging.warning(
                "Rate limited by the AI provider (attempt %d/%d) — waiting %.1fs then retrying.",
                attempt + 1, attempts, wait,
            )
            time.sleep(wait)


def _groq_models():
    """Modelong sinusubukan ng Groq, primary muna.

    Bawat Groq model ay may SARILING free-tier allowance (hal. 200K tokens at
    1K requests kada araw para sa `qwen/qwen3.8-27b`). Kapag naubos ang quota
    ng primary model, sinusubukan ang iba bago ibalik ang error sa user.
    Idagdag ang sariling listahan sa GROQ_MODEL_FALLBACKS (comma-separated).
    """
    primary = os.environ.get("GROQ_MODEL", "qwen/qwen3.8-27b")
    configured = [
        model.strip()
        for model in os.environ.get("GROQ_MODEL_FALLBACKS", "").split(",")
        if model.strip()
    ]
    extras = configured or ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
    models = [primary]
    for model in extras:
        if model not in models:
            models.append(model)
    return models


def _call_groq_api(user_input, language='tagalog', history=None):
    """Calls the Groq API (Llama 3.1) as the primary AI fallback."""
    if not _groq_available():
        logging.warning("Groq API not available (library not installed or key not set).")
        return None

    try:
        api_key = _get_groq_api_key()
        if not api_key:
            logging.error("Groq API key not found. Please set GROQ_API_KEY in the .env file.")
            return None

        key_preview = f"{api_key[:5]}...{api_key[-4:]}" if len(api_key) > 9 else "Invalid Key"
        logging.info(f"Attempting to use Groq API key: {key_preview}")

        client = _import_groq().Groq(api_key=api_key)

        system_prompt = _build_openai_system_prompt(language)
        messages = [
            {"role": "system", "content": system_prompt},
        ]
        for line in _history_to_prompt_lines(history):
            if line.startswith("Earlier user:"):
                messages.append({"role": "user", "content": line[len("Earlier user:"):].strip()})
            else:
                messages.append({"role": "assistant", "content": line[len("Earlier assistant:"):].strip()})
        # Paalala sa dulo: ang WIKA ng huling mensahe ang masusunod — kahit
        # single word lang. Hindi ito optional; HIGHEST PRIORITY ito.
        messages.append({"role": "user", "content": (
            f"{_language_directive(language)}\n{user_input}"
        )})

        for model in _groq_models():
            try:
                completion = _create_chat_completion(client, model, messages)
            except Exception as model_error:
                kind = _classify_ai_error(model_error)
                if not kind:
                    raise  # hindi limit error — ipapasa sa pangunahing handler
                # Quota/rate limit lang ng model na ito — baka may allowance pa
                # ang susunod na model, kaya doon tayo sa susubukan ng next.
                _note_ai_error(kind)
                logging.warning(
                    "Groq model %s is limited (%s); trying the next Groq model.",
                    model, kind,
                )
                continue

            if completion.choices and completion.choices[0].message:
                choice = completion.choices[0]
                partial = (choice.message.content or "").strip()
                if partial and "length" in str(getattr(choice, "finish_reason", "")).lower():
                    logging.info("Groq reply was cut off (finish_reason=length); requesting a continuation.")
                    extra = _request_chat_continuation(client, model, messages, partial)
                    if extra:
                        partial = partial + extra
                if partial:
                    # Tagumpay ang model na ito — burahin ang naunang limit error.
                    _clear_ai_error()
                    return _clean_ai_text(partial)

            logging.warning("Groq response from %s was empty or malformed.", model)

        return None

    except Exception as e:
        logging.exception(f"Groq API call failed: {e}")
        kind = _classify_ai_error(e)
        if kind:
            # Huwag nang ibalik agad ang error sa user — hayaang subukan muna
            # ang susunod na provider sa chain (o ang dataset fallback).
            _note_ai_error(kind)
            logging.warning("Groq is limited (%s); moving to the next AI provider.", kind)
        return None


def _call_gemini_api(user_input, language='tagalog', history=None):
    """Calls the Google Gemini API as a fallback."""
    if not _gemini_available():
        logging.warning("Gemini API not available (library not installed or key not set).")
        return _language_pick(
            language,
            "There is a problem with the AI service (library not installed). Please inform the administrator.",
            "Nagkaproblema sa AI service (hindi naka-install ang library). Paki-abiso sa administrator.",
            "Mayda problema ha AI service (diri naka-install an library). Alayon pagsumat ha administrator.",
        )

    try:
        api_key = _get_gemini_api_key()
        if not api_key:
            logging.error("Gemini API key not found. Please set GEMINI_API_KEY in the .env file.")
            return _language_pick(
                language,
                "There is a problem with the AI service (no API key). Please inform the administrator.",
                "Nagkaproblema sa AI service (walang API key). Paki-abiso sa administrator.",
                "Mayda problema ha AI service (waray API key). Alayon pagsumat ha administrator.",
            )

        key_preview = f"{api_key[:5]}...{api_key[-4:]}" if len(api_key) > 9 else "Invalid Key"
        logging.info(f"Attempting to use Gemini API key: {key_preview}")

        genai_module = _import_genai()
        genai_module.configure(api_key=api_key)

        preferred_models = [
            os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"),
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
        ]
        seen_models = set()
        for model_name in preferred_models:
            if not model_name or model_name in seen_models:
                continue
            seen_models.add(model_name)
            try:
                model = genai_module.GenerativeModel(model_name)
                system_prompt = _build_openai_system_prompt(language)
                history_block = "\n".join(_history_to_prompt_lines(history))
                lang_tag = f"{_language_directive(language)}\n{user_input}"
                if history_block:
                    full_prompt = f"{system_prompt}\n\n{history_block}\nUser: {lang_tag}\nAssistant:"
                else:
                    full_prompt = f"{system_prompt}\n\nUser: {lang_tag}\nAssistant:"
                response = model.generate_content(contents=full_prompt)
                if getattr(response, "parts", None):
                    text = response.text.strip()
                    if _gemini_reply_was_cut(response):
                        logging.info("Gemini reply was cut off (MAX_TOKENS); requesting a continuation.")
                        extra = _request_gemini_continuation(model, full_prompt, text)
                        if extra:
                            text = text + extra
                    return _clean_ai_text(text)
                logging.error("Gemini API call was blocked by safety settings or returned no content.")
                return _language_pick(
                    language,
                    "Sorry, I can't answer that question. The topic may be too sensitive.",
                    "Paumanhin, hindi ko masasagot ang tanong na iyan. Ang paksa ay maaaring masyadong sensitibo.",
                    "Pasensya, diri ko mababaton iton nga pakiana. Bangin an topic kay sensitibo.",
                )
            except Exception as model_error:
                logging.warning("Gemini model %s failed: %s", model_name, model_error)
                if "invalidargument" in str(model_error).lower() and model_name != preferred_models[-1]:
                    continue
                raise model_error

        raise RuntimeError("No Gemini model could satisfy the request.")

    except Exception as e:
        logging.exception(f"Google Gemini API call failed: {e}")
        kind = _classify_ai_error(e)
        if kind:
            # Rate limit/quota lang — tapos na ang chain, ipapakita na lang ito
            # ng _call_ai_reply kung kinakailangan.
            _note_ai_error(kind)
            logging.warning("Gemini is limited (%s); ending the AI chain.", kind)
            return None
        error_type = type(e).__name__
        logging.error(f"Gemini API call failed with a {error_type}. This will be shown to the user.")

        if "block" in str(e).lower():
            return _language_pick(
                language,
                "Sorry, I can't answer that question because of safety settings.",
                "Paumanhin, hindi ko masasagot ang tanong na iyan dahil sa safety settings.",
                "Pasensya, diri ko mababaton iton nga pakiana tungod han safety settings.",
            )

        if error_type in ['PermissionDenied', 'Unauthenticated'] or 'API_KEY_INVALID' in str(e).upper():
            error_message = _language_pick(
                language,
                "There is a problem with the AI service. Please inform the administrator. (API Key Error)",
                "Nagkaproblema sa AI service. Paki-abiso sa administrator. (API Key Error)",
                "Mayda problema ha AI service. Alayon pagsumat ha administrator. (API Key Error)",
            )
        elif 'deadline' in str(e).lower():
            error_message = _language_pick(
                language,
                "The AI took too long to answer. Please try again.",
                "Masyadong matagal bago sumagot ang AI. Subukang muli.",
                "Malawig an AI bago sumagot. Alayon pag-try utro.",
            )
        elif 'invalidargument' in str(e).lower() or error_type == 'InvalidArgument':
            error_message = _language_pick(
                language,
                "There is a problem with the AI service. Please inform the administrator. (Invalid Argument)",
                "Nagkaproblema sa AI service. Paki-abiso sa administrator. (Invalid Argument)",
                "Mayda problema ha AI service. Alayon pagsumat ha administrator. (Invalid Argument)",
            )
        else:
            error_message = _language_pick(
                language,
                f"There is a problem with the AI service. Please inform the administrator. (Error: {error_type})",
                f"Nagkaproblema sa AI service. Paki-abiso sa administrator. (Error: {error_type})",
                f"Mayda problema ha AI service. Alayon pagsumat ha administrator. (Error: {error_type})",
            )
        return error_message




def _dedupe_lines(text):
    """Tanggalin ang inuulit na linya (hal. nadobleng numbered list).

    Madalas umulit ang AI ng parehong items — kinukuha lang ang unang
    paglitaw ng bawat linya para malinis ang listahan.
    """
    if not text:
        return text
    seen = set()
    out_lines = []
    for line in text.split("\n"):
        # Tanggalin ang numbering/bullet markers bago ikumpara ang linya
        # (hal. "1. Kaya mo!" at "- Kaya mo!" ay pareho lang ng linya).
        key = re.sub(r"^(\s*\d{1,2}[.)]\s+|\s*[-*]\s+)", "", line.strip().lower())
        key = re.sub(r"\s+", " ", key).strip()
        if not key:
            out_lines.append(line)
            continue
        if key in seen:
            continue
        seen.add(key)
        out_lines.append(line)
    return "\n".join(out_lines)


def _dedupe_sentences(text):
    """Tanggalin ang inuulit na sentence sa loob ng iisang linya.

    Minsan inuulit ng AI ang parehong pangungusap sa iisang linya (hal.
    "Ang pula ay kulay ng puso. Ang pula ay kulay ng puso."). Pang-isang-linya
    lang ang paglilinis para hindi masira ang mga listahan na nakaayos sa
    hihiwalay na linya.
    """
    if not text:
        return text
    out_lines = []
    for line in text.split("\n"):
        parts = re.split(r"(?<=[.!?])\s+", line.strip())
        if len(parts) < 2:
            out_lines.append(line)
            continue
        seen = set()
        kept = []
        for part in parts:
            key = re.sub(r"[^\w\s]+", " ", part.lower())
            key = re.sub(r"\s+", " ", key).strip()
            # 4+ salita muna bago ituring na ulit, para hindi mabura ang
            # maiikling pariralang normal na nauulit (hal. "Kaya mo! Kaya mo!").
            if len(key.split()) >= 4 and key in seen:
                continue
            if key:
                seen.add(key)
            kept.append(part)
        out_lines.append(" ".join(kept))
    return "\n".join(out_lines)


def _balance_bold_markers(text):
    """Tanggalin ang hindi balanse na ** para hindi maghititaw ng hilaw na
    asterisks sa frontend (hal. "Ang **burnout ay normal" ay walang kapareho)."""
    if not text:
        return text
    if text.count("**") % 2:
        idx = text.rfind("**")
        text = text[:idx] + text[idx + 2:]
    return text
# Mga salitang hindi maaaring magtapos ng kumpletong pangungusap. Kapag ito
# ang huling salita ng sagot, malamang na naputol (cut-off) ang dulo —
# tinatanggal lang natin ang nakabitin na salita, hindi ang buong linya.
_DANGLING_TAIL_WORDS = {
    # English
    "the", "a", "an", "to", "of", "in", "on", "at", "by", "for", "with",
    "from", "into", "about", "over", "under", "between", "during",
    "before", "after", "and", "or", "but", "if", "then", "because",
    "than", "unless", "while", "until", "is", "are", "was", "were", "be",
    "been", "am", "can", "could", "will", "would", "shall", "should",
    "may", "might", "must", "do", "does", "did", "have", "has", "had",
    # Tagalog / Waray
    "na", "ng", "sa", "ang", "mga", "at", "o", "ay", "ha", "han",
    "pero", "ngunit", "dahil", "kung", "kapag", "habang", "para",
    "upang", "tungkol", "hanggang", "gaya", "tulad", "kailangan",
    # Mga affix/prefix na laging may kasunod na salita
    "mag", "nag", "pag", "hindi", "makaka", "makakapag",
}

_TERMINAL_END_CHARS = ".!?:;)\"'”’*"


def _is_dangling_tail_word(token):
    """True kapag hindi maaaring dulo ng kumpletong pangungusap ang salita."""
    word = re.sub(r"[^\w'-]", "", token.lower())
    if not word:
        return False
    # Cut-off sa kalagitnaan ng salita (hal. "hakbang-")
    if token.rstrip().endswith("-"):
        return True
    if word in _DANGLING_TAIL_WORDS:
        return True
    # Bitin na salita na kalahati lang ng kilalang salita (hal. "hind" -> "hindi")
    if len(word) >= 3 and any(w.startswith(word) for w in _DANGLING_TAIL_WORDS):
        return True
    return False


def _trim_dangling_tail(line):
    """Ibabalik ang linya na may kumpletong dulo, o '' kapag ubos na ang laman.

    Hal: "2. Hatiin ang gawain sa maliliit na hakbang na hind" ->
    "2. Hatiin ang gawain sa maliliit na hakbang."
    """
    stripped = line.strip()
    marker_match = re.match(r"^(\d{1,2}[.)]|[-*])\s+", stripped)
    marker = marker_match.group(0) if marker_match else ""
    content = stripped[marker_match.end():] if marker_match else stripped
    words = content.split()
    while words and _is_dangling_tail_word(words[-1]):
        words.pop()
    if not words:
        return ""
    return marker + " ".join(words)



def _repair_tail_line(line):
    """Ayusin ang huling linya ng sagot.

    Nagbabalik ng kumpletong linya (may ending punctuation), o ``None`` kapag
    dapat na itong tanggalin (bitin na heading o walang laman natira).
    """
    stripped = line.strip()
    if not stripped:
        return None
    # Bitin na heading na walang kasunod na listahan (hal. "**Mga Hakbang**")
    if re.fullmatch(r"\*\*[^*]+\*\*", stripped):
        return None
    # May ending na (. ! ? ; : ) o katapusan ng bold phrase -> kumpleto na
    if stripped[-1] in _TERMINAL_END_CHARS:
        return stripped
    trimmed = _trim_dangling_tail(stripped)
    if not trimmed or re.fullmatch(r"\d{1,2}[.)]", trimmed):
        return None
    if trimmed[-1] not in _TERMINAL_END_CHARS:
        trimmed += "."
    return trimmed


def _repair_truncated_tail(text):
    """Buoin ang dulo ng sagot nang hindi binubura ang kumpletong nilalaman.

    Dati, tinatanggal ang buong huling talata kapag walang ending punctuation
    at nauulit pa ang listahan dahil sa maling regex. Ngayon linya-kada-linya
    lang ang inaayos: tinatanggal lang ang talagang bitin na dulo, dinadagdagan
    ng '.' kung kumpleto naman ang linya, at kailanman ay hindi inuulit ang
    nilalaman.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    while paragraphs:
        lines = [l for l in paragraphs[-1].split("\n") if l.strip()]
        repaired = False
        while lines:
            fixed_line = _repair_tail_line(lines[-1])
            if fixed_line is not None:
                lines[-1] = fixed_line
                paragraphs[-1] = "\n".join(lines)
                repaired = True
                break
            lines.pop()
        if repaired:
            break
        paragraphs.pop()
    return "\n\n".join(paragraphs).strip()


def _clean_ai_text(text):
    """I-normalize ang AI reply sa ChatGPT-style na malinis at professional.

    Panatilihin ang magandang structure (paragraphs, bold highlights,
    numbered/bulleted lists) pero tanggalin ang magugulong characters:
    emojis, HTML tags, code blocks, at stray symbols. Ang natitirang
    markdown (**bold**, lists) ay ligtas na nire-render ng frontend bilang
    maayos na HTML — kaya walang hilaw na special characters na makikita
    ang user, pero ChatGPT-style pa rin ang itsura ng sagot.
    """
    if not text:
        return text
    cleaned = text.strip()
    # Markdown code blocks -> kunin lang ang laman bilang plain text
    cleaned = re.sub(r"```(?:\w+)?\n?(.*?)```", r"\1", cleaned, flags=re.DOTALL)
    # Inline code `code` -> plain
    cleaned = cleaned.replace("`", "")
    # <br> (kahit may attributes tulad ng <br class="x"/>), <p>, <li> at iba pang
    # line-break tags -> newline muna para hindi magkadikit ang mga pangungusap
    cleaned = re.sub(r"(?i)<\s*br\b[^>]*>", "\n", cleaned)
    cleaned = re.sub(r"(?i)</?\s*(p|div|li|ul|ol|h[1-6])[^>]*>", "\n", cleaned)
    # Natitirang HTML tags tanggalin
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    # Escaped entities (&lt;br&gt;, &#60;br&#62;, &#x3c;br&#x3e;) i-decode
    cleaned = cleaned.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    cleaned = re.sub(r"(?i)&#0*60;", "<", cleaned)
    cleaned = re.sub(r"(?i)&#0*62;", ">", cleaned)
    cleaned = re.sub(r"(?i)&#x0*3c;", "<", cleaned)
    cleaned = re.sub(r"(?i)&#x0*3e;", ">", cleaned)
    cleaned = cleaned.replace("&nbsp;", " ").replace("&#160;", " ").replace("\xa0", " ")
    # Ulitin ang pag-convert ng natitirang <br> pagkatapos ng decode - walang
    # anumang <br> na dapat makita ng user sa sagot
    cleaned = re.sub(r"(?i)<\s*br\b[^>]*>", "\n", cleaned)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    # Emojis at pictographs tanggalin (hindi professional tingnan)
    cleaned = re.sub(
        "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200d]",
        "",
        cleaned,
    )
    # Divider lines (---, ***, ___) tanggalin
    cleaned = re.sub(r"(?m)^\s*([-*_])\1{2,}\s*$", "", cleaned)
    # Blockquotes "> ..." -> plain text
    cleaned = re.sub(r"(?m)^\s{0,3}>\s?", "", cleaned)
    # Headings "### Title" -> gawing bold line na lang (ChatGPT-style)
    cleaned = re.sub(r"(?m)^\s{0,3}#{1,6}\s*(.+?)\s*$", r"**\1**", cleaned)
    # Stray tildes tanggalin
    cleaned = cleaned.replace("~", "")
    # Ayusin ang sobrang asterisks (***bold*** -> **bold**)
    cleaned = re.sub(r"\*{3,}", "**", cleaned)
    # Tanggalin ang inuulit na linya (nadobleng numbered list galing sa AI)
    cleaned = _dedupe_lines(cleaned)
    # Tanggalin ang inuulit na sentence sa loob ng parehong linya
    cleaned = _dedupe_sentences(cleaned)
    # Ayusin ang numbering: gawing sunod-sunod (1. 2. 3.) ulit
    lines = cleaned.split("\n")
    counter = 0
    fixed = []
    for line in lines:
        # 1-2 digit lang para hindi mapagkamalang taon ang "2024."
        if re.match(r"^\s*\d{1,2}[.)]\s+", line):
            counter += 1
            fixed.append(re.sub(r"^\s*\d{1,2}[.)]\s+", f"{counter}. ", line))
        else:
            # I-reset ang bilang sa labas ng listahan (blangko o talata)
            counter = 0
            fixed.append(line)
    cleaned = "\n".join(fixed)
    # Stray special chars sa simula ng linya (@, $, %, |, \) linisin
    cleaned = re.sub(r"(?m)^\s*[@$%|\\]+\s*", "", cleaned)
    # Ayusin ang whitespace: max 1 blank line sa pagitan ng paragraphs
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    # Alisin ang space bago ang punctuation
    cleaned = re.sub(r"\s+([.,!?:;])", r"\1", cleaned)
    # Hilaw na ** na walang kapareho -> tanggalin (hindi ito magmumukhang
    # bitin na asterisks sa frontend)
    cleaned = _balance_bold_markers(cleaned)
    # Ayusin ang naputol na dulo (walang ending punctuation) nang hindi
    # binubura ang kumpletong nilalaman at hindi inuulit ang listahan.
    cleaned = _repair_truncated_tail(cleaned)
    return cleaned.strip()


def _language_directive(language):
    """Instruction na inilalagay bago ang huling mensahe ng user sa AI.

    Kapag 'auto' (hindi sigurado ang detector — hal. unfamiliar na salita
    gaya ng "milestone" o typo), ang AI na mismo ang magdedekta ng wika ng
    mensahe — parang ChatGPT. Hindi ito kailanman pinapapilitang sumagot
    sa ibang wika kaysa sa ginamit ng user.
    """
    if language == 'auto':
        return (
            "[Detect the language of the message below yourself and reply ONLY "
            "in that same language — English, Tagalog/Taglish, or Waray. "
            "Do not translate the message; just answer naturally in the "
            "language the user used.]"
        )
    lang_name = {
        "english": "English",
        "tagalog": "Tagalog/Taglish",
        "waray": "Waray",
    }.get(language, "Tagalog/Taglish")
    return (
        f"[Reply in {lang_name}. The message below is {lang_name} — "
        f"answer in {lang_name} only.]"
    )


def _build_openai_system_prompt(language='tagalog'):
    base_guidelines = (
        "SAFETY RULES (follow strictly):\n"
        "1. NEVER diagnose any medical or psychological condition.\n"
        "2. NEVER prescribe medication or suggest stopping medication.\n"
        "3. NEVER claim to be a licensed therapist, doctor, or counselor.\n"
        "4. NEVER encourage harmful behavior, self-harm, or violence.\n"
        "5. NEVER share personal opinions on politics, religion, or controversial topics.\n"
        "6. NEVER generate hate speech, discriminatory, or offensive content.\n"
        "7. If the user is in crisis, ALWAYS direct them to professional help and hotlines.\n"
        "8. If asked about illegal activities, refuse and redirect to positive support.\n"
        "9. SCOPE: answer school and college ACADEMIC QUESTIONS FULLY — subject lessons, concepts, homework help, and step-by-step solutions for any subject (math, algebra, calculus, statistics, physics, chemistry, biology, computer programming, engineering, accounting, economics, psychology, nursing, humanities, research/thesis, and more) — plus academic struggles, study habits, and school-related concerns.\n"
        "10. For NON-academic topics (chitchat unrelated to school, politics, or anything you truly cannot know), briefly decline and bring the conversation back to school. NEVER decline a school, subject, lesson, homework, or research question — always answer those.\n"
        "\n"
        "ACADEMIC SUBJECT & LESSON ANSWERS (very important):\n"
        "- Give the ACTUAL answer to the subject question, then explain HOW you got it in simple steps so the student learns.\n"
        "- For problem-solving, show one short worked example with the steps filled in.\n"
        "- Define a subject term in simple words first, then give one everyday example.\n"
        "- If the question refers to a picture, file, or specific module you cannot see, say so briefly, answer what you can, and ask for the missing part.\n"
        "- Never refuse a school, subject, lesson, homework, or research question — refusing those is a mistake.\n"
        "\n"
        "RESPONSE STYLE (very important):\n"
        "- Be warm, empathetic, validating, and calm.\n"
        "- Write for a Filipino high school / college student.\n"
        "- Use VERY SIMPLE, everyday words only. Explain like the student is 12 years old. EXCEPTION for subject and lesson answers: you may use the proper term for that subject (for example derivative, mitosis, for loop) — then explain it in simple words right away.\n"
        "- When giving emotional support and study advice, NEVER use medical, scientific, or technical words unless unavoidable "
        "(for example: cortisol, dopamine, serotonin, neuroplasticity, anhedonia, hypothalamic, "
        "allostatic, behavioral activation, cognitive, physiological, intervention, efficacy, "
        "assessment, clinician, pharmacological, psychotherapy, MBSR, PMR, vagal, amygdala).\n"
        "- If a hard word is unavoidable, explain it right away in one short, simple sentence "
        "using a familiar example.\n"
        "- When your reply is in Tagalog or Taglish, use ONLY simple, everyday words that students use when talking to friends. "
        "NEVER use deep, literary, formal, or old-fashioned Tagalog words (malalalim na Tagalog). "
        "Simple replacements: 'nararapat' -> 'dapat', 'katinuan' -> 'malinaw na pag-iisip', 'sukatan' -> 'batayan', "
        "'pagtugon' -> 'gagawin o sagot', 'pananalig' -> 'tiwala', 'kapakanan' -> 'ikabubuti', 'kaligtaan' -> 'katamaran', "
        "'gawi' -> 'ugali o nakagawian', 'nangangahulugang' -> 'ibig sabihin', 'nauunawaan' -> 'naiintindihan'.\n"
        "- Natural Taglish is perfectly fine - write the way Filipino students actually talk. If an everyday English word is clearer than a deep Tagalog word, use the English word.\n"
        "- Use short sentences (ideally under 15 words each).\n"
        "- FORMAT LIKE CHATGPT (professional and easy to read): start with 1 short validating paragraph, then give 2-4 practical tips. Use **bold** only for key phrases, and use numbered steps (1. 2. 3.) or simple dashes (-) for lists. Separate ideas with blank lines so the answer looks clean and organized. EXCEPTION for subject, lesson, and homework answers: skip the validating paragraph and tips — answer directly with short steps or a short worked example, still clean and organized.\n"
        "- ALWAYS FINISH your answer completely. NEVER stop mid-sentence or leave words hanging. Every reply must end with a proper ending punctuation (. ! ?). Keep support replies short: 1 paragraph plus 2-4 tips. Subject and lesson answers: short steps or one short worked example — finish every sentence.\n"
        "- Write complete, grammatically correct sentences from start to finish. Every sentence must have a clear beginning and end - NEVER cut a sentence mid-way or leave a word hanging.\n"
        "- NEVER repeat the same sentence or list item twice. Each numbered step must be unique. If you are giving examples (like 10 sentences), number them 1 to 10 in order with NO duplicates and NO skipped numbers.\n"
        "- NEVER output HTML tags like <br>, <p>, or <div>. Use plain blank lines to separate paragraphs.\n"
        "- Keep the formatting clean: use only **bold**, numbered lists, dashes, and plain punctuation. NEVER use hashtags, backticks, tildes, emojis, HTML, or stray symbols. The app will render the reply beautifully, so write proper markdown structure.\n"
        "- STAY ON TOPIC: answer the user's academic concern, subject, or lesson question fully. For follow-up messages (like yes, and, how, what else, go on), continue the SAME topic you were already discussing instead of starting a new unrelated topic.\n"
        "- Use simple sentence association: each sentence must clearly connect to the previous one so the whole reply reads as one clear answer.\n"
        "- Acknowledge the user's feelings before offering suggestions when the user shares a struggle. For subject and lesson questions, answer directly first.\n"
        "- Use a supportive, non-judgmental tone.\n"
        "- Include practical, actionable tips when relevant.\n"
    )
    if language == 'waray':
        role = (
            "You are a compassionate academic support chatbot for students. "
            "You support students through academic struggles AND answer school and college "
            "subject and lesson questions (homework, definitions, worked examples). "
            "Always answer in Waray. "
        )
    elif language == 'english':
        role = (
            "You are a compassionate academic support chatbot for students. "
            "You support students through academic struggles AND answer school and college "
            "subject and lesson questions (homework, definitions, worked examples). "
            "Always answer in English. "
        )
    elif language == 'auto':
        # Hindi sigurado ang detector — walang pinapilitang wika. Ang AI
        # ang susunod sa mismong wika ng huling mensahe ng user (parang ChatGPT).
        role = (
            "You are a compassionate academic support chatbot for students. "
            "You support students through academic struggles AND answer school and college "
            "subject and lesson questions (homework, definitions, worked examples). "
            "Always answer in the SAME language as the user's last message "
            "(English, Tagalog/Taglish, or Waray). "
        )
    else:
        role = (
            "You are a compassionate academic support chatbot for students. "
            "You support students through academic struggles AND answer school and college "
            "subject and lesson questions (homework, definitions, worked examples). "
            "Always answer in Tagalog or Taglish. "
        )

    language_rules = (
        "\nLANGUAGE RULES (very important — HIGHEST PRIORITY, overrides everything else):\n"
        "- FIRST, look ONLY at the user's LAST message. Detect its language, then reply in that SAME language. No exceptions.\n"
        "- A single English word (for example 'overthinker', 'burnout', 'time', 'thesis', 'hello')\n"
        "  IS an English message: answer in English only. NEVER answer a lone English word in Tagalog.\n"
        "- A single Tagalog word (for example 'puyat', 'pagod', 'kumusta', 'salamat')\n"
        "  IS a Tagalog message: answer in Tagalog/Taglish only. NEVER answer a lone Tagalog word in English.\n"
        "- A single Waray word (for example 'maupay', 'bulig', 'pahuway')\n"
        "  IS a Waray message: answer in Waray only. NEVER answer a lone Waray word in another language.\n"
        "- A lone borrowed English word inside a Tagalog sentence (for example 'overthinker'\n"
        "  inside 'Na-overthinker ako') does NOT make the sentence English: answer in Tagalog/Taglish.\n"
        "- English question -> answer in English only.\n"
        "- Tagalog/Taglish question -> answer in Tagalog/Taglish only.\n"
        "- Waray question -> answer in Waray only.\n"
        "- Never mix languages in one reply unless the user mixed them first.\n"
        "- Do not translate the user's message; just answer naturally in their language.\n"
        "- If you are unsure of the language, answer in English when the message looks like English words,\n"
        "  otherwise match the detected language. NEVER default to Tagalog for an English-looking message.\n"
    )
    return role + language_rules + "\n" + base_guidelines


def _history_to_prompt_lines(history, limit=6):
    """Gawing prompt lines ang huling usapan para manatiling on-topic ang AI.

    ``history`` ay list ng (user_text, bot_text) tuples. Kinukuha lang ang
    huling ``limit`` na palitan para hindi humaba ang prompt.
    """
    if not history:
        return []
    lines = []
    for user_text, bot_text in list(history)[-limit:]:
        if user_text:
            lines.append(f"Earlier user: {str(user_text).strip()[:300]}")
        if bot_text:
            lines.append(f"Earlier assistant: {str(bot_text).strip()[:300]}")
    return lines


def _request_chat_continuation(client, model, messages, partial_text,
                               max_tokens=600, temperature=0.4):
    """Isang beses na magpatuloy kapag na-cut (finish_reason = "length") ang sagot.

    Ibabalik ang dagdag na teksto na dapat idikit sa dulo ng ``partial_text``
    (hindi na uulit: sinasabi nating ituloy lang mismo kung saan huminto ang
    modelo), o ``None`` kapag walang naibigay.
    """
    try:
        continuation = client.chat.completions.create(
            model=model,
            messages=messages + [
                {"role": "assistant", "content": partial_text},
                {
                    "role": "user",
                    "content": (
                        "Your previous reply was cut off. Continue it exactly "
                        "where it stopped without repeating anything, and "
                        "finish the whole answer."
                    ),
                },
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if (
            continuation.choices
            and continuation.choices[0].message
            and getattr(continuation.choices[0].message, "content", None)
        ):
            return continuation.choices[0].message.content
    except Exception:
        logging.exception("Chat continuation request failed.")
    return None


def _gemini_reply_was_cut(response):
    """True kapag na-max-tokens ang Gemini reply (hindi pa tapos ang sagot)."""
    try:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return False
        reason = str(getattr(candidates[0], "finish_reason", "")).upper()
        return "MAX_TOKENS" in reason or reason.endswith("2")
    except Exception:
        return False


def _request_gemini_continuation(model, full_prompt, partial_text):
    """Magpatuloy ng isang beses kapag na-cut ang Gemini reply."""
    try:
        continuation = model.generate_content(
            contents=(
                f"{full_prompt}\n\n"
                f"Your previous reply was cut off here:\n{partial_text}\n\n"
                "Continue it exactly where it stopped without repeating "
                "anything, and finish the whole answer. Continue:"
            )
        )
        if getattr(continuation, "parts", None):
            extra = (continuation.text or "").strip()
            if extra:
                return extra
    except Exception:
        logging.exception("Gemini continuation request failed.")
    return None


def _call_openai_api(user_input, intent=None, language='tagalog', history=None):
    if not _openai_available():
        return None

    return _run_openai_chat(user_input, intent=intent, language=language, history=history)


def _run_openai_chat(user_input, intent=None, language='tagalog', history=None):
    """Ang aktwal na OpenAI chat completion call (nire-reuse ng AI-first path)."""
    try:
        api_key = _get_openai_api_key()
        if not api_key:
            logging.error("OpenAI API key not found. Please set it in the .env file.")
            return None
        
        # --- DIAGNOSTIC LOG ---
        # This will show us which key the app is actually using.
        key_preview = f"{api_key[:5]}...{api_key[-4:]}" if len(api_key) > 9 else "Invalid Key"
        logging.warning(f"Attempting to use OpenAI API key: {key_preview}")
            
        openai_module = _import_openai()
        client = openai_module.OpenAI(api_key=api_key)
        model = os.environ.get("MENTALHEALTHWEB_OPENAI_MODEL", "gpt-3.5-turbo")

        messages = [
            {"role": "system", "content": _build_openai_system_prompt(language)},
        ]
        for line in _history_to_prompt_lines(history):
            if line.startswith("Earlier user:"):
                messages.append({"role": "user", "content": line[len("Earlier user:"):].strip()})
            else:
                messages.append({"role": "assistant", "content": line[len("Earlier assistant:"):].strip()})
        messages.append({"role": "user", "content": (
            f"{_language_directive(language)}\n{user_input}"
        )})
        if intent:
            messages.append({"role": "assistant", "content": f"Detected intent: {intent}."})

        completion = _create_chat_completion(client, model, messages)

        if completion.choices and completion.choices[0].message:
            choice = completion.choices[0]
            partial = (choice.message.content or "").strip()
            if partial and "length" in str(getattr(choice, "finish_reason", "")).lower():
                logging.info("OpenAI reply was cut off (finish_reason=length); requesting a continuation.")
                extra = _request_chat_continuation(client, model, messages, partial)
                if extra:
                    partial = partial + extra
            if partial:
                return _clean_ai_text(partial)

        logging.warning("OpenAI response was empty or malformed.")
        return None

    except Exception as e:
        # Dati: `except openai_module.RateLimitError` — nagiging NameError iyon
        # kapag hindi ma-import ang openai bago pa nangyari ang error, kaya
        # napupunta ang lahat ng error sa generic handler.
        kind = _classify_ai_error(e)
        if kind:
            logging.error("OpenAI %s error: %s", kind, e)
            # Ipagpatuloy sa susunod na provider (Gemini) imbes na agad na
            # sabihing "masyadong mabilis" ang user.
            _note_ai_error(kind)
            return None
        logging.exception(f"OpenAI API call failed: {e}")
        return None

# ----------------------------


def _language_matched_emergency_fallback(user_input, language):
    """Emergency fallback kapag mali pa rin ang wika matapos ang AI retry.

    Hindi ito ang dating dataset-first — naaabot lang ito kapag ang AI ay
    sumagot na pero MALI ANG WIKA kahit matapos ang correction retry.
    Laging tugma sa hininging wika ang ibabalik.
    """
    text = (user_input or "").lower().strip()
    intent = detect_intent(text)
    if intent:
        intent_data = INTENTS.get(intent, {})
        choices = _intent_response_choices(intent, language, intent_data)
        if choices:
            return (random.choice(choices), intent)
    faq_answer = get_faq_answer(text, language)
    if faq_answer:
        return (faq_answer, None)
    if language == "waray":
        generic_fallbacks = WARAY_FALLBACKS
    elif language == "english":
        generic_fallbacks = GENERIC_FALLBACKS_EN
    else:
        generic_fallbacks = GENERIC_FALLBACKS_TL
    return (random.choice(generic_fallbacks), None)


def _retry_ai_with_language_correction(user_input, language, history=None):
    """Isang retry na may correction prompt kapag mali ang wika ng AI reply.

    Nagbabalik ng (reply, ok) — ok=True kapag tumutugma na ang wika.
    """
    try:
        from .bot_responses_i18n import _post_check_correction_prompt
    except ImportError:  # pragma: no cover - kapag direktang pinatakbo bilang script
        from bot_responses_i18n import _post_check_correction_prompt
    correction = _post_check_correction_prompt(user_input, language)
    retry_input = f"{correction}\n\nOriginal message: {user_input}"
    if _groq_available():
        retry = _call_groq_api(retry_input, language, history=history)
        if retry and ai_reply_matches_language(retry, language):
            return retry, True
        if retry:
            return retry, False
    if _openai_available():
        retry = _run_openai_chat(retry_input, language=language, history=history)
        if retry and ai_reply_matches_language(retry, language):
            return retry, True
        if retry:
            return retry, False
    if _gemini_available():
        retry = _call_gemini_api(retry_input, language, history=history)
        if retry and ai_reply_matches_language(retry, language):
            return retry, True
        if retry:
            return retry, False
    return None, False


def _ai_first_enabled():
    """True kapag AI ang dapat sumagot muna (default ON)."""
    value = os.environ.get("MENTALHEALTHWEB_AI_FIRST", "true")
    return value.strip().lower() in ("1", "true", "yes", "on")


AI_FIRST_ENABLED = _ai_first_enabled()


def _call_ai_reply(user_input, language='tagalog', history=None, **kwargs):
    """AI-first reply chain: Groq (API key) -> OpenAI -> Gemini.

    Nagbabalik ng AI reply kung mayroon, o None kapag walang available na AI
    (para mag-fallback sa dataset).
    """
    global _ai_error_kind
    # Bagong tanong = bagong pagkakataon para sa mga provider.
    _ai_error_kind = None

    # Primary: Groq (libre, mabilis) — ito ang GROQ_API_KEY sa Render.
    if _groq_available():
        groq_reply = _call_groq_api(user_input, language, history=history)
        if groq_reply:
            return groq_reply

    # Fallback 1: OpenAI (may API key)
    if _openai_available():
        openai_reply = _run_openai_chat(user_input, language=language, history=history)
        if openai_reply:
            return openai_reply

    # Fallback 2: Gemini (kung may valid key)
    if _gemini_available():
        gemini_reply = _call_gemini_api(user_input, language, history=history)
        if gemini_reply:
            return gemini_reply

    # Walang nakasagot na provider. Dalawang bagay lang ang posibleng ipakita:
    # * "quota"     -> naubos talaga ang limit/tokens ng API key; kailangang
    #                   malaman ito ng user at ng administrator (hindi aayos sa
    #                   ilang segundo lang).
    # * "rate_limit"-> pagkatapos ng retry, pumapayag pa rin; mag-fallback na lang
    #                   sa dataset para may sagot pa rin ang chatbot (walang
    #                   "masyadong mabilis" na pambati sa bawat tanong).
    if _ai_error_kind == "quota":
        logging.error("All AI providers are out of quota/limits for this request.")
        return _ai_error_reply(language, _ai_error_kind)
    if _ai_error_kind == "rate_limit":
        logging.warning("All AI providers are rate-limited; using the dataset fallback.")
    return None


# ----------------------------
# DETECTION & RESPONSE LOGIC
# ----------------------------
def _has_signal(text, signal):
    normalized_text = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    normalized_signal = re.sub(r"[^a-z0-9]+", " ", signal.lower()).strip()
    if not normalized_signal:
        return False
    return re.search(rf"(?<!\w){re.escape(normalized_signal)}(?!\w)", normalized_text) is not None


def resolve_response_language(user_input, preferred='tagalog'):
    """Tinutukoy ang wikang gagamitin sa SAGOT ng bot.

    Sinusunod ang wika ng tanong ng user (English -> English, Tagalog ->
    Tagalog, Waray -> Waray) at babalik sa ``preferred`` (setting ng user)
    kapag hindi malinaw ang wika ng tanong.
    """
    preferred = (preferred or 'tagalog').lower()
    if preferred not in LANGUAGE_CHOICES:
        preferred = 'tagalog'

    detected = detect_language(user_input)
    if detected and detected != preferred:
        # Malinaw ang wika ng tanong, sundin natin ito kahit iba sa setting.
        return detected
    if detected:
        return detected

    english, tagalog, waray = score_languages(user_input)
    if preferred == 'waray' and waray >= 1 and waray >= tagalog:
        # Waray ang setting at may Waray na palatandaan -> Waray ang sagot.
        return 'waray'
    return preferred


def _crisis_response(language):
    if language == 'waray':
        return WARAY_CRISIS_RESPONSE
    if language == 'english':
        return CRISIS_RESPONSE
    return CRISIS_RESPONSE_TL


def _intent_response_choices(intent, language, intent_data):
    """Pumipili ng response list na tugma sa wika ng tanong."""
    if language == 'waray':
        choices = WARAY_RESPONSES.get(intent, [])
    elif language == 'english':
        choices = ENGLISH_RESPONSES.get(intent, [])
        if not choices:
            # Built-in na sagot lang ang gamitin kapag English din ito —
            # hindi puwedeng ibalik ang Tagalog/Waray na sagot sa English
            # na tanong (hal. "how to manage stress" na may Tagalog na
            # built-in response). Kapag hindi English, generic English na lang.
            built_in = intent_data.get("response", [])
            if built_in and detect_language(" ".join(built_in)) == 'english':
                choices = built_in
            else:
                choices = GENERIC_FALLBACKS_EN
    else:
        choices = TAGALOG_RESPONSES.get(intent, [])
    if not choices:
        choices = intent_data.get("response", [])
    return choices


def _intent_follow_ups(intent, language, intent_data):
    """Pumipili ng follow-up questions na tugma sa wika ng tanong."""
    if language == 'english':
        choices = ENGLISH_FOLLOW_UPS.get(intent, [])
        if choices:
            return choices
        # Huwag mag-append ng Tagalog/Waray follow-up sa English na sagot —
        # isa ito sa paraan kung paano nai-mix ang wika ng reply.
        built_in = intent_data.get("follow_up", [])
        if built_in and detect_language(" ".join(built_in)) == 'english':
            return built_in
        return []
    return intent_data.get("follow_up", [])


def detect_intent(text):
    """Detects the most likely intent from the user's text."""
    best_intent = None
    highest_score = 0
    highest_priority = -1

    for intent, data in INTENTS.items():
        matches = sum(1 for s in data.get("signals", []) if _has_signal(text, s))
        if matches > 0:
            priority = INTENT_PRIORITY.get(intent, 0)
            # Prioritize by score, then by priority
            if matches > highest_score or (matches == highest_score and priority > highest_priority):
                highest_score = matches
                highest_priority = priority
                best_intent = intent

    return best_intent

ACADEMIC_INTENTS = {
    "school assignment", "school project", "school activity",
    "financial problem", "stress", "stress_exams", "procrastination", "perfectionism",
    "unmotivated study", "failing subject", "major uncertainty", "financial stress",
    "work school balance", "burnout", "time_management", "imposter syndrome",
    "freshman adjustment", "impending deadline", "test anxiety", "feeling unmotivated",
    "fear of failure", "stress exams", "procrastination tl", "perfectionism tl",
    "imposter syndrome", "homesick", "struggling_grades_tl", "financial_stress tl",
    "burnout tl", "stress_management_tl", "motivation tl", "fear of failure tl",
    "grounding request"
}
ACADEMIC_INTENTS.update({"thesis_topic_struggle", "recitation_anxiety", "feeling_behind", "org_work_overload"})
ACADEMIC_INTENTS.update({"thesis_topic_struggle", "recitation_anxiety", "feeling_behind", "org_work_overload", "groupmate_problem", "reading_overload", "career_anxiety"})


def academic_referral(language='tagalog'):
    if language == 'english':
        return ACADEMIC_REFERRAL_EN
    if language == 'waray':
        return (
            "Kaya ko nga sumat ha mga klase han subject — mga leksyon, homework, ngan "
            "step-by-step nga solusyon, uk ha akademiko nga problema sugad han "
            "exam stress ngan time management. Pangutana mo ako mahitungod han imo mga klase!"
        )
    return (
        "Kaya kong sagutin ang mga tanong sa school at college subjects — mga lesson, "
        "homework, at step-by-step na solusyon — pati ang academic struggles gaya ng "
        "exam stress at time management. Magtanong ka lang tungkol sa mga klase mo!"
    )


def is_academic_intent(intent):
    return intent in ACADEMIC_INTENTS


def generate_response(user_input, last_intent=None, language='tagalog', history=None):
    """
    Main function to generate a bot response.

    Ang wika ng sagot ay sinusunod ang wika ng tanong ng user (English ->
    English, Tagalog -> Tagalog, Waray -> Waray). Ang ``language`` argument
    ang ginagamit na fallback kapag hindi malinaw ang wika ng tanong.

    Ang ``history`` ay opsyonal na list ng (user_text, bot_text) tuples mula
    sa mga huling mensahe — ginagamit ito ng AI para manatiling on-topic
    ang sagot sa follow-up questions.

    Returns a tuple: (response_text, new_intent, is_crisis_flag, is_abusive_flag)
    """
    text = user_input.lower().strip()
    is_abusive = 0
    new_intent = None

    # 0. Language of the REPLY (matching the user's question)
    detected_lang = detect_language(user_input)
    resp_lang = resolve_response_language(user_input, language)

    # 1. Crisis Check (Highest Priority — NEVER bypassed, even in AI-first mode)
    # We use the dedicated crisis keywords for immediate, hard-coded detection.
    if any(k in text for k in CRISIS_KEYWORDS):
        conversation_memory["last_intent"] = "crisis_situation"
        # Also flag if abusive language is present in a crisis message
        is_abusive_in_crisis = 1 if any(k in text for k in ABUSIVE_KEYWORDS) else 0

        resp = _crisis_response(resp_lang)
        return (resp, "crisis_situation", 1, is_abusive_in_crisis)

    # 2. Abusive Language Check (High Priority — NEVER bypassed, even in AI-first mode)
    if any(k in text for k in ABUSIVE_KEYWORDS):
        is_abusive = 1
        # Provide a direct response to the abusive language before proceeding.
        # The ban logic in app.py will still trigger based on the is_abusive=1 flag.
        if resp_lang == 'waray':
            abusive_response = "Nasasabtan ko nga bangin nadidismaya ka, pero alayon paggamit hin maupay nga mga pulong. Paonan-o ako makakabulig ha imo ha maupay nga paagi yana?"
        elif resp_lang == 'english':
            abusive_response = ABUSIVE_RESPONSE_EN
        else:
            abusive_response = "Naiintindihan ko na maaaring ikaw ay nadidismaya, pero panatilihin nating magalang ang ating pag-uusap. Paano kita matutulungan sa maayos na paraan ngayon?"
        return (abusive_response, new_intent, 0, 1)

    # 3. AI-FIRST (pinaka-mahigpit): lahat ng normal na tanong ay sinasagot
    # ng API key AI — English, Tagalog, o Waray man, kahit single word lang.
    # I-disable ito sa pamamagitan ng MENTALHEALTHWEB_AI_FIRST=false (default ON).
    # Crisis at abusive messages ay hindi dumadaan dito (nahuli na sila sa itaas).
    # Ang dataset/intent path sa ibaba ay EMERGENCY FALLBACK lang — naaabot lang
    # kapag walang available/magandang sagot ang AI (no keys, quota, error, empty).
    ai_first = AI_FIRST_ENABLED
    ai_reply = None
    if not is_abusive and ai_first:
        # Auto mode: kapag hindi sigurado ang detector (hal. "milestone",
        # typo, o unfamiliar na salita), ang AI ang magdedekta ng wika ng
        # mensahe — parang ChatGPT. Walang post-check doon kasi nga hindi
        # namin alam ang tamang wika; ang AI ang sumusunod sa mensahe.
        ai_lang = resp_lang if detected_lang else 'auto'
        ai_reply = _call_ai_reply(user_input, ai_lang, history=history)
        if ai_reply:
            # POST-CHECK (output validation): siguraduhing tumutugma ang wika
            # ng AI reply sa hiningi bago ito ipakita sa user. Hindi kinakailangan
            # kapag auto — wala tayong alam na tamang wika na paghahambingan.
            if ai_lang == 'auto' or ai_reply_matches_language(ai_reply, resp_lang):
                return (ai_reply, None, 0, is_abusive)
            logging.warning(
                "AI reply failed language post-check (expected=%s); retrying with correction.",
                resp_lang,
            )
            retry_reply, retry_ok = _retry_ai_with_language_correction(
                user_input, resp_lang, history=history
            )
            if retry_ok and retry_reply:
                return (retry_reply, None, 0, is_abusive)
            logging.warning(
                "AI retry still mismatched language (expected=%s); using language-matched fallback.",
                resp_lang,
            )
            fallback_reply, fallback_intent = _language_matched_emergency_fallback(
                user_input, resp_lang
            )
            return (fallback_reply, fallback_intent, 0, is_abusive)

    # 4. Dataset path — ginagamit lang kapag:
    #    (a) naka-disable ang AI-first mode, o
    #    (b) walang available/magandang sagot ang AI (no keys, quota, error, empty reply).
    faq_answer = get_faq_answer(text, resp_lang)
    if faq_answer:
        return (faq_answer, None, 0, is_abusive)

    # 5. Intent Detection (fallback kapag walang AI)

    # 4. Intent Detection (Primary Path)
    intent = detect_intent(text)
    if intent:
        new_intent = intent
        intent_data = INTENTS.get(intent, {})

        # Piliin ang response na tugma sa wika ng tanong.
        response_choices = _intent_response_choices(intent, resp_lang, intent_data)

        response = random.choice(response_choices) if response_choices else ""

        # Append a follow-up question if available and appropriate
        # Waray has no follow-ups yet, so we skip them for Waray replies.
        follow_up_choices = _intent_follow_ups(intent, resp_lang, intent_data)
        if follow_up_choices and resp_lang != 'waray':
            follow_up = random.choice(follow_up_choices)
            response = f"{response}\n\n{follow_up}"

        # The crisis flag is determined by the intent's priority level.
        # Priority 6 or higher is considered a crisis that needs flagging.
        is_crisis = 1 if INTENT_PRIORITY.get(intent, 0) >= 6 else 0
        
        # If it's a crisis-level intent (like suicidal_thoughts), also send the crisis response.
        # This handles cases where the intent detection catches it instead of the keyword list.
        if is_crisis and intent != "grounding_request": # Don't send crisis text for grounding
             return (_crisis_response(resp_lang), new_intent, 1, is_abusive)

        return (response, new_intent, is_crisis, is_abusive)

    # 6. Fallback Response — naabot lang ito kapag walang AI reply AT walang
    # intent ang na-detect (hal. naka-disable ang AI-first o down ang AI).
    if resp_lang == 'waray':
        generic_fallbacks = WARAY_FALLBACKS
    elif resp_lang == 'english':
        generic_fallbacks = GENERIC_FALLBACKS_EN
    else:
        generic_fallbacks = GENERIC_FALLBACKS_TL
    return (random.choice(generic_fallbacks), new_intent, 0, is_abusive)