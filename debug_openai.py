from dotenv import load_dotenv
import os
import openai

load_dotenv()
print('got env key', bool(os.getenv('OPENAI_API_KEY')))
print('key len', len(os.getenv('OPENAI_API_KEY') or ''))
print('openai module file:', openai.__file__)
print('openai version:', getattr(openai, '__version__', 'unknown'))
print('has openai.OpenAI:', hasattr(openai, 'OpenAI'))
print('has openai.ChatCompletion:', hasattr(openai, 'ChatCompletion'))
try:
    from openai import OpenAI as OpenAIClient
    print('OpenAIClient imported', OpenAIClient)
except Exception as e:
    print('OpenAIClient import failed', type(e).__name__, e)
try:
    client = openai.OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
    print('client created', client)
except Exception as e:
    print('openai.OpenAI client creation failed', type(e).__name__, e)

# --- Test API Call ---
print("\n--- Attempting a test API call to list models ---")
try:
    models = client.models.list()
    print("✅ SUCCESS: API call successful. Your key and quota are active.")
except Exception as e:
    print(f"❌ FAILED: API call failed. Error: {type(e).__name__} - {e}")
    print("This likely confirms a billing/quota issue. Please check your OpenAI dashboard.")
