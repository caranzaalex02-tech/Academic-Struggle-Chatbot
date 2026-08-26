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
    backend = os.environ.get("EMAIL_BACKEND", "").strip().lower()
    if backend:
        return backend
    # Prefer the Resend HTTP API when a key is present (works on Render,
    # which blocks direct SMTP connections).
    if os.environ.get("RESEND_API_KEY"):
        return "resend"
    # If SMTP credentials exist, use SMTP by default so password reset works without forcing console mode.
    if os.environ.get("EMAIL_SENDER") and os.environ.get("EMAIL_PASSWORD"):
        return "smtp"
    return "console"

EMAIL_BACKEND = _get_email_backend()


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

    if not all([config['sender'], config['password'], config['user']]):
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

    html_body = f"""
<html>
  <body style=\"font-family:Arial, sans-serif; color:#111; line-height:1.6;\">
    {logo_html}
    <p>Hi {username},</p>
    <p>Welcome to <strong>Academic Struggle Chatbot</strong>!</p>
    <p>Your account has been successfully created. You can now log in and start using the chatbot for support with your academic challenges.</p>
    <p>We're here to help you navigate the stresses of student life.</p>
    <p>Best,<br><strong>Academic Struggle Chatbot Team</strong></p>
  </body>
</html>
"""

    msg = _build_html_message("Welcome to Academic Struggle Chatbot", plain_body, html_body)
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

def send_password_reset_email(user_email, reset_link):
    """Sends a password reset email to the user."""
    config = _get_email_config()

    formatted_sender = _format_sender(config)
    if EMAIL_BACKEND == 'console':
        print("\n" + "="*20 + " CONSOLE EMAIL " + "="*20)
        print(f"TO: {user_email}")
        print(f"FROM: {formatted_sender}")
        print(f"SUBJECT: Reset Your Password")
        print("-" * 55)
        print("A password reset was requested for your account.")
        print("Please use the link below to reset your password:")
        print(f"\n>>> {reset_link} <<<\n")
        print("="*55 + "\n")
        return True

    if not all([config['sender'], config['password'], config['user']]):
        logging.warning("Password reset email not sent. Email credentials are not fully configured.")
        return False

    plain_body = f"""
Hi,

A password reset was requested for your account.

Please click the link below to reset your password. This link is valid for 1 hour.
{reset_link}

If you did not request this, please ignore this email.

Best,
Academic Struggle Chatbot Team
    """

    logo_html = ""
    if config['logo_url']:
        logo_html = f"<div style='margin-bottom:18px;'><img src=\"{config['logo_url']}\" alt=\"Academic Struggle Chatbot\" style=\"max-width:180px;height:auto;display:block;margin:0 auto;\"></div>"

    html_body = f"""
<html>
  <body style=\"font-family:Arial, sans-serif; color:#111; line-height:1.6;\">
    {logo_html}
    <p>Hi,</p>
    <p>A password reset was requested for your account.</p>
    <p>Please click the link below to reset your password. This link is valid for 1 hour.</p>
    <p><a href=\"{reset_link}\" style=\"color:#1a73e8;\">Reset your password</a></p>
    <p>If you did not request this, please ignore this email.</p>
    <p>Best,<br><strong>Academic Struggle Chatbot Team</strong></p>
  </body>
</html>
"""

    msg = _build_html_message("Reset Your Password", plain_body, html_body)
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