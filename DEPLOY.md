# Deploying to Render (quick guide)

This project includes a `Procfile` and `runtime.txt` for Render / Heroku-style deployments.

Prerequisites

- A Render account (https://render.com) or other host that supports Git deployments.
- Repository pushed to GitHub (`origin/main`).

Steps to create a Render Web Service

1. In Render dashboard, click **New** → **Web Service**.
2. Connect to GitHub and select the `Academic-Struggle-Chatbot` repository.
3. Branch: `main`.
4. Build Command: leave blank or set to `pip install -r requirements.txt`.
5. Start Command: use the `Procfile` (Render auto-detects) or set to `gunicorn run:app --bind 0.0.0.0:$PORT` if using Gunicorn.

Environment variables (set under Service → Environment):

- `FLASK_SECRET_KEY` = (your secret)
- `GEMINI_API_KEY` = (your new Gemini key)
- `OPENAI_API_KEY` = (your OpenAI key)
- `DATABASE_URL` = (Postgres URL if using remote DB)

Notes

- Do not store secret keys in the repository. Use Render's environment settings.
- For a lightweight Python server use `gunicorn` or Render's default; if using `waitress`, ensure your Procfile references `waitress-serve --port $PORT run:app`.

Rollback and logs

- Use Render dashboard to view service logs and restart the service.
- Use `git` to push changes; Render will redeploy on new commits to the branch.
