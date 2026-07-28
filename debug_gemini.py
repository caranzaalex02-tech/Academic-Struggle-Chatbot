import os
import google.generativeai as genai
from dotenv import load_dotenv

# --- SETUP ---
# 1. Make sure you have run `pip install google-generativeai python-dotenv`
# 2. Ensure your .env file has GEMINI_API_KEY="YOUR_KEY_HERE"

print("--- Gemini API Debugger ---")

# 1. Load environment variables from .env file
load_dotenv()

# 2. Get the API Key
api_key = os.getenv("GEMINI_API_KEY")

# 3. Print diagnostic information
if not api_key:
    print("❌ ERROR: GEMINI_API_KEY not found in .env file or environment variables.")
    print("Please make sure your .env file is in the same directory and contains the key.")
else:
    print(f"✅ Key Found. Length: {len(api_key)}. Ends with: '...{api_key[-4:]}'")

    # 4. Attempt a simple API call
    try:
        print("\nAttempting to configure API key...")
        genai.configure(api_key=api_key)
        print("Attempting to create a model...")
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        print("Attempting to generate content...")
        response = model.generate_content("This is a test. Say 'hello'.")
        print(f"\n✅ SUCCESS! API call successful. Gemini says: '{response.text.strip()}'")
    except Exception as e:
        print(f"\n❌ FAILED: API call failed. Error: {type(e).__name__} - {e}")
        print("\nTROUBLESHOOTING:")
        print("1. Double-check if you copied the ENTIRE API key correctly.")
        print("2. Ensure the 'Generative Language API' or 'Gemini API' is ENABLED in your Google Cloud project.")
        print("3. Make sure billing is enabled for your Google Cloud project (required by Google).")