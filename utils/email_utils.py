import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import os
import json
import logging
import urllib.request

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def _get_email_backend():
    # API keys take priority over a stale "smtp" default, because SMTP is
    # blocked on Render and won't work there anyway. Setting SENDGRID_API_KEY
    # (or RESEND_API_KEY) is enough to switch to the HTTP backend.
    if os.environ.get("SENDGRID_API_KEY"):
        return "sendgrid"
    if os.environ.get("RESEND_API_KEY"):
        return "resend"
    backend = os.environ.get("EMAIL_BACKEND", "").strip().lower()
    if backend:
        return backend
    # If SMTP credentials exist, use SMTP by default so password reset works without forcing console mode.
    if os.environ.get("EMAIL_SENDER") and os.environ.get("EMAIL_PASSWORD"):
        return "smtp"
    return "console"

EMAIL_BACKEND = _get_email_backend()


def _send_via_sendgrid(to_email, subject, plain_body, html_body):
    """Send email through the SendGrid Web API v3.

    SendGrid's free tier (100 emails/day) allows "Single Sender
    Verification", which means you can verify a single email address
    (e.g. your Gmail) as the sender WITHOUT owning a domain. This is the
    easiest free option that works from Render (which blocks SMTP).
    """
    api_key = os.environ.get("SENDGRID_API_KEY")
    if not api_key:
        logging.warning("SENDGRID_API_KEY is not set; cannot send via SendGrid.")
        return False

    sender_email = os.environ.get("EMAIL_SENDER")
    if not sender_email:
        logging.warning("EMAIL_SENDER is not set; cannot send via SendGrid.")
        return False

    display_name = os.environ.get("EMAIL_DISPLAY_NAME", "Academic Struggle Chatbot").strip()

    payload = {
        "personalizations": [
            {
                "to": [{"email": to_email}],
                "subject": subject,
            }
        ],
        "from": {"email": sender_email, "name": display_name},
        "reply_to": {"email": sender_email, "name": display_name},
        "content": [
            {"type": "text/plain", "value": plain_body},
            {"type": "text/html", "value": html_body},
        ],
        "mail_settings": {
            "bypass_list_management": {
                "enable": True
            },
        },
        "tracking_settings": {
            "click_tracking": {
                "enable": False,
                "enable_text": False
            },
            "open_tracking": {
                "enable": False
            },
            "subscription_tracking": {
                "enable": False
            }
        },
        "categories": ["transactional", "academic-struggle-chatbot"],
    }

    req = urllib.request.Request(
        "https://api.sendgrid.com/v3/mail/send",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            logging.info("SendGrid email sent to %s (status %s)", to_email, resp.status)
            return True
    except urllib.error.HTTPError as e:
        # SendGrid returns a useful error body on failure.
        try:
            detail = e.read().decode("utf-8")
        except Exception:
            detail = ""
        logging.error("SendGrid API error %s for %s: %s", e.code, to_email, detail)
        return False
    except Exception as e:
        logging.error("Failed to send email via SendGrid to %s: %s", to_email, e)
        return False


def _send_via_resend(to_email, subject, plain_body, html_body):
    """Send email through the Resend HTTP API.

    Render (and many other PaaS providers) block outbound SMTP ports
    (25/465/587), which is why Gmail SMTP fails with
    "Connection unexpectedly closed". Resend exposes a simple HTTPS API
    that works from any environment.
    """
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        logging.warning("RESEND_API_KEY is not set; cannot send via Resend.")
        return False

    sender = os.environ.get("EMAIL_SENDER") or "onboarding@resend.dev"
    display_name = os.environ.get("EMAIL_DISPLAY_NAME", "Academic Struggle Chatbot").strip()
    from_addr = f"{display_name} <{sender}>"

    payload = {
        "from": from_addr,
        "to": [to_email],
        "subject": subject,
        "html": html_body,
        "text": plain_body,
    }

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            logging.info("Resend email sent to %s (status %s)", to_email, resp.status)
            return True
    except Exception as e:
        logging.error("Failed to send email via Resend to %s: %s", to_email, e)
        return False

def _get_email_config():
    """Helper to fetch all email configuration from environment variables."""
    def _safe_int(value, default, name="value"):
        try:
            return int(value) if value else default
        except (ValueError, TypeError):
            logging.warning("Invalid %s value '%s'. Using default %s.", name, value, default)
            return default

    return {
        "sender": os.environ.get("EMAIL_SENDER") or os.environ.get("CRISIS_EMAIL_SENDER"),
        "password": os.environ.get("EMAIL_PASSWORD") or os.environ.get("CRISIS_EMAIL_PASSWORD"),
        "host": os.environ.get("EMAIL_HOST", "smtp.sendgrid.net"),
        "port": _safe_int(os.environ.get("EMAIL_PORT"), 587, "EMAIL_PORT"),
        # Fail fast instead of hanging the request forever when the SMTP server is unreachable.
        "timeout": _safe_int(os.environ.get("EMAIL_TIMEOUT"), 15, "EMAIL_TIMEOUT"),
        "use_tls": os.environ.get("EMAIL_USE_TLS", "true").strip().lower() in ["true", "1", "yes"],
        "use_ssl": os.environ.get("EMAIL_USE_SSL", "false").strip().lower() in ["true", "1", "yes"],
        "user": os.environ.get("EMAIL_HOST_USER") or os.environ.get("EMAIL_SENDER") or os.environ.get("CRISIS_EMAIL_SENDER"),
        "display_name": os.environ.get("EMAIL_DISPLAY_NAME", "Academic Struggle Chatbot").strip(),
        "logo_url": os.environ.get("EMAIL_LOGO_URL", "").strip(),
    }


def _format_sender(config):
    if not config.get("sender"):
        return ""
    display_name = config.get("display_name") or "Academic Struggle Chatbot"
    return f"{display_name} <{config['sender']}>"


def _build_html_message(subject, plain_body, html_body):
    msg = MIMEMultipart("alternative")
    msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    msg["Subject"] = subject
    return msg


def send_crisis_email(username, message):
    config = _get_email_config()
    receiver = os.environ.get("CRISIS_EMAIL_RECEIVER", "guidanceoffice@gmail.com")

    body = f"""
🚨 CRISIS ALERT DETECTED

User: {username}
Message: {message}

Immediate attention required.
    """
    
    if EMAIL_BACKEND == 'console':
        print("\n" + "="*20 + " CONSOLE EMAIL " + "="*20)
        print(f"TO: Crisis Team <{receiver}>")
        print(f"FROM: {config['sender']}")
        print(f"SUBJECT: CRISIS ALERT - Mental Health Chatbot")
        print("-" * 55)
        print(body)
        print("="*55 + "\n")
        return

    if not all([config['sender'], config['password'], receiver]):
        logging.warning("Crisis email not sent. Email credentials are not configured in environment variables.")
        return

    msg = MIMEText(body)
    msg["Subject"] = "CRISIS ALERT - Mental Health Chatbot"
    msg["From"] = config['sender']
    msg["To"] = receiver

    try:
        with smtplib.SMTP(config['host'], config['port'], timeout=config['timeout']) as server:
            server.ehlo()
            if config['use_tls']:
                server.starttls()
                server.ehlo()
            server.login(config['user'], config['password'])
            server.send_message(msg)
    except Exception as e:
        logging.error(f"Failed to send crisis email: {e}")

def send_registration_email(username, user_email):
    """Sends a welcome email to a newly registered user."""
    config = _get_email_config()
    
    formatted_sender = _format_sender(config)
    if EMAIL_BACKEND == 'console':
        print("\n" + "="*20 + " CONSOLE EMAIL " + "="*20)
        print(f"TO: {user_email}")
        print(f"FROM: {formatted_sender}")
        print(f"SUBJECT: Welcome to Academic Struggle Chatbot")
        print("-" * 55)
        print(f"Hi {username},\n\nWelcome! Your account is ready.")
        print("Thank you for joining our Academic Struggle Chatbot. You can now log in and start receiving help with study stress, motivation, and wellbeing.")
        print("="*55 + "\n")
        return True

    # SMTP requires sender + password + user; HTTP backends (SendGrid/Resend)
    # only need their API key + sender, which is checked inside each helper.
    if EMAIL_BACKEND not in ('sendgrid', 'resend') and not all([config['sender'], config['password'], config['user']]):
        logging.warning("Registration email not sent. Email credentials are not configured in environment variables.")
        return False

    plain_body = f"""
Hi {username},

Welcome to Academic Struggle Chatbot!

Your account has been successfully created. You can now log in and start using the chatbot for support with your academic challenges.

We're here to help you navigate the stresses of student life.

Best,
Academic Struggle Chatbot Team
    """

    logo_html = ""
    if config['logo_url']:
        logo_html = f"<div style='margin-bottom:18px;'><img src=\"{config['logo_url']}\" alt=\"Academic Struggle Chatbot\" style=\"max-width:180px;height:auto;display:block;margin:0 auto;\"></div>"

    html_body = f"""\\<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
</head>
<body style="margin:0;padding:0;background-color:#f7f9fc;font-family:'Segoe UI',Arial,Helvetica,sans-serif;">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color:#f7f9fc;">
    <tr>
      <td align="center" style="padding:30px 16px 20px;">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="max-width:560px;background:#ffffff;border-radius:12px;box-shadow:0 4px 16px rgba(0,0,0,0.06);">
          <tr>
            <td style="background:linear-gradient(135deg,#00c6ff,#0072ff);padding:28px 24px;border-radius:12px 12px 0 0;text-align:center;">
              {logo_html}
              <h1 style="margin:6px 0 0;font-size:20px;font-weight:700;color:#ffffff;letter-spacing:-0.2px;">Welcome to Academic Struggle Chatbot!</h1>
            </td>
          </tr>
          <tr>
            <td style="padding:28px 24px 8px;color:#334155;font-size:15px;line-height:1.65;">
              <p style="margin:0 0 14px;">Hi {username},</p>
              <p style="margin:0 0 14px;">Your account has been <strong>successfully created</strong>. You can now log in and start using the chatbot for support with your academic challenges.</p>
              <p style="margin:0 0 14px;">We're here to help you navigate the stresses of student life — whenever you need someone to talk to.</p>
              <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="margin:22px 0 10px;">
                <tr>
                  <td align="center">
                    <a href="https://academic-struggle-support-essu-guiuan.onrender.com/login" target="_blank" style="display:inline-block;background:linear-gradient(135deg,#00c6ff,#0072ff);color:#ffffff;font-size:15px;font-weight:700;text-decoration:none;padding:13px 36px;border-radius:8px;">Log In Now</a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:8px 24px 24px;border-top:1px solid #e9eef3;margin-top:12px;">
              <p style="margin:10px 0 0;font-size:12px;color:#94a3b8;text-align:center;">
                Academic Struggle Support ESSU-Guiuan<br />
                This is an automated message — please do not reply directly.<br />
                Need help? Contact your campus counselor.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

    msg = _build_html_message("Welcome to Academic Struggle Chatbot", plain_body, html_body)
    if EMAIL_BACKEND == 'sendgrid':
        return _send_via_sendgrid(user_email, "Welcome to Academic Struggle Chatbot", plain_body, html_body)
    if EMAIL_BACKEND == 'resend':
        return _send_via_resend(user_email, "Welcome to Academic Struggle Chatbot", plain_body, html_body)
    msg["From"] = formatted_sender
    msg["To"] = user_email

    try:
        if config['use_ssl']:
            with smtplib.SMTP_SSL(config['host'], config['port'], timeout=config['timeout']) as server:
                server.login(config['user'], config['password'])
                server.send_message(msg)
        else:
            with smtplib.SMTP(config['host'], config['port'], timeout=config['timeout']) as server:
                server.ehlo()
                if config['use_tls']:
                    server.starttls()
                    server.ehlo()
                server.login(config['user'], config['password'])
                server.send_message(msg)
        logging.info(f"Registration email sent successfully to {user_email}")
        return True
    except Exception as e:
        logging.error(f"Failed to send registration email to {user_email}: {e}")
        return False

def send_password_reset_email(user_email, reset_code=None, reset_link=None):
    """Sends a password reset email with a 6-digit verification code.
    
    Args:
        user_email: Recipient email address
        reset_code: 6-digit verification code (primary method)
        reset_link: Fallback reset link (backward compatibility)
    """
    config = _get_email_config()

    formatted_sender = _format_sender(config)
    if EMAIL_BACKEND == 'console':
        print("\n" + "="*20 + " CONSOLE EMAIL " + "="*20)
        print(f"TO: {user_email}")
        print(f"FROM: {formatted_sender}")
        print(f"SUBJECT: Your Password Reset Code")
        print("-" * 55)
        if reset_code:
            print("A password reset was requested for your account.")
            print(f"\nYour 6-digit verification code is: >>> {reset_code} <<<")
            print("\nThis code is valid for 30 minutes.")
            print("Go to the verify code page and enter this code to reset your password.")
        elif reset_link:
            print("A password reset was requested for your account.")
            print("Please use the link below to reset your password:")
            print(f"\n>>> {reset_link} <<<\n")
        print("="*55 + "\n")
        return True

    if EMAIL_BACKEND not in ('sendgrid', 'resend') and not all([config['sender'], config['password'], config['user']]):
        logging.warning("Password reset email not sent. Email credentials are not fully configured.")
        return False

    plain_body = f"""
Hi,

A password reset was requested for your account.

Your 6-digit verification code is:

    {reset_code if reset_code else "N/A"}

This code is valid for 30 minutes.
Enter this code on the verification page to reset your password.

If you did not request this, please ignore this email.

Best,
Academic Struggle Chatbot Team
    """

    logo_html = ""
    if config['logo_url']:
        logo_html = f"<div style='margin-bottom:18px;'><img src=\"{config['logo_url']}\" alt=\"Academic Struggle Chatbot\" style=\"max-width:180px;height:auto;display:block;margin:0 auto;\"></div>"

    html_body = f"""\\<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
</head>
<body style="margin:0;padding:0;background-color:#f7f9fc;font-family:'Segoe UI',Arial,Helvetica,sans-serif;">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color:#f7f9fc;">
    <tr>
      <td align="center" style="padding:30px 16px 20px;">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="max-width:560px;background:#ffffff;border-radius:12px;box-shadow:0 4px 16px rgba(0,0,0,0.06);">
          <tr>
            <td style="background:linear-gradient(135deg,#00c6ff,#0072ff);padding:28px 24px;border-radius:12px 12px 0 0;text-align:center;">
              {logo_html}
              <h1 style="margin:6px 0 0;font-size:20px;font-weight:700;color:#ffffff;letter-spacing:-0.2px;">Your Password Reset Code</h1>
            </td>
          </tr>
          <tr>
            <td style="padding:28px 24px 8px;color:#334155;font-size:15px;line-height:1.65;">
              <p style="margin:0 0 14px;">Hi,</p>
              <p style="margin:0 0 14px;">A password reset was requested for your account. Your verification code is valid for <strong>30 minutes</strong>.</p>
              <div style="background:#f0f9ff;border:2px dashed #00c6ff;border-radius:12px;padding:20px;margin:22px 0 10px;text-align:center;">
                <p style="margin:0 0 6px;font-size:13px;color:#64748b;">Your verification code:</p>
                <p style="margin:0;font-size:32px;font-weight:800;letter-spacing:8px;color:#0072ff;font-family:'Courier New',monospace;">{reset_code if reset_code else reset_link}</p>
                <p style="margin:8px 0 0;font-size:12px;color:#94a3b8;">Expires in 30 minutes</p>
              </div>
              <p style="margin:0 0 14px;font-size:13px;color:#64748b;">If you did not request this password reset, please ignore this email or contact support.</p>
            </td>
          </tr>
          <tr>
            <td style="padding:8px 24px 24px;border-top:1px solid #e9eef3;margin-top:12px;">
              <p style="margin:10px 0 0;font-size:12px;color:#94a3b8;text-align:center;">
                Academic Struggle Support ESSU-Guiuan<br />
                This is an automated message — please do not reply directly.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

    msg = _build_html_message("Reset Your Password", plain_body, html_body)
    if EMAIL_BACKEND == 'sendgrid':
        return _send_via_sendgrid(user_email, "Reset Your Password", plain_body, html_body)
    if EMAIL_BACKEND == 'resend':
        return _send_via_resend(user_email, "Reset Your Password", plain_body, html_body)
    msg["From"] = formatted_sender
    msg["To"] = user_email

    try:
        if config['use_ssl']:
            with smtplib.SMTP_SSL(config['host'], config['port'], timeout=config['timeout']) as server:
                server.login(config['user'], config['password'])
                server.send_message(msg)
        else:
            with smtplib.SMTP(config['host'], config['port'], timeout=config['timeout']) as server:
                server.ehlo()
                if config['use_tls']:
                    server.starttls()
                    server.ehlo()
                server.login(config['user'], config['password'])
                server.send_message(msg)

        logging.info(f"Password reset email sent successfully to {user_email}")
        return True
    except Exception as e:
        logging.error(f"Failed to send password reset email to {user_email}: {e}")
        return False