"""Live quota probe for the Groq API key in .env.
Prints the live Groq rate-limit headers (and any HTTP error) so you can
verify the free/developer plan limits at runtime.

Usage:
    venv\\Scripts\\python.exe scripts/quota_check.py

Expected free/developer plan (qwen/qwen3.8-27b) headers as of Q4 2025/2026:
    x-ratelimit-limit-requests: 1000   <- Requests Per Day (RPD)
    x-ratelimit-limit-tokens:   8000    <- Tokens Per Minute (TPM)
    x-ratelimit-remaining-requests: <requests left today>
    x-ratelimit-remaining-tokens: <tokens left in this minute window>
    x-ratelimit-reset-requests: ~<time to midnight UTC>
    x-ratelimit-reset-tokens:   ~<time to next minute>

Notes:
    - x-ratelimit-reset-requests counts down to the RPD daily cap reset.
    - x-ratelimit-reset-tokens counts down to the next 60-second token window.
    - Hitting these returns HTTP 429 (Too Many Requests).
"""
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
if not GROQ_API_KEY:
    print("ERROR: set GROQ_API_KEY in .env (or export GROQ_API_KEY) first.")
    sys.exit(1)

URL = "https://api.groq.com/openai/v1/chat/completions"
HEADERS = {
    "Authorization": f"Bearer {GROQ_API_KEY}",
    "Content-Type": "application/json",
}
PAYLOAD = {
    "model": os.environ.get("GROQ_MODEL", "qwen/qwen3.8-27b"),
    "messages": [{"role": "user", "content": "Say this once: quota probe ok."}],
    "max_tokens": 4,
}


def main() -> int:
    try:
        resp = requests.post(URL, headers=HEADERS, json=PAYLOAD, timeout=60)
    except requests.RequestException as exc:
        print(f"NETWORK ERROR: {exc}")
        return 1

    print(f"HTTP status: {resp.status_code}")
    print(f"model: {PAYLOAD['model']}")

    rate = resp.headers
    if resp.status_code == 200:
        print("\n--- rate limit headers (OK) ---")
        for key in (
            "x-ratelimit-limit-requests",
            "x-ratelimit-limit-tokens",
            "x-ratelimit-remaining-requests",
            "x-ratelimit-remaining-tokens",
            "x-ratelimit-reset-requests",
            "x-ratelimit-reset-tokens",
        ):
            print(f"{key}: {rate.get(key)}")
        return 0

    print("\n--- error body (first 500 chars) ---")
    print(resp.text[:500])
    print("\n--- rate limit headers (if any) ---")
    for key, value in rate.items():
        if "ratelimit" in key.lower():
            print(f"{key}: {value}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
