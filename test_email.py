"""SendGrid / email self-test.

Gamit:
    python test_email.py you@example.com              # gamitin ang kasalukuyang config
    python test_email.py you@example.com --gmail      # pilitin ang Gmail API (inirerekomenda)
    python test_email.py you@example.com --sendgrid   # pilitin ang SendGrid (HTTP API)
    python test_email.py you@example.com --resend     # pilitin ang Resend (HTTP API)

Ipapakita nito ang EKSAKTONG sagot ng provider (status code + error body),
kaya malalaman mo agad kung:
  * tanggap ang credentials
  * tama/verified ang sender
  * o may iba pang problema

Para sa --gmail, kailangan muna patakbuhin ang:
    python get_gmail_token.py
at nakatakda ang GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN.

HALIMBAWA (Gmail API):
    $env:GMAIL_CLIENT_ID="....apps.googleusercontent.com"
    $env:GMAIL_CLIENT_SECRET="GOCSPX-...."
    $env:GMAIL_REFRESH_TOKEN="1//...."
    $env:GMAIL_SENDER="academicstrugglesupportchatbot@gmail.com"
    python test_email.py caranzaalex02@gmail.com --gmail
"""

import os
import sys

# Windows console (cp1252) ay hindi kayang mag-print ng emoji/unicode —
# i-force sa UTF-8 para hindi mag-crash ang script.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from dotenv import load_dotenv

load_dotenv()

from utils import email_utils  # noqa: E402


def _mask(value):
    if not value:
        return "(wala)"
    if len(value) <= 10:
        return value[:2] + "***"
    return f"{value[:6]}...{value[-4:]}"


def print_config(forced):
    print("=" * 62)
    print(" EMAIL CONFIG CHECK")
    print("=" * 62)
    print(f"  Detected backend : {email_utils.get_email_backend()}")
    print(f"  Forced backend   : {forced or '(hindi naka-force)'}")
    print(f"  EMAIL_SENDER     : {os.environ.get('EMAIL_SENDER') or '(wala)'}")
    print(f"  GMAIL_SENDER     : {os.environ.get('GMAIL_SENDER') or '(wala)'}")
    print(f"  EMAIL_DISPLAY_NAME: {os.environ.get('EMAIL_DISPLAY_NAME', 'Academic Struggle Chatbot')}")
    print(f"  GMAIL_CLIENT_ID  : {_mask(os.environ.get('GMAIL_CLIENT_ID'))}")
    print(f"  GMAIL_CLIENT_SECRET: {_mask(os.environ.get('GMAIL_CLIENT_SECRET'))}")
    print(f"  GMAIL_REFRESH_TOKEN: {_mask(os.environ.get('GMAIL_REFRESH_TOKEN'))}")
    print(f"  SENDGRID_API_KEY : {_mask(os.environ.get('SENDGRID_API_KEY'))}")
    print(f"  RESEND_API_KEY   : {_mask(os.environ.get('RESEND_API_KEY'))}")
    print(f"  EMAIL_PASSWORD   : {'SET' if os.environ.get('EMAIL_PASSWORD') else '(wala)'}")
    print(f"  Running on Render: {email_utils._is_running_on_render()}")
    print("=" * 62)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]

    if not args:
        print(__doc__)
        return 1

    to_email = args[0].strip().lower()
    forced = None
    if "--gmail" in flags:
        forced = "gmail_api"
    elif "--sendgrid" in flags:
        forced = "sendgrid"
    elif "--resend" in flags:
        forced = "resend"

    print_config(forced)

    if forced:
        # I-force ang backend sa pamamagitan ng pag-override ng detector.
        original = email_utils._get_email_backend
        email_utils._get_email_backend = lambda: forced
    else:
        original = None

    subject = "SendGrid / Email Self-Test"
    plain = (
        "Ito ay test message mula sa Academic Struggle Chatbot.\n"
        "Kung nabasa mo ito, gumagana na ang email sending.\n"
    )
    html = "<p>Ito ay <strong>test message</strong> mula sa Academic Struggle Chatbot.</p>"

    print()
    print(f"Nagpapadala ng test email sa {to_email} ...")
    print()

    try:
        # Direkta sa provider function para makita ang tunay na sagot.
        backend = forced or email_utils.get_email_backend()
        if backend == "gmail_api":
            ok = email_utils._send_via_gmail_api(to_email, subject, plain, html)
        elif backend == "sendgrid":
            ok = email_utils._send_via_sendgrid(to_email, subject, plain, html)
        elif backend == "resend":
            ok = email_utils._send_via_resend(to_email, subject, plain, html)
        else:
            ok = email_utils.send_password_reset_email(to_email, reset_code="123456")
    finally:
        if original is not None:
            email_utils._get_email_backend = original

    print()
    print("=" * 62)
    print(f" RESULTA: {'[OK] NAGSEND (tanggap ng provider)' if ok else '[FAIL] BUMAGSAK (tingnan ang error sa itaas)'}")
    print("=" * 62)

    if ok:
        print()
        print("Susunod: tingnan ang inbox AT SPAM folder ng", to_email)
        print("Kapag wala pa rin sa loob ng 2 minuto:")
        print("  * Gmail API: i-check ang 'Sent' folder ng Gmail mo — dapat nandiyan")
        print("    ang email na ipinadala mo, at nasa INBOX ng recipient.")
        print("  * SendGrid/Resend: i-check ang Activity/Deliverability page nila.")
        print()
    else:
        print()
        print("MGA KARANIWANG DAHILAN AT SOLUSYON:")
        print("  [GMAIL API] 400 / 'invalid_grant'")
        print("     -> Hindi na-validate ang refresh token. Maaaring: (a) iba ang Gmail")
        print("        na na-authorize kaysa sa GMAIL_SENDER, o (b) na-revoke/expired na.")
        print("        SOLUSYON: patakbuhin ulit ang  python get_gmail_token.py")
        print("  [GMAIL API] 403 / 'insufficient permission' o 'accessNotConfigured'")
        print("     -> Hindi naka-enable ang Gmail API sa Google Cloud project mo.")
        print("        Pumunta sa APIs & Services -> Library -> hanapin ang")
        print("        'Gmail API' -> Enable.")
        print("  [GMAIL API] kulang ang GMAIL_CLIENT_ID/SECRET/REFRESH_TOKEN")
        print("     -> Patakbuhin ang  python get_gmail_token.py  at ilagay ang")
        print("        tatlong value sa Render -> Environment.")
        print("  [SendGrid] 401 / 'authorization required'")
        print("     -> Mali o kulang ang SENDGRID_API_KEY (nagsisimula sa 'SG.').")
        print("  [SendGrid] 403 / 'from address does not match a verified Sender Identity'")
        print("     -> Hindi pa na-verify ang EMAIL_SENDER sa SendGrid.")
        print("        Settings -> Sender Authentication -> Single Sender Verification.")
        print("        Kaya mas mainam ang GMAIL API — hindi na kailangan ng verification.")
        print()

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
