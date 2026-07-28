# Security & Incident Response

If sensitive data or keys are exposed in this repository, follow these steps immediately:

1. Revoke the compromised keys/tokens immediately:
   - Gemini / Google API keys: Google Cloud Console → APIs & Services → Credentials → Delete key.
   - OpenAI keys: https://platform.openai.com/account/api-keys → Delete exposed key.
   - GitHub PATs: https://github.com/settings/tokens → Revoke token.

2. Rotate keys and update environments:
   - Generate new keys in provider consoles.
   - Update your local `.env` (never commit `.env`) and update deployment environment variables (Render, Heroku, etc.).

3. Replace secrets in logs and other systems if leaked.

4. Communicate with collaborators:
   - Inform any team members and require them to rotate any shared credentials.
   - Force a re-clone of the repository after a forced push that rewrites history.

5. If GitHub push protection blocked a push, follow GitHub guidance and unblock/allow if appropriate after removing secrets.

Contact: repository owner or security lead.
