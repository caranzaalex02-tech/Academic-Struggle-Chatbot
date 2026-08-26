# bot_logic.py
import csv
import os
import random
import re
import sqlite3
import logging
from pathlib import Path

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
    # EMOTIONAL / MENTAL HEALTH (Conversational)
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
            "Mabigat talaga ang problemang pinansyal.\nPaalala:\n• Hindi ito sukatan ng halaga mo\n• Maraming students ang dumadaan dito\n• Hindi ka nag-iisa"
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
            "Thank you for trusting me with your thoughts. You're doing amazing by reaching out and taking care of your mental health!",
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

Ang score mo sa exam ay hindi sukatan ng pagkatao mo. Ang mahalaga ay ang iyong pagsisikap. Kaya mo 'yan! 💪"""]
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
        "response": ["""Nauunawaan ko ang pressure na nararamdaman mo. Ang stress sa exam ay normal para sa lahat ng estudyante. Subukan mong maging organized—gumawa ng study schedule at mag-break regularly.
Ang mahalaga ay ang iyong pagsisikap, hindi ang perpektongong score. Kayang-kaya mo yan!
"Ang tagumpay ay sumisikad na walang tigil araw-araw." – Robert Collier"""],
        "follow_up": []
    },

   

    "imposter_syndrome_tl": {
        "signals": ["imposter syndrome", "hindi ko deserve", "swerte lang", "fraud", "makakadiscover sila", "hindi ako talaga magaling"],
        "response": ["""Ang imposter syndrome ay lalo sa magagatalinong tao! Kung nandito ka, nangangahulugang deserve mo talaga ito. Tinatamaan ang lahat, pero hindi lang nila sinasabi.
Maglingkod sa sarili mo ng magandang feedback—tandaan ang mga success mo. Ikaw ay genuine, at kaya mo talaga.
"Ang impostor syndrome ay isang ilusyon, hindi katotohanan." – Unknown"""],
        "follow_up": []
    },

    "homesick_tl": {
        "signals": ["homesick", "nag-iisa sa college", "miss home", "miss family", "college away", "layo sa bahay"],
        "response": ["""Ang pakiramdam na nag-iisa ay natural, lalo na kung malayo ka sa tahanan. Makipag-ugnayan sa pamilya regularly—video call, chat, kahit mensahe lang.
Ngunit samantalahin din ang kasama mo ngayon. Ang halo ng pamilya at bagong mga kaibigan ay lumikha ng bagong tahanan. Kaya mo!
"Mapapangalagaan mo ang tatlong tahanan: kung saan ka mula, kung nasaan ka ngayon, at kung saan ka papunta." – Unknown"""],
        "follow_up": []
    },

    "struggling_grades_tl": {
        "signals": ["struggling grades", "bumababa grade", "hindi nakakuha", "class standing", "exam result", "maraming E", "mababang grado"],
        "response": ["""Ang hindi pagpapabuti ng grade ay nakakapagod, pero hindi ito dahilan para sa iyo. Makipag-usap sa teacher tungkol sa extra credit, tutoring, o kung ano ang dapat mong gawin.
Maraming estudyante ang tumaas mula sa mababang punto. Ang pagkamali ay hindi pangmatagalan—ito ay pagkakataon na mag-improve.
"Ang bawat expert ay batang nagsimula." – Unknown"""],
        "follow_up": []
    },

    "financial_stress_tl": {
        "signals": ["walang pera", "gastos", "mahirap ang bayad", "financial", "utang", "bills", "presyo", "bili hindi kaya"],
        "response": ["""Ang financial stress ay tunay, ngunit hindi ito forever. Hanapin ang resources sa school: scholarships, grants, student loans, o work-study programs.
Mag-budget, itanong tulong sa pamilya kung kaya nila, at tanggapin ang tulong na inaalok. Ang pagiging matalino sa pera ay nagsisimula sa pag-plano ngayon.
"Ang pera ay tool, hindi iyong identity. Gamitin ito ng matalino." – Unknown"""],
        "follow_up": []
    },

    "burnout_tl": {
        "signals": ["burnout", "pagod na sobra", "exhausted", "walang energy", "laging busy", "burnout talaga", "tired na tired", "no more fuel"],
        "response": ["""Ang burnout ay sign na kailangan mo ng rest. Hindi ito pagweak—ito ay sign na tao ka. Magsimula ng napakaliit na pahinga: 10 minuto lang para sa iyong sarili.
Sabihin ang 'no' sa ilang bagay. Bigyan ng priyoridad ang iyong kalusugan. Walang achievable na target na sulit nang sirain ang iyong buhay.
"Ang pahinga ay hindi kaligtaan. Ito ay investment sa iyong kinabukasan." – Unknown"""],
        "follow_up": []
    },

    

    "stress_management_tl": {
        "signals": ["stress", "stressed", "relax", "chill", "way mag destress", "meditation", "calm", "how to manage stress", "reduce stress", "paano i-manage stress", "pano mag-relax", "tips destress", "stress relief"],
        "response": ["""Chronic stress activates the hypothalamic-pituitary-adrenal (HPA) axis, elevating cortisol levels and impairing prefrontal cortex function. This is physiologically dangerous but treatable.

EVIDENCE-BASED STRESS MANAGEMENT STRATEGIES:

1. PHYSIOLOGICAL REGULATION:
   - Diaphragmatic breathing (4-7-8 pattern): Activates vagal tone, downregulates amygdala.
   - Progressive muscle relaxation (PMR): Reduces somatic tension; proven efficacy in cortisol reduction.
   - Aerobic exercise: Evidence-level "A" intervention; enhances BDNF and reduces allostatic load.

2. COGNITIVE INTERVENTIONS:
   - Identify stressor locus of control (changeable vs. unchangeable).
   - Implement acceptance and commitment therapy (ACT) for unchangeable stressors.
   - Time management and task prioritization reduce decision fatigue.

3. BEHAVIORAL ACTIVATION:
   - Engage in personally-meaningful activities (enhances dopaminergic reward pathways).
   - Mindfulness meditation (8 weeks MBSR shows significant cortisol reduction).
   - Social connection buffering (strong predictor of stress resilience).

4. SLEEP & NUTRITION:
   - Maintain consistent sleep schedule (optimizes circadian HPA axis function).
   - Limit stimulants (caffeine inhibits stress recovery).
   - Omega-3 supplementation shows preliminary stress-reduction efficacy.

ASSESSMENT: If chronic stress impairs occupational/academic/social functioning, seek comprehensive mental health evaluation. Clinician-guided intervention may include psychotherapy and/or pharmacological support."""],
        "follow_up": []
    },

    "motivation_tl": {
        "signals": ["motivation", "motivate", "encourage", "push myself", "walang gana", "drive", "energy", "how to stay motivated", "increase motivation", "paano motivated", "pano mag-motivation", "tips motivation", "ways to motivate","motivational"],
        "response": ["""Motivation is a consequence of action, not a prerequisite. This is neurologically established: behavioral activation precedes mood elevation via dopaminergic pathways.

NEUROCHEMICAL BASIS:
- Dopamine (motivational drive) increases with ACTION, not anticipation.
- Each completed micro-task triggers dopamine release, reinforcing behavior.
- Anhedonia (lack of interest) in depression improves fastest through behavioral activation FIRST.

IMPLEMENTATION (EVIDENCE-BASED):
1. Goal Decomposition: Break objective into absurdly small tasks (one paragraph, 5-minute walk).
2. Immediate Initiation: Start NOW—momentum builds momentum. No "feeling like it" required.
3. Task Completion Reinforcement: Dopamine surge follows task completion, increasing subsequent motivation.
4. Habit Formation: Repetition for 21-66 days creates neural pathways (neuroplasticity); motivation becomes automatic.

CLINICAL PRINCIPLE: "Action precedes motivation in the neural reward circuits." Low dopamine states require BEHAVIORAL JUMP START—this is not laziness or character failure; it's neurobiology.

If persistent anhedonia or lack of motivation despite behavioral efforts, assess for depression/ADHD with mental health professional.

Start. Now. One tiny action."""],
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
Magsimula sa malawak na ideya at dahan-dahang gawin itong mas partikular. Makipag-usap sa iyong adviser; nandiyan sila para gabayan ka.
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
        "response": ["""Ang pagiging aktibo sa student organizations ay maganda, pero madali itong maging overwhelming. Mahalagang matutunan ang prioritization.
Alin sa mga gawain ang pinaka-importante? Okay lang din na matutong tumanggi sa ibang responsibilidad para protektahan ang iyong oras at mental health.
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
        "Kun waray ka na gana o kapoy ka na, pamati ha imo lawas. Bangin kinahanglan mo la hin pahuway. Diri karera an pag-eskwela. Importante an imo mental health. Pahuway anay, tapos laban utro."
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
    "what is this app for": "This app is a mental health support chatbot for students, designed to provide emotional support, grounding exercises, and guidance for school stress.",
    "how can i use this chatbot": "You can type your concerns here and the chatbot will respond with support, coping tips, and crisis guidance when needed.",
    "who can use this app": "This app is intended for students and anyone who wants a safe space to talk about stress, anxiety, or emotional struggles."
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


def get_faq_answer(text):
    normalized = text.lower().strip()
    if not normalized:
        return None

    for question, answer in DEFAULT_FAQ_ANSWERS.items():
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


def _call_groq_api(user_input, language='tagalog'):
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
        model = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")

        system_prompt = _build_openai_system_prompt(language)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input}
        ]

        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=280,
            temperature=0.8,
        )

        if completion.choices and completion.choices[0].message:
            return completion.choices[0].message.content.strip()

        logging.warning("Groq response was empty or malformed.")
        return None

    except Exception as e:
        logging.exception(f"Groq API call failed: {e}")
        error_type = type(e).__name__
        if 'rate' in str(e).lower() or 'quota' in str(e).lower():
            if language == 'waray':
                return "An AI service in nagpapahuway makadiyot. Alayon paghulat hin pipira ka segundo ngan pag-try utro."
            return "Masyadong mabilis ang mga tanong. Magpahinga muna tayo sandali at subukan ulit pagkatapos ng ilang segundo."
        return None


def _call_gemini_api(user_input, language='tagalog'):
    """Calls the Google Gemini API as a fallback."""
    if not _gemini_available():
        logging.warning("Gemini API not available (library not installed or key not set).")
        if language == 'waray':
            return "Mayda problema ha AI service (diri naka-install an library). Alayon pagsumat ha administrator."
        return "Nagkaproblema sa AI service (hindi naka-install ang library). Paki-abiso sa administrator."

    try:
        api_key = _get_gemini_api_key()
        if not api_key:
            logging.error("Gemini API key not found. Please set GEMINI_API_KEY in the .env file.")
            if language == 'waray':
                return "Mayda problema ha AI service (waray API key). Alayon pagsumat ha administrator."
            return "Nagkaproblema sa AI service (walang API key). Paki-abiso sa administrator."

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
                full_prompt = f"{system_prompt}\n\nUser: {user_input}\nAssistant:"
                response = model.generate_content(contents=full_prompt)
                if getattr(response, "parts", None):
                    return response.text.strip()
                logging.error("Gemini API call was blocked by safety settings or returned no content.")
                if language == 'waray':
                    return "Pasensya, diri ko mababaton iton nga pakiana. Bangin an topic kay sensitibo."
                return "Paumanhin, hindi ko masasagot ang tanong na iyan. Ang paksa ay maaaring masyadong sensitibo."
            except Exception as model_error:
                logging.warning("Gemini model %s failed: %s", model_name, model_error)
                if "invalidargument" in str(model_error).lower() and model_name != preferred_models[-1]:
                    continue
                raise model_error

        raise RuntimeError("No Gemini model could satisfy the request.")

    except Exception as e:
        logging.exception(f"Google Gemini API call failed: {e}")
        error_type = type(e).__name__
        logging.error(f"Gemini API call failed with a {error_type}. This will be shown to the user.")

        if "block" in str(e).lower():
            if language == 'waray':
                return "Pasensya, diri ko mababaton iton nga pakiana tungod han safety settings."
            return "Paumanhin, hindi ko masasagot ang tanong na iyan dahil sa safety settings."

        if error_type in ['PermissionDenied', 'Unauthenticated'] or 'API_KEY_INVALID' in str(e).upper():
            if language == 'waray':
                error_message = "Mayda problema ha AI service. Alayon pagsumat ha administrator. (API Key Error)"
            else:
                error_message = "Nagkaproblema sa AI service. Paki-abiso sa administrator. (API Key Error)"
        elif 'deadline' in str(e).lower():
            error_message = "Masyadong matagal bago sumagot ang AI. Subukang muli."
        elif 'invalidargument' in str(e).lower() or error_type == 'InvalidArgument':
            error_message = "Nagkaproblema sa AI service. Paki-abiso sa administrator. (Invalid Argument)"
        else:
            error_message = f"Nagkaproblema sa AI service. Paki-abiso sa administrator. (Error: {error_type})"
        return error_message




def _build_openai_system_prompt(language='tagalog'):
    base_guidelines = (
        "SAFETY RULES (follow strictly):\n"
        "1. NEVER diagnose any medical or mental health condition.\n"
        "2. NEVER prescribe medication or suggest stopping medication.\n"
        "3. NEVER claim to be a licensed therapist, doctor, or counselor.\n"
        "4. NEVER encourage harmful behavior, self-harm, or violence.\n"
        "5. NEVER share personal opinions on politics, religion, or controversial topics.\n"
        "6. NEVER generate hate speech, discriminatory, or offensive content.\n"
        "7. If the user is in crisis, ALWAYS direct them to professional help and hotlines.\n"
        "8. If asked about illegal activities, refuse and redirect to positive support.\n"
        "9. Keep responses focused on academic stress, study habits, and emotional well-being.\n"
        "10. If unsure or the topic is outside your scope, politely say you cannot answer and suggest talking to a trusted adult or counselor.\n"
        "\n"
        "RESPONSE STYLE:\n"
        "- Be warm, empathetic, validating, and calm.\n"
        "- Use simple, clear language appropriate for students.\n"
        "- Keep responses concise (2-4 sentences when possible).\n"
        "- Acknowledge the user's feelings before offering suggestions.\n"
        "- Use a supportive, non-judgmental tone.\n"
        "- Include practical, actionable tips when relevant.\n"
    )
    if language == 'waray':
        return (
            "You are a compassionate Waray mental health support chatbot for students. "
            "Respond in gentle Waray whenever possible.\n\n"
            + base_guidelines
        )
    return (
        "You are a compassionate mental health support chatbot for students. "
        "Answer in Tagalog or Taglish based on the user's input.\n\n"
        + base_guidelines
    )


def _call_openai_api(user_input, intent=None, language='tagalog'):
    if not _openai_available():
        return None

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
            {"role": "user", "content": user_input}
        ]
        if intent:
            messages.append({"role": "assistant", "content": f"Detected intent: {intent}."})

        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=280,
            temperature=0.8,
        )

        if completion.choices and completion.choices[0].message:
            return completion.choices[0].message.content.strip()

        logging.warning("OpenAI response was empty or malformed.")
        return None

    except openai_module.RateLimitError as e:
        logging.error("OpenAI quota/rate limit error: %s", e)
        # Check if the error is specifically about quota
        if 'insufficient_quota' in str(e).lower():
            if language == 'waray':
                return "Pasensya, an AI service in diri available yana tungod kay naubos na an credits. Alayon pagsumat ha administrator."
            return "Pasensya, pansamantalang hindi available ang AI service dahil naubos na ang credits. Paki-abiso sa administrator."
        # Otherwise, it's a rate limit issue (too many requests too fast)
        if language == 'waray':
            return "An AI service in nagpapahuway makadiyot. Alayon paghulat hin pipira ka segundo ngan pag-try utro."
        return "Masyadong mabilis ang mga tanong. Magpahinga muna tayo sandali at subukan ulit pagkatapos ng ilang segundo."
    except Exception as e:
        logging.exception(f"OpenAI API call failed: {e}")
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
    if language == 'waray':
        return (
            "Mas makakabulig ako labi na ha akademiko nga problema sugad han assignment, project, exam stress, "
            " ngan time management. Kun diri ini akademiko nga pakiana, mas maupay nga magamit ka hin iba nga AI "
            "sugad han ChatGPT o Google Bard para hini nga klase hin mga pakiana."
        )
    return (
        "Mas makakatulong ako sa mga tanong na tungkol sa academic struggle gaya ng assignments, "
        "projects, exam stress, at time management. Para sa ibang paksa, subukan mo ang ibang AI tulad "
        "ng ChatGPT o Google Bard."
    )


def is_academic_intent(intent):
    return intent in ACADEMIC_INTENTS


def generate_response(user_input, last_intent=None, language='tagalog'):
    """
    Main function to generate a bot response.
    Returns a tuple: (response_text, new_intent, is_crisis_flag, is_abusive_flag)
    """
    text = user_input.lower().strip()
    is_abusive = 0
    new_intent = None

    # 1. Crisis Check (Highest Priority)
    # We use the dedicated crisis keywords for immediate, hard-coded detection.
    if any(k in text for k in CRISIS_KEYWORDS):
        conversation_memory["last_intent"] = "crisis_situation"
        # Also flag if abusive language is present in a crisis message
        is_abusive_in_crisis = 1 if any(k in text for k in ABUSIVE_KEYWORDS) else 0

        resp = WARAY_CRISIS_RESPONSE if language == 'waray' else CRISIS_RESPONSE
        return (resp, "crisis_situation", 1, is_abusive_in_crisis)

    # 2. Abusive Language Check (High Priority)
    if any(k in text for k in ABUSIVE_KEYWORDS):
        is_abusive = 1
        # Provide a direct response to the abusive language before proceeding.
        # The ban logic in app.py will still trigger based on the is_abusive=1 flag.
        if language == 'waray':
            abusive_response = "Nasasabtan ko nga bangin nadidismaya ka, pero alayon paggamit hin maupay nga mga pulong. Paonan-o ako makakabulig ha imo ha maupay nga paagi yana?"
        else:
            abusive_response = "Naiintindihan ko na maaaring ikaw ay nadidismaya, pero panatilihin nating magalang ang ating pag-uusap. Paano kita matutulungan sa maayos na paraan ngayon?"
        return (abusive_response, new_intent, 0, 1)

    # 3. FAQ dataset lookup (After crisis and abuse checks)
    faq_answer = get_faq_answer(text)
    if faq_answer:
        return (faq_answer, None, 0, is_abusive)

    # 4. Intent Detection (Primary Path)
    intent = detect_intent(text)
    if intent:
        new_intent = intent
        intent_data = INTENTS.get(intent, {})
        if language == 'waray':
            response_choices = WARAY_RESPONSES.get(intent, [])
            if not response_choices:
                # If no specific waray response, use the main one (which is likely Tagalog/English)
                # This part can be improved by ensuring all intents have waray versions if needed.
                response_choices = intent_data.get("response", [])
        else:
            response_choices = intent_data.get("response", [])

        response = random.choice(response_choices) if response_choices else ""

        # Append a follow-up question if available and appropriate
        # Only append follow up if we are not in Waray (unless we add Waray follow ups later)
        follow_up_choices = intent_data.get("follow_up", [])
        if follow_up_choices and language != 'waray':
            follow_up = random.choice(follow_up_choices)
            response = f"{response}\n\n{follow_up}"

        # The crisis flag is determined by the intent's priority level.
        # Priority 6 or higher is considered a crisis that needs flagging.
        is_crisis = 1 if INTENT_PRIORITY.get(intent, 0) >= 6 else 0
        
        # If it's a crisis-level intent (like suicidal_thoughts), also send the crisis response.
        # This handles cases where the intent detection catches it instead of the keyword list.
        if is_crisis and intent != "grounding_request": # Don't send crisis text for grounding
             resp = WARAY_CRISIS_RESPONSE if language == 'waray' else CRISIS_RESPONSE
             return (resp, new_intent, 1, is_abusive)

        return (response, new_intent, is_crisis, is_abusive)

    # 5. Generative AI Fallback (Groq → OpenAI → Gemini)
    if not is_abusive:
        # Primary: Groq (Libre, mabilis, Llama 3.1)
        if _groq_available():
            groq_reply = _call_groq_api(user_input, language)
            if groq_reply:
                return (groq_reply, None, 0, is_abusive)

        # Fallback 1: OpenAI (kung may valid key at credits)
        if _openai_available():
            openai_reply = _call_openai_api(user_input, language=language)
            if openai_reply:
                return (openai_reply, None, 0, is_abusive)

        # Fallback 2: Gemini (kung may valid key)
        if _gemini_available():
            gemini_reply = _call_gemini_api(user_input, language)
            if gemini_reply:
                return (gemini_reply, None, 0, is_abusive)

    # 6. Fallback Response if no intent is detected and not abusive
    generic_fallbacks = [
        "Naririnig kita. Nandito lang ako para makinig sa'yo. 💙",
        "I understand. Please tell me more about how you're feeling.",
        "Mahalaga ang nararamdaman mo. Handa akong makinig.",
        "Thank you for sharing. I'm here to support you.",
        "Masaya akong narinig ang iyong kuwento. Nandito ako para sa'yo.",
        "Hindi mo kailangang harapin ang lahat mag-isa. Pwede mo akong kausapin tungkol dito."
    ]
    fallback = WARAY_FALLBACKS if language == 'waray' else generic_fallbacks
    return (random.choice(fallback), new_intent, 0, is_abusive)