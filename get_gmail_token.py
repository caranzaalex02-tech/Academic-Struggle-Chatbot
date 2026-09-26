"""Gmail API token setup — patakbuhin ito ISANG BESES sa laptop mo.

Ito ang kukuha ng GMAIL_REFRESH_TOKEN na gagamitin ng Render para makapagpadala
ng email gamit ang TUNAY mong Gmail account. Dahil tunay na Gmail ang
nagpapadala, HINDI napupunta sa spam ang mga email, at dahil HTTPS (port 443)
ang ginagamit, HINDI ito blocked sa Render free tier.

=====================================================================
HAKBANG 1: Gumawa ng OAuth client sa Google Cloud Console
=====================================================================
1. Pumunta sa  https://console.cloud.google.com/
2. Gumawa ng bagong project (taas-kaliwa na dropdown -> "New Project")
   Pangalan halimbawa: "Academic Struggle Chatbot"
3. Sa kaliwa: "APIs & Services" -> "Library"
   Hanapin ang  "Gmail API"  -> click  ->  "Enable"
4. Sa kaliwa: "APIs & Services" -> "OAuth consent screen"
   * User Type:  External   -> click "Create"
   * App name:  Academic Struggle Chatbot
   * User support email:  piliin ang Gmail mo
   * Developer contact email:  ilagay ang Gmail mo
   * Save and Continue
   * Scopes:  i-skip lang (Save and Continue)
   * Test users:  click "Add Users" -> ilagay ang Gmail mo -> Save
   * Save and Continue  ->  Back to Dashboard
5. Sa kaliwa: "APIs & Services" -> "Credentials"
   * click  "Create Credentials"  ->  "OAuth client ID"
   * Application type:  **Desktop app**
   * Name:  "Academic Struggle Chatbot Desktop"
   * click "Create"
   * KOPYAHIN ang  Client ID  at  Client secret

=====================================================================
HAKBANG 2: Patakbuhin ang script na ito
=====================================================================
    python get_gmail_token.py

Ilalagay mo ang Client ID at Client secret kapag tinanong. Mag-bubukas ang
browser — i-login ang Gmail account na gagamitin (hal.
academicstrugglesupportchatbot@gmail.com), tapos i-click ang "Continue/Allow".

Kung may lalabas na "Google hasn't verified this app":
    click "Advanced"  ->  "Go to <app name> (unsafe)"
Normal lang yan — sarili mong app naman ito.

=====================================================================
HAKBANG 3: Ilagay ang resulta sa Render
=====================================================================
Ipapakita ng script ang 4 na value. Ilagay lahat sa:
Render -> service mo -> Environment -> Add Environment Variable

    GMAIL_CLIENT_ID       = (mula sa script)
    GMAIL_CLIENT_SECRET   = (mula sa script)
    GMAIL_REFRESH_TOKEN   = (mula sa script)
    GMAIL_SENDER          = academicstrugglesupportchatbot@gmail.com

Tapos: Save Changes -> Manual Deploy -> Deploy latest commit.

I-verify: buksan ang  https://<app-mo>.onrender.com/health/email
Dapat may  "backend": "gmail_api"  at  "gmail_api_ready": true.

O kaya sa laptop muna:
    python test_email.py caranzaalex02@gmail.com --gmail
"""

