# Academic Struggle Chatbot — Quick .env & Key Rotation Guide

This repository intentionally does not contain real secrets. Use the `.env` file locally to store API keys and other sensitive values.

Quick steps

- Copy the sanitized example into a local `.env`:

```powershell
copy .env.example .env
notepad .env
```

- Fill in your real secrets in `.env` (do NOT commit `.env` to git).

Best practices

- Never commit API keys, secrets, or tokens. Keep them in `.env` and add `.env` to `.gitignore`.
- Use environment variables in your deployment environment (Render, Heroku, etc.) instead of committing secrets.

Rotating compromised keys (short guide)

1. Gemini / Google API keys
   - Go to Google Cloud Console → APIs & Services → Credentials.
   - Find the key/service account used for Gemini, create a new key, restrict it (HTTP referrers / IPs / APIs), and update your `.env` with the new value.
   - Revoke/delete the old key immediately.

2. OpenAI keys
   - Sign in to https://platform.openai.com/account/api-keys
   - Create a new key, store it in your `.env` as `OPENAI_API_KEY`, then delete the old key.

3. GitHub PAT (if exposed)
   - Revoke the compromised PAT from https://github.com/settings/tokens
   - Create a new PAT and configure your local Git credential manager instead of embedding tokens in URLs.

Commands to commit the sanitized `.env.example` (already done) and verify status:

```powershell
& "C:\Program Files\Git\cmd\git.exe" status
& "C:\Program Files\Git\cmd\git.exe" add .env.example README.md
& "C:\Program Files\Git\cmd\git.exe" commit -m "Add README with .env usage and key-rotation guidance"
& "C:\Program Files\Git\cmd\git.exe" push origin main
```

If you'd like, I can also:

- walk you through rotating each exposed key step-by-step while you perform the actions, or
- add a short `SECURITY.md` with emergency steps to rotate keys and notify collaborators.

— Assistant
