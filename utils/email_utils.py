import smtplib
from email.mime.text import MIMEText
import os
import logging

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "console")

def _get_email_config():
    """Helper to fetch all email configuration from environment variables."""
    # Use general EMAIL_SENDER/PASSWORD, but fall back to CRISIS_ ones if not present.
    return {
        "sender": os.environ.get("EMAIL_SENDER") or os.environ.get("CRISIS_EMAIL_SENDER"),
        "password": os.environ.get("EMAIL_PASSWORD") or os.environ.get("CRISIS_EMAIL_PASSWORD"),
        "host": os.environ.get("EMAIL_HOST", "smtp.sendgrid.net"),
        "port": int(os.environ.get("EMAIL_PORT", 587)),
        # For Gmail, user is the same as the sender email.
        "user": os.environ.get("EMAIL_HOST_USER") or os.environ.get("EMAIL_SENDER") or os.environ.get("CRISIS_EMAIL_SENDER"),
    }

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
        with smtplib.SMTP(config['host'], config['port']) as server:
            server.starttls()
            server.login(config['user'], config['password'])
            server.send_message(msg)
    except Exception as e:
        logging.error(f"Failed to send crisis email: {e}")

def send_registration_email(username, user_email):
    """Sends a welcome email to a newly registered user."""
    config = _get_email_config()
    
    if EMAIL_BACKEND == 'console':
        print("\n" + "="*20 + " CONSOLE EMAIL " + "="*20)
        print(f"TO: {user_email}")
        print(f"FROM: {config.get('sender')}")
        print(f"SUBJECT: Welcome to Student Support Chatbot!")
        print("-" * 55)
        print(f"Hi {username},\n\nWelcome! Your account is ready.")
        print("="*55 + "\n")
        return

    if not all([config['sender'], config['password']]):
        logging.warning("Registration email not sent. Email credentials are not configured in environment variables.")
        return

    body = f"""
Hi {username},

Welcome to the Student Support Chatbot!

Your account has been successfully created. You can now log in and start using the chatbot for support with your academic challenges.

We're here to help you navigate the stresses of student life.

Best,
The Student Support Team
    """
    
    msg = MIMEText(body)
    msg["Subject"] = "Welcome to the Student Support Chatbot!"
    msg["From"] = config['sender']
    msg["To"] = user_email

    try:
        with smtplib.SMTP(config['host'], config['port']) as server:
            server.starttls()
            server.login(config['user'], config['password'])
            server.send_message(msg)
            logging.info(f"Registration email sent successfully to {user_email}")
    except Exception as e:
        logging.error(f"Failed to send registration email to {user_email}: {e}")

def send_password_reset_email(user_email, reset_link):
    """Sends a password reset email to the user."""
    config = _get_email_config()

    if EMAIL_BACKEND == 'console':
        print("\n" + "="*20 + " CONSOLE EMAIL " + "="*20)
        print(f"TO: {user_email}")
        print(f"FROM: {config['sender']}")
        print(f"SUBJECT: Reset Your Password")
        print("-" * 55)
        print("A password reset was requested for your account.")
        print("Please use the link below to reset your password:")
        print(f"\n>>> {reset_link} <<<\n")
        print("="*55 + "\n")
        return True

    if not all([config['sender'], config['password']]):
        logging.warning("Password reset email not sent. Email credentials are not configured.")
        return False

    body = f"""
Hi,

A password reset was requested for your account.

Please click the link below to reset your password. This link is valid for 1 hour.
{reset_link}

If you did not request this, please ignore this email.

Best,
The Student Support Team
    """
    msg = MIMEText(body)
    msg["Subject"] = "Reset Your Password"
    msg["From"] = config['sender']
    msg["To"] = user_email

    try:
        with smtplib.SMTP(config['host'], config['port']) as server:
            server.starttls()
            server.login(config['user'], config['password'])
            server.send_message(msg)
            logging.info(f"Password reset email sent successfully to {user_email}")
            return True
    except Exception as e:
        logging.error(f"Failed to send password reset email to {user_email}: {e}")
        return False