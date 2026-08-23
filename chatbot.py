"""
Standalone Chatbot Runner
=========================
This script provides a command-line interface to test the chatbot's
response logic without needing to run the full Flask web server.

Usage:
    python chatbot.py

The script loads API keys from the .env file and uses the same
bot_logic.generate_response() function that powers the web app.
"""

import os
import sys

# Ensure the project root is on the path so imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("[WARNING] python-dotenv not installed. API keys may not load.")
    print("          Install with: pip install python-dotenv")

from utils.bot_logic import generate_response


def check_api_keys():
    """Print the status of configured API keys."""
    print("=" * 50)
    print("API KEY STATUS")
    print("=" * 50)

    groq_key = os.environ.get("GROQ_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")

    if groq_key:
        preview = f"{groq_key[:5]}...{groq_key[-4:]}" if len(groq_key) > 9 else "INVALID"
        print(f"  Groq API Key   : SET ({preview})")
        groq_model = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")
        print(f"  Groq Model     : {groq_model}")
    else:
        print("  Groq API Key   : NOT SET (set GROQ_API_KEY in .env)")

    if gemini_key:
        preview = f"{gemini_key[:5]}...{gemini_key[-4:]}" if len(gemini_key) > 9 else "INVALID"
        print(f"  Gemini API Key : SET ({preview})")
    else:
        print("  Gemini API Key : NOT SET (set GEMINI_API_KEY in .env)")

    if openai_key:
        preview = f"{openai_key[:7]}...{openai_key[-4:]}" if len(openai_key) > 11 else "INVALID"
        print(f"  OpenAI API Key : SET ({preview})")
    else:
        print("  OpenAI API Key : NOT SET (set OPENAI_API_KEY in .env)")

    model = os.environ.get("MENTALHEALTHWEB_OPENAI_MODEL", "gpt-3.5-turbo")
    print(f"  OpenAI Model   : {model}")
    print("=" * 50)
    print()


def main():
    print()
    print("╔══════════════════════════════════════════════╗")
    print("║   Academic Struggle Support Chatbot (CLI)    ║")
    print("╚══════════════════════════════════════════════╝")
    print()
    print("Type your message and press Enter. The chatbot")
    print("will respond using the same logic as the web app.")
    print()
    print("Commands:")
    print("  /lang tagalog  - Switch to Tagalog mode")
    print("  /lang waray    - Switch to Waray mode")
    print("  /keys          - Show API key status")
    print("  /quit or /exit - Exit the chatbot")
    print()

    check_api_keys()

    language = "tagalog"
    last_intent = None

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nSalamat sa paggamit! Ingat ka palagi. 🤍")
            break

        if not user_input:
            continue

        # Handle commands
        if user_input.lower() in ("/quit", "/exit"):
            print("Bot: Salamat sa paggamit! Ingat ka palagi. 🤍")
            break
        elif user_input.lower() == "/keys":
            check_api_keys()
            continue
        elif user_input.lower().startswith("/lang"):
            parts = user_input.split()
            if len(parts) >= 2 and parts[1] in ("tagalog", "waray"):
                language = parts[1]
                print(f"Bot: Language set to '{language}'.")
            else:
                print("Bot: Usage: /lang tagalog or /lang waray")
            continue

        # Generate response using the same logic as the web app
        reply, new_intent, is_crisis, is_abusive = generate_response(
            user_input, last_intent, language
        )

        if new_intent:
            last_intent = new_intent

        # Add flags for debugging
        flags = []
        if is_crisis:
            flags.append("🚨 CRISIS")
        if is_abusive:
            flags.append("⚠️ ABUSIVE")
        flag_str = f" [{' | '.join(flags)}]" if flags else ""

        print(f"Bot{flag_str}: {reply}")
        print()


if __name__ == "__main__":
    main()