import http.server
import json
import os
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "openid",
    "email",
]
REDIRECT_PORT = 8080
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/"


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Salo ang redirect mula sa Google at kunin ang `code`."""

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if parsed.path in ("/favicon.ico", "/robots.txt"):
            self.send_response(204)
            self.end_headers()
            return

        self.server.auth_code = params.get("code", [None])[0]
        self.server.auth_error = params.get("error", [None])[0]

        if self.server.auth_code:
            headline = "Tapos na! Puwede mo nang isara ang tab na ito."
            detail = "Bumalik ka sa terminal para makita ang refresh token."
        else:
            headline = "Hindi natuloy ang authorization."
            detail = f"Error: {self.server.auth_error or 'walang code na natanggap'}"

        body = (
            "<html><head><meta charset='utf-8'><title>Gmail Setup</title></head>"
            "<body style=\"font-family:Segoe UI,Arial,sans-serif;padding:40px;"
            "max-width:640px;margin:auto;background:#f7f9fc;color:#334155;\">"
            f"<h2 style='color:#0072ff;'>{headline}</h2>"
            f"<p>{detail}</p>"
            "</body></html>"
        ).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # tahimik — huwag mag-print ng access logs


def _ask(prompt, env_name=None):
    """Hingin ang value, o gamitin ang environment variable kung meron na."""
    if env_name:
        existing = os.environ.get(env_name)
        if existing:
            print(f"  {env_name} = (galing sa environment, ito ang gagamitin)")
            return existing.strip()
    print(f"  {prompt}")
    return input("  > ").strip()


def _post_form(url, fields, timeout=30):
    """POST application/x-www-form-urlencoded, ibalik ang (data, error_text)."""
    payload = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")
        except Exception:
            pass
        return None, f"HTTP {e.code}: {detail}"
    except Exception as e:
        return None, str(e)


def _get_authorized_email(access_token):
    """Alamin kung aling Gmail account ang na-authorize (iwas pagkakamali)."""
    if not access_token:
        return ""
    try:
        req = urllib.request.Request(
            USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8")).get("email", "")
    except Exception:
        return ""


def _save_env_file(client_id, client_secret, refresh_token, sender):
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gmail_env.txt")
    try:
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write("# Gmail API credentials — ILAGAY SA RENDER ENVIRONMENT\n")
            fh.write("# HUWAG i-commit ang file na ito sa GitHub!\n")
            fh.write(f"GMAIL_CLIENT_ID={client_id}\n")
            fh.write(f"GMAIL_CLIENT_SECRET={client_secret}\n")
            fh.write(f"GMAIL_REFRESH_TOKEN={refresh_token}\n")
            fh.write(f"GMAIL_SENDER={sender}\n")
        print(f"Naka-save din sa file: {out_path}")
        print("(Bukasan mo na lang yan para kopyahin papuntang Render.)")
    except Exception as e:
        print(f"(Hindi na-save sa file: {e} — kopyahin na lang mula sa itaas.)")


def main():
    print("=" * 66)
    print(" GMAIL API TOKEN SETUP")
    print("=" * 66)
    print()
    print("Sundin muna ang HAKBANG 1 sa taas ng file na ito bago magpatuloy.")
    print()

    client_id = _ask(
        "GMAIL_CLIENT_ID (nagsisimula sa ...apps.googleusercontent.com)",
        env_name="GMAIL_CLIENT_ID",
    )
    client_secret = _ask(
        "GMAIL_CLIENT_SECRET (nagsisimula sa GOCSPX-)",
        env_name="GMAIL_CLIENT_SECRET",
    )
    sender = _ask(
        "GMAIL_SENDER (ang Gmail address na i-a-authorize, hal. "
        "academicstrugglesupportchatbot@gmail.com)",
        env_name="GMAIL_SENDER",
    )

    if not client_id or not client_secret or not sender:
        print("\n[FAIL] Kailangan lahat ng tatlong value. Subukan ulit.")
        return 1

    print()
    print(f"Naghihintay ng authorization sa port {REDIRECT_PORT} ...")
    print()

    try:
        server = http.server.HTTPServer(("localhost", REDIRECT_PORT), _CallbackHandler)
    except OSError as e:
        print(f"[FAIL] Hindi ma-buksan ang port {REDIRECT_PORT}: {e}")
        print("Maaaring may ibang program na gumagamit nito. Isara ito at subukan ulit.")
        return 1

    server.auth_code = None
    server.auth_error = None

    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",  # kailangan para laging may refresh_token
        "login_hint": sender,
    }
    auth_link = AUTH_URL + "?" + urllib.parse.urlencode(params)

    print("Bukas na ang browser mo. Kung hindi bumukas, kopyahin ito:")
    print()
    print(auth_link)
    print()
    try:
        webbrowser.open(auth_link)
    except Exception:
        pass

    thread.join(timeout=300)  # 5 minutong hintay

    if not server.auth_code:
        server.server_close()
        print()
        print("[FAIL] Walang natanggap na authorization code.")
        print("Dahilan:", server.auth_error or "nag-timeout o hindi natapos ang login")
        print()
        print("Mga dapat i-check:")
        print("  * Naka-open ba ang browser at natapos mo ang login + 'Allow'?")
        print("  * Desktop app ba ang OAuth client type mo? (hindi Web application)")
        print("     -> Kung Web application, kailangang idagdag ang")
        print(f"        {REDIRECT_URI}")
        print("        sa 'Authorized redirect URIs' ng client mo.")
        print("  * Na-enable ba ang Gmail API sa project?")
        print("  * Naka-add ba ang Gmail mo sa 'Test users' ng OAuth consent screen?")
        return 1

    server.server_close()
    print("Nakuha ang code. Kinukuha ang refresh token ...")

    tokens, error = _post_form(TOKEN_URL, {
        "code": server.auth_code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    })

    if error:
        print(f"\n[FAIL] Token exchange failed: {error}")
        return 1

    refresh_token = tokens.get("refresh_token")
    access_token = tokens.get("access_token")

    if not refresh_token:
        print()
        print("[FAIL] Walang refresh_token sa sagot ng Google.")
        print("Nangyayari ito kapag na-authorize na dati ang app.")
        print("SOLUSYON: pumunta sa https://myaccount.google.com/permissions")
        print("  -> hanapin ang app mo -> click 'Remove Access' -> patakbuhin ulit ito.")
        return 1

    authorized_email = _get_authorized_email(access_token)

    print()
    print("=" * 66)
    print(" [OK] TAPOS NA — ito ang mga value para sa Render")
    print("=" * 66)
    print()
    if authorized_email:
        print(f"  Na-authorize na Gmail account: {authorized_email}")
        if authorized_email.lower() != sender.lower():
            print()
            print("  [!] BABALA: Iba ang na-authorize kaysa sa GMAIL_SENDER mo!")
            print(f"      Na-authorize : {authorized_email}")
            print(f"      GMAIL_SENDER : {sender}")
            print("      Dapat PAREHO ito. Kung hindi, patakbuhin ulit at piliin")
            print("      ang tamang account sa browser.")
        print()

    print("Ilagay lahat ng ito sa Render -> service mo -> Environment:")
    print()
    print(f"  GMAIL_CLIENT_ID       = {client_id}")
    print(f"  GMAIL_CLIENT_SECRET   = {client_secret}")
    print(f"  GMAIL_REFRESH_TOKEN   = {refresh_token}")
    print(f"  GMAIL_SENDER          = {authorized_email or sender}")
    print()
    print("Pagkatapos: Save Changes -> Manual Deploy -> Deploy latest commit.")
    print()

    _save_env_file(client_id, client_secret, refresh_token, authorized_email or sender)

    print()
    print("SUSUNOD NA HAKBANG (pagkatapos ma-deploy sa Render):")
    print("  1. Buksan ang  <app-mo>.onrender.com/health/email")
    print('     Dapat: "backend": "gmail_api", "gmail_api_ready": true')
    print("  2. I-test: Forgot Password gamit ang caranzaalex02@gmail.com")
    print("  3. I-check ang Inbox AT Spam. Dapat nasa INBOX na ito ngayon.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

