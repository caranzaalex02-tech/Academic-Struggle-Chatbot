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

import json
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def env(name: str, default: str = "") -> str:
    # Minimal .env reader — walang dotenv dependency.
    # Checks the script's own folder, then the repo root (in case the script
    # lives in scripts/ and .env sits at the project root).
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
    ]
    for path in candidates:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line.startswith(name + "="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get(name, default)

GROQ_API_KEY = env("GROQ_API_KEY")
if not GROQ_API_KEY:
    print("ERROR: set GROQ_API_KEY in .env (or export GROQ_API_KEY) first.")
    sys.exit(1)

URL = "https://api.groq.com/openai/v1/chat/completions"


def main() -> int:
    key = GROQ_API_KEY
    model = os.environ.get("GROQ_MODEL", "qwen/qwen3.8-27b")
    if not key:
        print("ERROR: set GROQ_API_KEY in .env (or export GROQ_API_KEY) first.")
        return 1

    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "Say this once: quota probe ok."}],
        "max_tokens": 4,
    }).encode("utf-8")

    req = urllib.request.Request(
        URL,
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/124.0 Safari/537.36",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            status = resp.status
            headers = {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as e:
        status = e.code
        headers = {k.lower(): v for k, v in e.headers.items()}
        print(f"HTTP {status} error")
        print((e.read()[:300].decode("utf-8", "replace")))
    except Exception as e:  # noqa: BLE001
        print(f"NETWORK ERROR: {type(e).__name__}: {e}")
        return 1

    print(f"HTTP status: {status}")
    print(f"model: {model}")

    if status == 200:
        print("\n--- rate limit headers (OK) ---")
        for key in (
            "x-ratelimit-limit-requests",
            "x-ratelimit-limit-tokens",
            "x-ratelimit-remaining-requests",
            "x-ratelimit-remaining-tokens",
            "x-ratelimit-reset-requests",
            "x-ratelimit-reset-tokens",
        ):
            print(f"{key}: {headers.get(key)}")
        return 0

    print("\n--- rate limit headers (if any) ---")
    for name, value in sorted(headers.items()):
        if "ratelimit" in name:
            print(f"{name}: {value}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
