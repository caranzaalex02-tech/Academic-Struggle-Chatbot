# Python Standard Library
import base64
import os
import re
import sqlite3
import urllib.parse
from datetime import datetime, timedelta, timezone
from threading import Timer

# Third-Party Libraries
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, g, flash, make_response
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadTimeSignature, BadSignature
from werkzeug.utils import secure_filename
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

try:
    import psycopg2
    from psycopg2.extras import DictCursor
    import openai
    from dotenv import load_dotenv
except ImportError:
    psycopg2 = None
    DictCursor = None
    openai = None
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

# Local Application Imports
from utils.bot_logic import generate_response
from utils.email_utils import send_crisis_email, send_registration_email, send_password_reset_email, EMAIL_BACKEND

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or os.environ.get("SECRET_KEY") or "dev-secret-key-change-in-production"
if os.environ.get("FLASK_SECRET_KEY") is None and os.environ.get("SECRET_KEY") is None:
    app.logger.warning("FLASK_SECRET_KEY is not set; using a temporary fallback secret.")
DATABASE = os.environ.get("MENTALHEALTHWEB_DB", "database.db")
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- Rate Limiting Setup ---
# Use Redis in production if REDIS_URL is set, otherwise fall back to in-memory storage.
redis_url = os.environ.get("REDIS_URL")
storage_uri = redis_url if redis_url else "memory://"
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri=storage_uri,
)
if redis_url:
    app.logger.info("Flask-Limiter is using Redis for rate limiting.")

# For password reset tokens
s = URLSafeTimedSerializer(app.secret_key)


def hash_password(password):
    """Hash a password using pbkdf2:sha256.

    Werkzeug 3.x defaults to scrypt, which is memory-intensive enough to
    trigger an out-of-memory kill (SIGKILL) on small Render/Heroku dynos
    (~512 MB), causing "internal server error" during registration.
    pbkdf2:sha256 is still secure and uses far less memory.
    check_password_hash() auto-detects the hashing method, so previously
    stored scrypt hashes keep working.
    """
    return generate_password_hash(password, method="pbkdf2:sha256")

typing_users = {}

# --- Security Headers ---
@app.after_request
def add_security_headers(response):
    # Prevents clickjacking
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    # Prevents MIME-type sniffing
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


# --- Global error handlers ---
@app.errorhandler(500)
def internal_error(e):
    """Log the full traceback and show a friendly message instead of a blank 500 page."""
    app.logger.error("Internal Server Error: %s", e, exc_info=True)
    try:
        return render_template("error_500.html"), 500
    except Exception:
        return "<h1>Internal Server Error</h1><p>Something went wrong. Please try again later.</p>", 500


@app.errorhandler(429)
def rate_limited(e):
    return render_template("error_500.html", message="Too many requests. Please wait a while and try again."), 429

# ================= DATABASE REFACTOR =================
def get_db():
    """Opens a new database connection if there is none yet for the current application context."""
    if 'db' not in g:
        db_url = os.environ.get('DATABASE_URL')
        if db_url:
            # Production environment: Connect to PostgreSQL when a valid URL is provided.
            try:
                g.db = psycopg2.connect(db_url, cursor_factory=DictCursor)
            except Exception as e:
                app.logger.warning(f"Falling back to SQLite because PostgreSQL connection failed: {e}")
                g.db = sqlite3.connect(DATABASE)
                g.db.row_factory = sqlite3.Row
        else:
            # Development environment: Connect to local SQLite database
            g.db = sqlite3.connect(DATABASE)
            g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    """Closes the database again at the end of the request."""
    db = g.pop('db', None)
    if db is not None:
        db.close()

# ================= DATABASE =================
def init_db():
    """Initializes the database by creating tables and adding necessary columns."""
    is_postgres = 'DATABASE_URL' in os.environ
    conn = get_db()
    c = conn.cursor()

    # Use appropriate syntax based on the database type
    autoincrement_pk = "SERIAL PRIMARY KEY" if is_postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
    datetime_default = "TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP" if is_postgres else "DATETIME DEFAULT CURRENT_TIMESTAMP"
    ban_expires_type = "TIMESTAMP" if is_postgres else "DATETIME"

    # --- Create Tables ---
    c.execute(f"""
    CREATE TABLE IF NOT EXISTS users (
        id {autoincrement_pk},
        first_name TEXT,
        last_name TEXT,
        password TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        phone TEXT,
        age INTEGER,
        gender TEXT,
        course TEXT,
        role TEXT DEFAULT 'user',
        profile_pic TEXT DEFAULT '/static/images/default_avatar.svg',
        ban_expires_at {ban_expires_type} DEFAULT NULL,
        abuse_offense_count INTEGER DEFAULT 0
    )""")

    c.execute(f"""
    CREATE TABLE IF NOT EXISTS messages (
        id {autoincrement_pk},
        user_email TEXT,
        user_message TEXT,
        bot_response TEXT,
        is_crisis INTEGER DEFAULT 0,
        is_abusive INTEGER DEFAULT 0,
        timestamp {datetime_default}
    )
    """)

    c.execute(f"""
    CREATE TABLE IF NOT EXISTS archived_messages (
        id {autoincrement_pk},
        user_email TEXT,
        user_message TEXT,
        bot_response TEXT,
        is_crisis INTEGER,
        timestamp TIMESTAMP
    )
    """)

    c.execute(f"""
    CREATE TABLE IF NOT EXISTS mood_log (
        id {autoincrement_pk},
        user_email TEXT,
        mood TEXT,
        timestamp {datetime_default}
    )
    """)

    c.execute(f"""
    CREATE TABLE IF NOT EXISTS daily_quotes (
        id {autoincrement_pk},
        quote TEXT
    )
    """)

    c.execute(f"""
    CREATE TABLE IF NOT EXISTS faq_dataset (
        id {autoincrement_pk},
        question TEXT,
        answer TEXT
    )
    """)

    c.execute(f"""
    CREATE TABLE IF NOT EXISTS peer_messages (
        id {autoincrement_pk},
        sender TEXT,
        receiver TEXT,
        message TEXT,
        is_read INTEGER DEFAULT 0,
        timestamp {datetime_default}
    )
    """)

    c.execute(f"""
    CREATE TABLE IF NOT EXISTS ratings (
        id {autoincrement_pk},
        user_email TEXT,
        rating INTEGER,
        timestamp {datetime_default}
    )
    """)

    c.execute(f"""
    CREATE TABLE IF NOT EXISTS admin_logs (
        id {autoincrement_pk},
        admin_username TEXT,
        action TEXT,
        target_username TEXT,
        timestamp TIMESTAMP
    )
    """)

    c.execute(f"""
    CREATE TABLE IF NOT EXISTS user_settings (
        id {autoincrement_pk},
        user_email TEXT UNIQUE NOT NULL,
        show_in_community INTEGER DEFAULT 1,
        allow_peer_messages INTEGER DEFAULT 1,
        language TEXT DEFAULT 'tagalog'
    )
    """)

    # --- Commit table creation before running migrations ---
    conn.commit()

    # --- Migrations for older databases (safe to run multiple times) ---
    # Run for BOTH SQLite and PostgreSQL so databases created by older
    # versions of the app automatically get any newly-added columns.
    def add_column(table, column, definition):
        try:
            if is_postgres:
                c.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}")
            else:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            conn.commit()
        except Exception as e:
            # Column already exists or other error - rollback and continue safely.
            conn.rollback()
            err_msg = str(e).lower()
            if "duplicate" not in err_msg and "already exists" not in err_msg:
                app.logger.warning("Skipping column migration %s.%s: %s", table, column, e)

    add_column("users", "first_name", "TEXT")
    add_column("users", "last_name", "TEXT")
    add_column("users", "phone", "TEXT")
    add_column("users", "age", "INTEGER")
    add_column("users", "gender", "TEXT")
    add_column("users", "course", "TEXT")
    add_column("users", "role", "TEXT DEFAULT 'user'")
    add_column("users", "profile_pic", "TEXT DEFAULT '/static/images/default_avatar.svg'")
    add_column("users", "ban_expires_at", f"{ban_expires_type} DEFAULT NULL")
    add_column("users", "abuse_offense_count", "INTEGER DEFAULT 0")
    add_column("messages", "is_abusive", "INTEGER DEFAULT 0")
    add_column("peer_messages", "is_read", "INTEGER DEFAULT 0")

    # --- Normalize existing emails to lowercase ---
    # Login/register now lowercase emails, so migrate older rows so they match.
    try:
        c.execute("UPDATE users SET email = LOWER(email)")
        conn.commit()
    except Exception as e:
        conn.rollback()
        app.logger.warning("Email normalization skipped: %s", e)

    # --- Seed Data ---
    # Seed FAQs if table is empty
    c.execute("SELECT COUNT(*) FROM faq_dataset")
    if c.fetchone()[0] == 0:
        sample_faqs = [
            ("what is this app for", "This app is a student-friendly mental health chatbot that offers emotional support, grounding exercises, and guidance for school stress."),
            ("how can i use this chatbot", "You can type your concerns here and the chatbot will respond with support, coping tips, and crisis guidance when needed."),
            ("what should i do if i feel like hurting myself", "Please contact emergency services or a crisis hotline immediately and tell a trusted person right away.")
        ]
        if is_postgres:
            c.executemany("INSERT INTO faq_dataset (question, answer) VALUES (%s, %s)", sample_faqs)
        else:
            c.executemany("INSERT INTO faq_dataset (question, answer) VALUES (?, ?)", sample_faqs)

    conn.commit()

# ================= PRELOAD QUOTES =================
def preload_quotes():
    quotes = [
        "Believe in yourself.",
        "It always seems impossible until it's done.",
        "Keep moving forward."
    ]
    is_postgres = 'DATABASE_URL' in os.environ
    conn = get_db()
    c = conn.cursor()
    for q in quotes:
        try:
            # Use %s for PostgreSQL, ? for SQLite
            if is_postgres:
                c.execute("INSERT INTO daily_quotes (quote) VALUES (%s)", (q,))
            else:
                c.execute("INSERT INTO daily_quotes (quote) VALUES (?)", (q,))
        except:
            conn.rollback()
    conn.commit()

# ================= HELPER FUNCTIONS =================
def get_ph_time():
    """Return current Philippine time (UTC+8), timezone-aware."""
    utc_now = datetime.now(timezone.utc)
    ph_timezone = timezone(timedelta(hours=8))
    ph_time = utc_now.astimezone(ph_timezone)
    return ph_time

def format_time(dt):
    """Return formatted datetime string."""
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def log_admin_action(admin_username, action, target_username):
    """Logs an action performed by an admin."""
    db = get_db()
    c = db.cursor()
    ph_time = get_ph_time()
    formatted_time = format_time(ph_time)
    
    # Use %s for PostgreSQL compatibility
    if 'DATABASE_URL' in os.environ:
        c.execute("INSERT INTO admin_logs (admin_username, action, target_username, timestamp) VALUES (%s, %s, %s, %s)",
                  (admin_username, action, target_username, formatted_time))
    else:
        c.execute("INSERT INTO admin_logs (admin_username, action, target_username, timestamp) VALUES (?, ?, ?, ?)",
                  (admin_username, action, target_username, formatted_time))
    db.commit()

def format_time_for_chat(dt_string):
    """Formats a datetime string into a more readable chat format."""
    try:
        # Handles formats like '2024-03-08 12:05:55'
        dt_obj = datetime.strptime(dt_string.split('.')[0], '%Y-%m-%d %H:%M:%S')
        return dt_obj.strftime('%I:%M %p') # e.g., 12:05 PM
    except (ValueError, TypeError):
        return dt_string # Return original if format is unexpected

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_profile_pic_url(pic_url):
    if not pic_url:
        return url_for('static', filename='images/default_avatar.svg')

    if pic_url.startswith('/'):
        decoded_url = urllib.parse.unquote(pic_url)
        local_path = os.path.join(app.root_path, decoded_url.lstrip('/').replace('/', os.sep))
        if os.path.exists(local_path):
            return pic_url

    return url_for('static', filename='images/default_avatar.svg')

# ================= ROUTES =================
@app.route("/")
def home():
    return redirect(url_for("login"))

# ---- LOGIN ----
@app.route("/login", methods=["GET","POST"])
@limiter.limit("10 per minute")
def login():
    error = None
    if request.method=="POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form["password"]
        app.logger.info("Login attempt for email=%r", email)
        db = get_db()
        c = db.cursor()
        # Use %s for PostgreSQL compatibility
        if 'DATABASE_URL' in os.environ:
            c.execute("SELECT email, password, role, ban_expires_at FROM users WHERE email=%s", (email,))
        else:
            c.execute("SELECT email, password, role, ban_expires_at FROM users WHERE email=?", (email,))
        user = c.fetchone()
        if user and check_password_hash(user['password'], password):
            # STRICT SEPARATION: Regular users only. Admins must use the admin login page.
            if user['role'] == 'admin':
                error = "Admins must use the Admin Login page."
            else:
                session["user"] = user['email']
                session["role"] = user['role']
                return redirect(url_for("chatbot"))
        else:
            if not user:
                app.logger.warning("Login failed for %r: no user found", email)
            else:
                app.logger.warning("Login failed for %r: password mismatch", email)
            error = "Invalid credentials."
    return render_template("login.html", error=error)

# ---- ADMIN LOGIN (Separate Route) ----
@app.route("/admin_login", methods=["GET","POST"])
@limiter.limit("5 per minute")
def admin_login():
    error = None
    if request.method=="POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form["password"]
        db = get_db()
        c = db.cursor()
        # Use %s for PostgreSQL compatibility
        if 'DATABASE_URL' in os.environ:
            c.execute("SELECT email, password, role FROM users WHERE email=%s", (username,))
        else:
            c.execute("SELECT email, password, role FROM users WHERE email=?", (username,))
        user = c.fetchone()
        if user and check_password_hash(user['password'], password):
            if user['role'] == 'admin':
                # 2FA has been removed. Log in directly.
                session["user"] = user['email']
                session["role"] = 'admin'
                return redirect(url_for("admin_dashboard"))
            else:
                error = "Access Denied. You are not an admin."
        else:
            error = "Invalid admin credentials."
    return render_template("admin_login.html", error=error)

# ---- ADMIN REGISTER (First-time setup) ----
@app.route("/admin/register", methods=["GET", "POST"])
def admin_register():
    db = get_db()
    c = db.cursor()
    
    # Security: Check if an admin already exists.
    if 'DATABASE_URL' in os.environ:
        c.execute("SELECT id FROM users WHERE role = 'admin'")
    else:
        c.execute("SELECT id FROM users WHERE role = 'admin'")
    
    if c.fetchone():
        flash("Admin registration is closed. An admin account already exists.", "error")
        return redirect(url_for('admin_login'))

    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not email:
            error = "Email is required."
        elif not password or len(password) < 8:
            error = "Password must be at least 8 characters long."
        elif password != confirm_password:
            error = "Passwords do not match."
        
        if error is None:
            hashed_password = hash_password(password)
            try:
                if 'DATABASE_URL' in os.environ:
                    c.execute("INSERT INTO users (email, password, first_name, last_name, role) VALUES (%s, %s, %s, %s, %s)",
                              (email, hashed_password, "Admin", "User", "admin"))
                else:
                    c.execute("INSERT INTO users (email, password, first_name, last_name, role) VALUES (?, ?, ?, ?, ?)",
                              (email, hashed_password, "Admin", "User", "admin"))
                db.commit() # type: ignore
                flash("Admin account created successfully! You can now log in.", "success")
                return redirect(url_for('admin_login'))
            except Exception:
                db.rollback()
                error = "An unexpected error occurred. Please try again."

    # If we are here, it's a GET request or there was a POST error
    return render_template("admin_register.html", error=error)

# ---- REGISTER ----
@app.route("/register", methods=["GET","POST"])
def register():
    error = None
    if request.method=="POST":
        first_name = request.form.get("first_name", "").strip().title()
        last_name = request.form.get("last_name", "").strip().title()
        password = request.form.get("password", "")
        email = request.form.get("email", "").strip().lower()
        student_id = request.form.get("student_id", "").strip()
        age = request.form.get("age")
        gender = request.form.get("gender")
        course = request.form.get("course")
        accept_terms = request.form.get("accept_terms")
        app.logger.info(
            "Register attempt: email=%r gender=%r course=%r student_id=%r age=%r terms=%r",
            email, gender, course, student_id, age, accept_terms,
        )

        # --- Validation ---
        if not first_name:
            error = "First name is required."
        elif not last_name:
            error = "Last name is required."
        elif not password:
            error = "Password is required."
        elif len(password) < 6:
            error = "Password must be at least 6 characters long."
        elif not email:
            error = "Email address is required."
        elif not student_id:
            error = "Student ID is required."
        elif not re.match(r'^\d{2}-\d{4}$', student_id):
            error = "Student ID must be in the format 23-0768 (2 digits, dash, 4 digits)."
        elif not age:
            error = "Age is required."
        elif not gender:
            error = "Gender is required."
        elif not course:
            error = "College/Department is required."
        else:
            try:
                age_int = int(age)
                if age_int < 18:
                    error = "You must be at least 18 years old to register."
            except (ValueError, TypeError):
                error = "Invalid age. Please enter a valid number."
            if error is None and not accept_terms:
                error = "You must accept the Terms and Conditions to register."

        # Check for existing email only if other validations pass
        if error is None:
            db = get_db()
            c = db.cursor()
            if 'DATABASE_URL' in os.environ:
                c.execute("SELECT id FROM users WHERE email = %s", (email,))
            else:
                c.execute("SELECT id FROM users WHERE email = ?", (email,))
            if c.fetchone():
                error = "Email address is already registered. Please use a different one."

        if error is None:
            db = get_db()
            c = db.cursor()
            try:
                hashed_password = hash_password(password)
                if 'DATABASE_URL' in os.environ:
                    c.execute("INSERT INTO users (first_name, last_name, password, email, phone, age, gender, course) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                              (first_name, last_name, hashed_password, email, student_id, int(age), gender, course))
                else:
                    c.execute("INSERT INTO users (first_name, last_name, password, email, phone, age, gender, course) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                              (first_name, last_name, hashed_password, email, student_id, int(age), gender, course))
                # Commit BEFORE sending the welcome email so an email failure can never
                # block or break registration.
                db.commit()
            except Exception as e:
                db.rollback()
                # Log the real error so it can be diagnosed; show a friendly message.
                app.logger.error("Registration INSERT failed for %s: %s", email, e, exc_info=True)
                err_name = type(e).__name__.lower()
                err_msg = str(e).lower()
                if "integrity" in err_name or "unique" in err_msg or "duplicate" in err_msg or "already exists" in err_msg:
                    error = "Email address is already registered. Please use a different one."
                else:
                    error = "An unexpected error occurred. Please try again later."

            if error is None:
                # Send a welcome email (best effort) - never fail registration because of email.
                try:
                    send_registration_email(first_name, email)
                except Exception as e:
                    app.logger.error("Failed to send registration email to %s: %s", email, e)
                flash("Registration successful! Please log in.", "success")
                return redirect(url_for("login"))

        # Log the reason the form was re-rendered so it can be diagnosed.
        if request.method == "POST":
            app.logger.info("Register re-rendered with error: %r", error)

    return render_template("register.html", error=error)

# ---- FORGOT PASSWORD ----
@app.route("/forgot_password", methods=["GET", "POST"])
@limiter.limit("5 per hour")
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        db = get_db()
        c = db.cursor()
        if 'DATABASE_URL' in os.environ:
            c.execute("SELECT email FROM users WHERE email = %s", (email,))
        else:
            c.execute("SELECT email FROM users WHERE email = ?", (email,))
        user = c.fetchone()

        if user:
            # User found, generate and send reset link
            token = s.dumps(email, salt='password-reset-salt')
            reset_link = url_for('reset_with_token', token=token, _external=True)
            app.logger.info(f"User password reset link generated: {reset_link}")
            try:
                email_sent = send_password_reset_email(email, reset_link)
            except Exception as e:
                app.logger.error("Unexpected error sending password reset email to %s: %s", email, e)
                email_sent = False
            # For development convenience, optionally show the reset link when emails are printed to console
            if EMAIL_BACKEND == 'console' or os.environ.get('SHOW_RESET_LINKS', '').strip().lower() == 'true':
                flash(f"Password reset link (dev): {reset_link}", "success")
            if not email_sent:
                # Render blocks outbound SMTP, so fall back to showing the link
                # so the user can still reset their password.
                flash("Could not send the reset email. Use this link to reset your password:", "error")
                flash(f"{reset_link}", "info")
                return redirect(url_for('forgot_password'))

        # For better UX and security, always show a generic success message.
        flash(f"An email has been sent to {email} with instructions to reset your password, if that account exists.", "success")
        return redirect(url_for('forgot_password'))

    return render_template("forgot_password.html")

# ---- RESET PASSWORD with TOKEN ----
@app.route('/reset/<token>', methods=["GET", "POST"])
def reset_with_token(token):
    try:
        # Check token validity (max_age in seconds, 3600s = 1 hour)
        email = s.loads(token, salt='password-reset-salt', max_age=3600)
    except SignatureExpired:
        flash("The password reset link has expired. Please request a new one.", "error")
        return redirect(url_for('forgot_password'))
    except BadTimeSignature:
        flash("Invalid password reset link.", "error")
        return redirect(url_for('forgot_password'))
    except BadSignature:
        flash("Invalid password reset link. Please request a new one.", "error")
        return redirect(url_for('forgot_password'))

    if request.method == "POST":
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")

        if not password or len(password) < 6:
            flash("Password must be at least 6 characters long.", "error")
        elif password != confirm_password:
            flash("Passwords do not match.", "error")
        else:
            hashed_password = hash_password(password)
            db = get_db()
            c = db.cursor()
            if 'DATABASE_URL' in os.environ:
                c.execute("UPDATE users SET password = %s WHERE email = %s", (hashed_password, email))
            else:
                c.execute("UPDATE users SET password = ? WHERE email = ?", (hashed_password, email))
            db.commit()
            flash("Your password has been updated! You can now log in.", "success")
            return redirect(url_for('login'))

    return render_template('reset_with_token.html', token=token)

# ---- ADMIN FORGOT/RESET PASSWORD ----
@app.route("/admin/forgot_password", methods=["GET", "POST"])
@limiter.limit("5 per hour")
def admin_forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        db = get_db()
        c = db.cursor()
        # Ensure the user is an admin
        if 'DATABASE_URL' in os.environ:
            c.execute("SELECT email FROM users WHERE email = %s AND role = 'admin'", (email,))
        else:
            c.execute("SELECT email FROM users WHERE email = ? AND role = 'admin'", (email,))
        user = c.fetchone()

        app.logger.info(f"Admin password reset requested for {email}")

        if user:
            # User is an admin, generate and send reset link
            token = s.dumps(email, salt='admin-password-reset-salt')
            reset_link = url_for('admin_reset_with_token', token=token, _external=True)
            app.logger.info(f"Admin password reset link generated: {reset_link}")
            try:
                email_sent = send_password_reset_email(email, reset_link)
            except Exception as e:
                app.logger.error("Unexpected error sending admin password reset email to %s: %s", email, e)
                email_sent = False
            # For development convenience, optionally show the reset link when emails are printed to console
            if EMAIL_BACKEND == 'console' or os.environ.get('SHOW_RESET_LINKS', '').strip().lower() == 'true':
                flash(f"Admin password reset link (dev): {reset_link}", "success")
            if not email_sent:
                app.logger.warning("Admin password reset email could not be sent for %s", email)
                flash("Could not send the reset email. Use this link to reset your admin password:", "error")
                flash(f"{reset_link}", "info")
                return redirect(url_for('admin_forgot_password'))
        else:
            app.logger.info("Admin password reset requested for non-existent admin email: %s", email)

        # Always show a generic success message for security
        flash(f"If an admin account with the email {email} exists, a password reset link has been sent.", "success")
        return redirect(url_for('admin_forgot_password'))

    return render_template("admin_forgot_password.html")

@app.route('/admin/reset/<token>', methods=["GET", "POST"]) # Changed function name
def admin_reset_with_token(token):
    try:
        email = s.loads(token, salt='admin-password-reset-salt', max_age=3600)
    except SignatureExpired:
        flash("The password reset link has expired. Please request a new one.", "error")
        return redirect(url_for('admin_forgot_password'))
    except BadTimeSignature:
        flash("Invalid password reset link.", "error")
        return redirect(url_for('admin_forgot_password'))
    except BadSignature:
        flash("Invalid password reset link. Please request a new one.", "error")
        return redirect(url_for('admin_forgot_password'))

    if request.method == "POST":
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")

        if not password or len(password) < 6:
            flash("Password must be at least 6 characters long.", "error")
        elif password != confirm_password:
            flash("Passwords do not match.", "error")
        else:
            hashed_password = hash_password(password)
            db = get_db()
            c = db.cursor()
            if 'DATABASE_URL' in os.environ:
                c.execute("UPDATE users SET password = %s WHERE email = %s AND role = 'admin'", (hashed_password, email))
            else:
                c.execute("UPDATE users SET password = ? WHERE email = ? AND role = 'admin'", (hashed_password, email))
            db.commit()
            flash("Admin password has been updated! You can now log in.", "success")
            return redirect(url_for('admin_login'))

    return render_template('admin_reset_with_token.html', token=token)

# ---- CHATBOT ----
@app.route("/chatbot")
def chatbot():
    if "user" not in session:
        return redirect(url_for("login"))
    db = get_db()
    c = db.cursor()

    # Daily quote
    if 'DATABASE_URL' in os.environ: # PostgreSQL
        c.execute("SELECT quote FROM daily_quotes ORDER BY RANDOM() LIMIT 1") # PostgreSQL
    else:
        c.execute("SELECT quote FROM daily_quotes ORDER BY RANDOM() LIMIT 1") # SQLite
    row = c.fetchone()
    daily_quote = row[0] if row else ""

    # Load messages
    if 'DATABASE_URL' in os.environ:
        c.execute("SELECT user_message, bot_response FROM messages WHERE user_email=%s ORDER BY id ASC", (session["user"],))
    else:
        c.execute("SELECT user_message, bot_response FROM messages WHERE user_email=? ORDER BY id ASC", (session["user"],))
    messages = c.fetchall()

    # Check if mood was logged today
    today_str = get_ph_time().strftime('%Y-%m-%d')
    if 'DATABASE_URL' in os.environ:
        # For PostgreSQL, we need to cast the timestamp to a date
        c.execute("SELECT COUNT(*) FROM mood_log WHERE user_email=%s AND CAST(timestamp AS DATE) = %s", (session["user"], today_str))
    else:
        c.execute("SELECT COUNT(*) FROM mood_log WHERE user_email=? AND DATE(timestamp) = ?", (session["user"], today_str))
    mood_log_count = c.fetchone()[0]
    mood_logged_today = mood_log_count > 0

    return render_template("index.html", messages=messages, daily_quote=daily_quote, mood_logged_today=mood_logged_today)

# ---- SET LANGUAGE ----
@app.route("/set_language", methods=["POST"])
def set_language():
    if "user" not in session:
        return jsonify({"status":"Unauthorized"}), 401
    data = request.get_json()
    language = data.get("language")
    if language in ["tagalog", "waray"]:
        session["language"] = language
        return jsonify({"status": "ok", "language": language})
    return jsonify({"status": "error"}), 400

# ---- CHAT MESSAGE ----
@app.route("/chat", methods=["POST"])
def chat():
    if "user" not in session:
        return jsonify({"response":"Unauthorized"}),401
    data = request.get_json()
    message = data.get("message","")
    db = get_db()
    c = db.cursor()

    # Get user language preference (default to tagalog)
    user_language = session.get("language", "tagalog")

    # Check user's current ban status and offense count
    if 'DATABASE_URL' in os.environ:
        c.execute("SELECT abuse_offense_count, ban_expires_at FROM users WHERE email = %s", (session["user"],))
    else:
        c.execute("SELECT abuse_offense_count, ban_expires_at FROM users WHERE email = ?", (session["user"],))
    user_status = c.fetchone()
    current_offenses = user_status['abuse_offense_count'] if user_status else 0
    
    # Block chatting if user is currently banned
    if user_status and user_status['ban_expires_at']:
        try:
            ph_timezone = timezone(timedelta(hours=8))
            # Parse the naive string from DB and make it timezone-aware
            naive_ban_expiry_dt = datetime.strptime(user_status['ban_expires_at'].split('.')[0], '%Y-%m-%d %H:%M:%S')
            aware_ban_expiry_dt = naive_ban_expiry_dt.replace(tzinfo=ph_timezone)

            if aware_ban_expiry_dt > get_ph_time():
                expiry_formatted = aware_ban_expiry_dt.strftime('%B %d, %Y at %I:%M %p')
                
                if user_language == 'waray':
                    ban_msg = f"An imo account in suspendido pa. Pwede mo ini gamiton utro pagkatapos hiton {expiry_formatted}."
                else:
                    ban_msg = f"Ang iyong account ay kasalukuyang suspendido. Maaari mo itong muling gamitin pagkatapos ng {expiry_formatted}."
                return jsonify({"response": ban_msg})
        except (ValueError, TypeError):
            pass

    # Generate bot response and check for abuse
    last_intent = session.get('last_intent')
    reply, new_intent, is_crisis, is_abusive = generate_response(message, last_intent, user_language)
    if new_intent:
        session['last_intent'] = new_intent

    # --- AUTOMATIC BANNING LOGIC (DISABLED) ---
    # The code below is commented out to disable automatic banning.
    # The bot will still respond to abusive words, but will not suspend the user.
    # if is_abusive:
    #     current_offenses += 1
    #     ban_duration = None
    #     duration_str = ""

    #     if current_offenses == 1:
    #         ban_duration = timedelta(days=1)
    #         duration_str = "1 araw"
    #     elif current_offenses == 2:
    #         ban_duration = timedelta(weeks=1)
    #         duration_str = "1 linggo"
    #     elif current_offenses == 3:
    #         ban_duration = timedelta(weeks=3)
    #         duration_str = "3 linggo"
    #     else: # 4th offense and beyond
    #         ban_duration = timedelta(days=30)
    #         duration_str = "1 buwan"

    #     ban_until = get_ph_time() + ban_duration
    #     ban_until_str = ban_until.strftime("%Y-%m-%d %H:%M:%S")
    #     expiry_formatted = ban_until.strftime('%B %d, %Y at %I:%M %p')

    #     c.execute("UPDATE users SET abuse_offense_count = ?, ban_expires_at = ? WHERE email = ?",
    #               (current_offenses, ban_until_str, session["user"]))
        
    #     # Log the automatic ban action
    #     action_details = f"auto_ban_{duration_str.replace(' ', '_')}"
    #     log_admin_action('SYSTEM', action_details, session["user"])

    #     # Override reply with a ban notification
    #     if user_language == 'waray':
    #         reply = f"PAHIBARO (Offense #{current_offenses}): Tungod han pa-ulit-ulit nga paggamit hin maraot nga pulong, an imo account in suspendido ha sulod hin {duration_str}. Pwede mo ini gamiton utro pagkatapos hiton {expiry_formatted}."
    #     else:
    #         reply = f"BABALA (Offense #{current_offenses}): Dahil sa paulit-ulit na paggamit ng hindi angkop na lenggwahe, ang iyong account ay suspendido sa loob ng {duration_str}. Maaari mo itong muling gamitin pagkatapos ng {expiry_formatted}."

    # Timezone-aware PH time
    ph_time = get_ph_time()
    formatted_time = format_time(ph_time)

    # Use correct placeholder based on DB type
    if 'DATABASE_URL' in os.environ:
        c.execute("""INSERT INTO messages (user_email,user_message,bot_response,is_crisis,is_abusive,timestamp) VALUES (%s,%s,%s,%s,%s,%s)""",
                  (session["user"], message, reply, is_crisis, is_abusive, formatted_time))
    else:
        c.execute("""INSERT INTO messages (user_email,user_message,bot_response,is_crisis,is_abusive,timestamp) VALUES (?,?,?,?,?,?)""",
                  (session["user"], message, reply, is_crisis, is_abusive, formatted_time))
    db.commit()
    
    if is_crisis:
        # send_crisis_email(session["user"], message) # Temporarily disable to avoid email errors during setup
        pass

    return jsonify({"response":reply})

# ---- MOOD LOGGING ----
@app.route("/log_mood", methods=["POST"])
def log_mood():
    if "user" not in session:
        return jsonify({"status":"Unauthorized"}),401
    data = request.get_json()
    mood = data.get("mood")
    if not mood:
        return jsonify({"status":"error"}),400

    # Timezone-aware PH time
    ph_time = get_ph_time()
    formatted_time = format_time(ph_time)

    db = get_db()
    c = db.cursor()
    # Use correct placeholder based on DB type
    if 'DATABASE_URL' in os.environ:
        c.execute("INSERT INTO mood_log (user_email,mood,timestamp) VALUES (%s,%s,%s)", (session["user"],mood,formatted_time))
    else:
        c.execute("INSERT INTO mood_log (user_email,mood,timestamp) VALUES (?,?,?)", (session["user"],mood,formatted_time))
    db.commit()
    return jsonify({"status":"ok"})

# ---- RATING ----
@app.route("/rate_session", methods=["POST"])
def rate_session():
    if "user" not in session:
        return jsonify({"status":"Unauthorized"}), 401
    data = request.get_json()
    rating = data.get("rating")
    if not rating or rating not in [1,2,3,4,5]:
        return jsonify({"status":"error"}), 400

    ph_time = get_ph_time()
    formatted_time = format_time(ph_time)

    db = get_db()
    c = db.cursor()
    # Use correct placeholder based on DB type
    if 'DATABASE_URL' in os.environ:
        c.execute("INSERT INTO ratings (user_email, rating, timestamp) VALUES (%s,%s,%s)", (session["user"], rating, formatted_time))
    else:
        c.execute("INSERT INTO ratings (user_email, rating, timestamp) VALUES (?,?,?)", (session["user"], rating, formatted_time))
    db.commit()
    return jsonify({"status":"ok", "message": "Thank you for your feedback!"})

# ---- MINI DASHBOARD / MOOD ANALYTICS ROOM ----
@app.route("/mini_dashboard")
def mini_dashboard():
    if "user" not in session:
        return redirect(url_for("login"))

    db = get_db()
    c = db.cursor()

    # Mood summary
    if 'DATABASE_URL' in os.environ:
        c.execute("SELECT mood, COUNT(*) as total FROM mood_log WHERE user_email=%s GROUP BY mood", (session["user"],))
    else:
        c.execute("SELECT mood, COUNT(*) as total FROM mood_log WHERE user_email=? GROUP BY mood", (session["user"],))
    mood_data = c.fetchall()
    moods = [row["mood"] for row in mood_data]
    counts = [row["total"] for row in mood_data]

    # Weekly trend
    today = datetime.now(timezone(timedelta(hours=8)))
    days = []
    trend_data = {"Happy": [], "Neutral": [], "Sad": []}
    for i in range(6, -1, -1):
        day = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        days.append(day)
        for mood in trend_data.keys():
            if 'DATABASE_URL' in os.environ:
                # For PostgreSQL, we need to cast the timestamp to a date
                c.execute("SELECT COUNT(*) as total FROM mood_log WHERE user_email=%s AND mood=%s AND CAST(timestamp AS DATE)=%s",
                          (session["user"], mood, day))
            else:
                c.execute("SELECT COUNT(*) as total FROM mood_log WHERE user_email=? AND mood=? AND DATE(timestamp)=?",
                          (session["user"], mood, day))
            result = c.fetchone()
            trend_data[mood].append(result["total"] if result["total"] is not None else 0)

    return render_template("mini_dashboard.html", moods=moods, counts=counts, days=days, trend_data=trend_data, username=session["user"])
@app.route("/mini_games")
def mini_games():
    return render_template("mini_games.html")
# ---- ARCHIVED ROOM ----
@app.route("/archived_room")
def archived_room():
    if "user" not in session:
        return redirect(url_for("login"))

    db = get_db()
    c = db.cursor()
    if 'DATABASE_URL' in os.environ:
        c.execute("SELECT user_message, bot_response, timestamp, id FROM archived_messages WHERE user_email=%s ORDER BY id DESC", (session["user"],))
    else:
        c.execute("SELECT user_message, bot_response, timestamp, id FROM archived_messages WHERE user_email=? ORDER BY id DESC", (session["user"],))
    archived = c.fetchall()

    return render_template("archived_room.html", archived=archived)

# ---- ARCHIVE / RESTORE / DELETE ----
@app.route("/restart_chat")
def restart_chat():
    if "user" not in session:
        return redirect(url_for("login"))
    db = get_db()
    c = db.cursor()
    if 'DATABASE_URL' in os.environ:
        c.execute("""INSERT INTO archived_messages (user_email,user_message,bot_response,is_crisis,timestamp)
                     SELECT user_email,user_message,bot_response,is_crisis,timestamp FROM messages WHERE user_email=%s""", (session["user"],))
        c.execute("DELETE FROM messages WHERE user_email=%s", (session["user"],))
    else:
        c.execute("""INSERT INTO archived_messages (user_email,user_message,bot_response,is_crisis,timestamp)
                     SELECT user_email,user_message,bot_response,is_crisis,timestamp FROM messages WHERE user_email=?""", (session["user"],))
        c.execute("DELETE FROM messages WHERE user_email=?", (session["user"],))
    db.commit() # type: ignore
    return redirect(url_for("chatbot"))

@app.route("/restore_chat/<int:archive_id>")
def restore_chat(archive_id):
    if "user" not in session:
        return redirect(url_for("login"))
    db = get_db()
    c = db.cursor()
    if 'DATABASE_URL' in os.environ:
        c.execute("""SELECT user_email,user_message,bot_response,is_crisis,timestamp
                     FROM archived_messages WHERE id=%s AND user_email=%s""", (archive_id, session["user"]))
    else:
        c.execute("""SELECT user_email,user_message,bot_response,is_crisis,timestamp
                     FROM archived_messages WHERE id=? AND user_email=?""", (archive_id, session["user"]))
    row = c.fetchone()
    if row:
        if 'DATABASE_URL' in os.environ:
            c.execute("INSERT INTO messages (user_email,user_message,bot_response,is_crisis,timestamp) VALUES (%s,%s,%s,%s,%s)", row)
            c.execute("DELETE FROM archived_messages WHERE id=%s AND user_email=%s", (archive_id, session["user"]))
        else:
            c.execute("INSERT INTO messages (user_email,user_message,bot_response,is_crisis,timestamp) VALUES (?,?,?,?,?)", row)
            c.execute("DELETE FROM archived_messages WHERE id=? AND user_email=?", (archive_id, session["user"]))
        db.commit() # type: ignore
    return redirect(url_for("archived_room"))

@app.route("/delete_chat/<int:archive_id>")
def delete_chat(archive_id):
    if "user" not in session:
        return redirect(url_for("login"))
    db = get_db()
    c = db.cursor()
    if 'DATABASE_URL' in os.environ:
        c.execute("DELETE FROM archived_messages WHERE id=%s AND user_email=%s", (archive_id, session["user"]))
    else:
        c.execute("DELETE FROM archived_messages WHERE id=? AND user_email=?", (archive_id, session["user"]))
    db.commit() # type: ignore
    return redirect(url_for("archived_room"))

# ---- LOGOUT ----
@app.route("/logout")
def logout():
    # You might want to remove the user from typing_users on logout
    session.clear()
    return redirect(url_for("login"))

# ================= PEER CHAT FEATURES =================
@app.route("/community")
def community():
    if "user" not in session:
        return redirect(url_for("login"))
    db = get_db()
    c = db.cursor() # Use correct placeholder based on DB type
    if 'DATABASE_URL' in os.environ:
        c.execute("SELECT email, first_name, last_name, profile_pic FROM users WHERE email != %s AND role != 'admin'", (session["user"],))
    else:
        c.execute("SELECT email, first_name, last_name, profile_pic FROM users WHERE email != ? AND role != 'admin'", (session["user"],))
    all_users = c.fetchall()
    
    users_data = []
    for u_row in all_users:
        u_email = u_row['email']
        u_profile_pic = get_profile_pic_url(u_row['profile_pic'])
        
        # Check if this user has opted to show in community
        if 'DATABASE_URL' in os.environ:
            c.execute("SELECT show_in_community FROM user_settings WHERE user_email=%s", (u_email,))
        else:
            c.execute("SELECT show_in_community FROM user_settings WHERE user_email=?", (u_email,))
        setting_row = c.fetchone()
        if setting_row and setting_row['show_in_community'] == 0:
            continue  # Skip users who opted out
        
        # Count unread messages from this user (u) to current user (using %s)
        if 'DATABASE_URL' in os.environ:
            c.execute("SELECT COUNT(*) FROM peer_messages WHERE sender=%s AND receiver=%s AND is_read=0", (u_email, session["user"]))
        else:
            c.execute("SELECT COUNT(*) FROM peer_messages WHERE sender=? AND receiver=? AND is_read=0", (u_email, session["user"]))
        count = c.fetchone()[0]
        users_data.append({"username": u_email, "name": f"{u_row['first_name']} {u_row['last_name']}", "unread": count, "profile_pic": u_profile_pic})

    # Get current user's profile pic to display
    if 'DATABASE_URL' in os.environ:
        c.execute("SELECT profile_pic FROM users WHERE email = %s", (session["user"],))
    else:
        c.execute("SELECT profile_pic FROM users WHERE email = ?", (session["user"],))
    current_user_pic_row = c.fetchone()
    current_user_pic = get_profile_pic_url(current_user_pic_row[0] if current_user_pic_row else None)

    return render_template("community.html", users=users_data, current_user_pic=current_user_pic, current_username=session['user'])

@app.route("/peer_chat/<partner>")
def peer_chat(partner):
    if "user" not in session:
        return redirect(url_for("login"))
    db = get_db()
    c = db.cursor()
    if 'DATABASE_URL' in os.environ:
        c.execute("SELECT profile_pic FROM users WHERE email = %s", (partner,))
    else:
        c.execute("SELECT profile_pic FROM users WHERE email = ?", (partner,))
    partner_pic_row = c.fetchone()
    partner_pic = get_profile_pic_url(partner_pic_row[0] if partner_pic_row else None)
    return render_template("peer_chat.html", partner=partner, username=session["user"], partner_pic=partner_pic)

@app.route('/api/upload_image', methods=['POST'])
def upload_image():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    if file and allowed_file(file.filename):
        unique_filename = f"chat_image_{session['user']}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(file.filename)}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        try:
            file.save(filepath)
            file_url = url_for('static', filename=f'uploads/{unique_filename}')
            return jsonify({"url": file_url})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"error": "File type not allowed"}), 400

@app.route("/api/send_peer", methods=["POST"])
def send_peer():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    receiver = data.get("receiver")
    message = data.get("message")
    
    if not message or not receiver:
        return jsonify({"error": "Missing data"}), 400

    db = get_db()
    c = db.cursor()

    # Use timezone-aware PH time
    ph_time = get_ph_time()
    formatted_time = format_time(ph_time)

    if 'DATABASE_URL' in os.environ:
        c.execute("INSERT INTO peer_messages (sender, receiver, message, timestamp) VALUES (%s,%s,%s,%s)",
                  (session["user"], receiver, message, formatted_time))
    else:
        c.execute("INSERT INTO peer_messages (sender, receiver, message, timestamp) VALUES (?,?,?,?)", (session["user"], receiver, message, formatted_time))
    db.commit()
    return jsonify({"status": "ok"})

@app.route("/api/get_peer/<partner>")
def get_peer(partner):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    user = session["user"]
    db = get_db()
    c = db.cursor()
    
    # Mark messages as read when opening chat
    if 'DATABASE_URL' in os.environ:
        c.execute("UPDATE peer_messages SET is_read=1 WHERE sender=%s AND receiver=%s", (partner, user))
    else:
        c.execute("UPDATE peer_messages SET is_read=1 WHERE sender=? AND receiver=?", (partner, user))
    db.commit()

    if 'DATABASE_URL' in os.environ:
        c.execute("""SELECT sender, message, timestamp FROM peer_messages WHERE (sender=%s AND receiver=%s) OR (sender=%s AND receiver=%s) ORDER BY id ASC""",
                  (user, partner, partner, user))
    else:
        c.execute("""SELECT sender, message, timestamp FROM peer_messages WHERE (sender=? AND receiver=?) OR (sender=? AND receiver=?) ORDER BY id ASC""",
                  (user, partner, partner, user))
    
    messages = [{"sender": r[0], "message": r[1], "timestamp": format_time_for_chat(r[2])} for r in c.fetchall()]
    return jsonify({"messages": messages})

@app.route('/api/typing', methods=['POST'])
def set_typing_status():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    username = session['user']
    typing_users[username] = datetime.now(timezone.utc)
    return jsonify({"status": "ok"})

@app.route('/api/typing_status/<partner>')
def get_typing_status(partner):
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    last_typed = typing_users.get(partner)
    is_typing = False
    if last_typed:
        # If the last typing signal was within the last 3 seconds
        if (datetime.now(timezone.utc) - last_typed).total_seconds() < 3:
            is_typing = True
            
    return jsonify({"is_typing": is_typing})

@app.route('/api/upload_profile_pic', methods=['POST'])
def upload_profile_pic():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    if file and allowed_file(file.filename):
        username = session['user']
        safe_username = secure_filename(username)
        unique_filename = f"pfp_{safe_username}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(file.filename)}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        try:
            file.save(filepath)
            file_url = url_for('static', filename=f'uploads/{unique_filename}')
            db = get_db()
            c = db.cursor() # Use correct placeholder based on DB type
            if 'DATABASE_URL' in os.environ:
                c.execute("UPDATE users SET profile_pic = %s WHERE email = %s", (file_url, username))
            else:
                try:
                    c.execute("UPDATE users SET profile_pic = ? WHERE email = ?", (file_url, username))
                except sqlite3.OperationalError as e:
                    app.logger.error(f"SQLite error on profile pic update: {e}")
            db.commit() # type: ignore
            return jsonify({"status": "ok", "url": file_url})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"error": "File type not allowed"}), 400

# ================= ADMIN DASHBOARD =================
@app.route("/admin_dashboard")
def admin_dashboard():
    if "user" not in session or session.get("role") != "admin":
        return redirect(url_for("login"))
    
    db = get_db()
    c = db.cursor()
    
    # Get all users
    if 'DATABASE_URL' in os.environ:
        c.execute("SELECT id, email, first_name, last_name, phone, age, gender, course, role, ban_expires_at, abuse_offense_count FROM users WHERE role != 'admin'")
    else:
        c.execute("SELECT id, email, first_name, last_name, phone, age, gender, course, role, ban_expires_at, abuse_offense_count FROM users WHERE role != 'admin'")
    all_users = c.fetchall()

    users_data = []
    seven_days_ago = (get_ph_time() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")

    for user in all_users:
        # Check for "At-Risk" status: 3 or more 'Sad' logs in the last 7 days
        if 'DATABASE_URL' in os.environ:
            c.execute("""SELECT COUNT(*) FROM mood_log WHERE user_email=%s AND mood='Sad' AND timestamp >= %s""",
                      (user['email'], seven_days_ago))
        else:
            c.execute("""SELECT COUNT(*) FROM mood_log WHERE user_email=? AND mood='Sad' AND timestamp >= ?""",
                      (user['email'], seven_days_ago))
        sad_row = c.fetchone()
        sad_count = sad_row[0] if sad_row else 0

        # Check for any crisis messages
        if 'DATABASE_URL' in os.environ:
            c.execute("SELECT COUNT(*) FROM messages WHERE user_email=%s AND is_crisis=1", (user['email'],))
        else:
            c.execute("SELECT COUNT(*) FROM messages WHERE user_email=? AND is_crisis=1", (user['email'],))
        crisis_row = c.fetchone()
        crisis_count = crisis_row[0] if crisis_row else 0

        # Check for any abusive messages
        if 'DATABASE_URL' in os.environ:
            c.execute("SELECT COUNT(*) FROM messages WHERE user_email=%s AND is_abusive=1", (user['email'],))
        else:
            c.execute("SELECT COUNT(*) FROM messages WHERE user_email=? AND is_abusive=1", (user['email'],))
        abusive_row = c.fetchone()
        abusive_count = abusive_row[0] if abusive_row else 0

        user_dict = dict(user)
        user_dict['is_banned'] = False
        user_dict['ban_expiry_formatted'] = None

        if user['ban_expires_at']:
            try:
                ph_timezone = timezone(timedelta(hours=8))
                naive_ban_expiry_dt = datetime.strptime(user['ban_expires_at'].split('.')[0], '%Y-%m-%d %H:%M:%S')
                aware_ban_expiry_dt = naive_ban_expiry_dt.replace(tzinfo=ph_timezone)
                if aware_ban_expiry_dt > get_ph_time():
                    user_dict['is_banned'] = True
                    user_dict['ban_expiry_formatted'] = aware_ban_expiry_dt.strftime('%b %d, %Y')
            except (ValueError, TypeError):
                pass # Keep as not banned if date is malformed

        user_dict['at_risk'] = sad_count >= 3
        user_dict['has_crisis_chat'] = crisis_count > 0
        user_dict['has_abusive_chat'] = abusive_count > 0
        users_data.append(user_dict)
    
    return render_template("admin_dashboard.html", users=users_data)

@app.route("/admin/user/<username>")
def admin_user_details(username):
    if "user" not in session or session.get("role") != "admin":
        return redirect(url_for("login"))

    db = get_db()
    c = db.cursor()
    
    # User Info
    if 'DATABASE_URL' in os.environ:
        c.execute("SELECT * FROM users WHERE email=%s", (username,))
    else:
        c.execute("SELECT * FROM users WHERE email=?", (username,))
    user_info_row = c.fetchone()
    
    if not user_info_row:
        return "User not found", 404

    user_info = dict(user_info_row) # Convert to dict to modify

    # Add ban status to the user_info dict
    user_info['is_banned'] = False
    user_info['ban_expiry_formatted'] = None
    if user_info.get('ban_expires_at'):
        try:
            ph_timezone = timezone(timedelta(hours=8))
            naive_ban_expiry_dt = datetime.strptime(user_info['ban_expires_at'].split('.')[0], '%Y-%m-%d %H:%M:%S')
            aware_ban_expiry_dt = naive_ban_expiry_dt.replace(tzinfo=ph_timezone)
            if aware_ban_expiry_dt > get_ph_time():
                user_info['is_banned'] = True
                user_info['ban_expiry_formatted'] = aware_ban_expiry_dt.strftime('%b %d, %Y')
        except (ValueError, TypeError):
            pass

    # Chat History (Active)
    if 'DATABASE_URL' in os.environ:
        c.execute("SELECT * FROM messages WHERE user_email=%s ORDER BY timestamp DESC", (username,))
    else:
        c.execute("SELECT * FROM messages WHERE user_email=? ORDER BY timestamp DESC", (username,))
    active_chats = c.fetchall()
    
    # Chat History (Archived)
    if 'DATABASE_URL' in os.environ:
        c.execute("SELECT * FROM archived_messages WHERE user_email=%s ORDER BY timestamp DESC", (username,))
    else:
        c.execute("SELECT * FROM archived_messages WHERE user_email=? ORDER BY timestamp DESC", (username,))
    archived_chats = c.fetchall()
    
    # Mood Logs
    if 'DATABASE_URL' in os.environ:
        c.execute("SELECT mood, timestamp FROM mood_log WHERE user_email=%s ORDER BY timestamp ASC", (username,))
    else:
        c.execute("SELECT mood, timestamp FROM mood_log WHERE user_email=? ORDER BY timestamp ASC", (username,))
    mood_logs = c.fetchall()
    
    # Process Mood Data for Charts
    mood_counts = {}
    for log in mood_logs:
        # Ensure 'mood' key exists, as DictCursor might not always guarantee it if column is missing
        if 'mood' not in log:
            continue
        m = log["mood"]
        mood_counts[m] = mood_counts.get(m, 0) + 1
        
    # Weekly trend
    today = get_ph_time()
    days = []
    trend_data = {"Happy": [], "Neutral": [], "Sad": []}
    for i in range(6, -1, -1):
        day = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        days.append(day)
        for mood in trend_data.keys():
            if 'DATABASE_URL' in os.environ:
                # For PostgreSQL, we need to cast the timestamp to a date
                c.execute("SELECT COUNT(*) as total FROM mood_log WHERE user_email=%s AND mood=%s AND CAST(timestamp AS DATE)=%s",
                          (username, mood, day))
            else:
                c.execute("SELECT COUNT(*) as total FROM mood_log WHERE user_email=? AND mood=? AND DATE(timestamp)=?",
                          (username, mood, day))
            result = c.fetchone()
            trend_data[mood].append(result["total"] if result["total"] is not None else 0)
        
    # Get Average Rating
    if 'DATABASE_URL' in os.environ:
        c.execute("SELECT AVG(rating) FROM ratings WHERE user_email=%s", (username,))
    else:
        c.execute("SELECT AVG(rating) FROM ratings WHERE user_email=?", (username,))
    avg_rating_row = c.fetchone()
    avg_rating = avg_rating_row[0] if avg_rating_row and avg_rating_row[0] is not None else 0
    
    return render_template("admin_user_details.html", user=user_info, 
                           active_chats=active_chats, archived_chats=archived_chats, 
                           mood_counts=mood_counts, avg_rating=avg_rating,
                           days=days, trend_data=trend_data)

@app.route("/admin/delete_user/<username>", methods=["POST"])
def admin_delete_user(username):
    if "user" not in session or session.get("role") != "admin":
        return redirect(url_for("login"))

    if username == "admin@system.local": # Prevent admin from deleting itself
        return redirect(url_for("admin_dashboard"))

    db = get_db()
    c = db.cursor()

    # Delete all associated data
    placeholder = "%s" if 'DATABASE_URL' in os.environ else "?"
    c.execute(f"DELETE FROM users WHERE email={placeholder}", (username,))
    c.execute(f"DELETE FROM messages WHERE user_email={placeholder}", (username,))
    c.execute(f"DELETE FROM archived_messages WHERE user_email={placeholder}", (username,))
    c.execute(f"DELETE FROM mood_log WHERE user_email={placeholder}", (username,))
    c.execute(f"DELETE FROM ratings WHERE user_email={placeholder}", (username,))
    if 'DATABASE_URL' in os.environ:
        c.execute("DELETE FROM peer_messages WHERE sender=%s OR receiver=%s", (username, username))
    else:
        c.execute("DELETE FROM peer_messages WHERE sender=? OR receiver=?", (username, username))

    # Log the action before committing
    log_admin_action(session['user'], 'delete_user', username)

    db.commit() # type: ignore

    # Return to the logs page if deletion was performed from there, otherwise go to dashboard
    if request.referrer and '/admin/logs' in request.referrer:
        return redirect(url_for("admin_logs"))
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/ban_user/<username>", methods=["POST"])
def admin_ban_user(username):
    if "user" not in session or session.get("role") != "admin":
        return redirect(url_for("login"))

    if username == "admin@system.local": # Prevent admin from banning itself
        return redirect(url_for("admin_dashboard"))

    db = get_db()
    c = db.cursor()
    # A "permanent" manual ban can be a date far in the future
    if 'DATABASE_URL' in os.environ:
        permanent_ban_date = '9999-12-31 23:59:59+08' # For PostgreSQL, include timezone
    else:
        permanent_ban_date = '9999-12-31 23:59:59'
    log_admin_action(session['user'], 'ban_user', username)
    if 'DATABASE_URL' in os.environ:
        c.execute("UPDATE users SET ban_expires_at = %s WHERE email = %s", (permanent_ban_date, username))
    else:
        c.execute("UPDATE users SET ban_expires_at = ? WHERE email = ?", (permanent_ban_date, username))
    db.commit() # type: ignore
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/unban_user/<username>", methods=["POST"])
def admin_unban_user(username):
    if "user" not in session or session.get("role") != "admin":
        return redirect(url_for("login"))

    db = get_db()
    c = db.cursor()
    # Unbanning also resets their offense count
    log_admin_action(session['user'], 'unban_user', username)
    if 'DATABASE_URL' in os.environ:
        c.execute("UPDATE users SET ban_expires_at = NULL, abuse_offense_count = 0 WHERE email = %s", (username,))
    else:
        c.execute("UPDATE users SET ban_expires_at = NULL, abuse_offense_count = 0 WHERE email = ?", (username,))
    db.commit() # type: ignore
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/logs")
def admin_logs():
    if "user" not in session or session.get("role") != "admin":
        return redirect(url_for("admin_login"))
    # This route is disabled as per user request. Redirect to the main dashboard.
    return redirect(url_for("admin_dashboard"))

# ================= USER SETTINGS =================
@app.route("/settings", methods=["GET", "POST"])
def user_settings():
    if "user" not in session:
        return redirect(url_for("login"))
    
    db = get_db()
    c = db.cursor()
    user_email = session["user"]
    
    # Get user info
    if 'DATABASE_URL' in os.environ:
        c.execute("SELECT first_name, last_name, email FROM users WHERE email=%s", (user_email,))
    else:
        c.execute("SELECT first_name, last_name, email FROM users WHERE email=?", (user_email,))
    user_info = c.fetchone()
    
    # Get or create settings
    if 'DATABASE_URL' in os.environ:
        c.execute("SELECT show_in_community, allow_peer_messages, language FROM user_settings WHERE user_email=%s", (user_email,))
    else:
        c.execute("SELECT show_in_community, allow_peer_messages, language FROM user_settings WHERE user_email=?", (user_email,))
    settings = c.fetchone()
    
    if not settings:
        # Create default settings for existing users
        if 'DATABASE_URL' in os.environ:
            c.execute("INSERT INTO user_settings (user_email) VALUES (%s)", (user_email,))
        else:
            c.execute("INSERT INTO user_settings (user_email) VALUES (?)", (user_email,))
        db.commit()
        settings = {"show_in_community": 1, "allow_peer_messages": 1, "language": "tagalog"}
    
    success_msg = None
    error_msg = None
    
    if request.method == "POST":
        action = request.form.get("action", "")
        
        if action == "save_settings":
            show_community = 1 if request.form.get("show_in_community") else 0
            allow_peer = 1 if request.form.get("allow_peer_messages") else 0
            language = request.form.get("language", "tagalog")
            
            if language not in ["tagalog", "waray"]:
                language = "tagalog"
            
            if 'DATABASE_URL' in os.environ:
                c.execute("UPDATE user_settings SET show_in_community=%s, allow_peer_messages=%s, language=%s WHERE user_email=%s",
                          (show_community, allow_peer, language, user_email))
            else:
                c.execute("UPDATE user_settings SET show_in_community=?, allow_peer_messages=?, language=? WHERE user_email=?",
                          (show_community, allow_peer, language, user_email))
            db.commit()
            
            # Update session language
            session["language"] = language
            settings = {"show_in_community": show_community, "allow_peer_messages": allow_peer, "language": language}
            success_msg = "Settings saved successfully!"
        
        elif action == "change_password":
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")
            
            if not current_password or not new_password or not confirm_password:
                error_msg = "All password fields are required."
            elif len(new_password) < 6:
                error_msg = "New password must be at least 6 characters long."
            elif new_password != confirm_password:
                error_msg = "New passwords do not match."
            else:
                # Verify current password
                if 'DATABASE_URL' in os.environ:
                    c.execute("SELECT password FROM users WHERE email=%s", (user_email,))
                else:
                    c.execute("SELECT password FROM users WHERE email=?", (user_email,))
                user_row = c.fetchone()
                
                if user_row and check_password_hash(user_row['password'], current_password):
                    hashed_password = hash_password(new_password)
                    if 'DATABASE_URL' in os.environ:
                        c.execute("UPDATE users SET password=%s WHERE email=%s", (hashed_password, user_email))
                    else:
                        c.execute("UPDATE users SET password=? WHERE email=?", (hashed_password, user_email))
                    db.commit()
                    success_msg = "Password changed successfully!"
                else:
                    error_msg = "Current password is incorrect."
    
    return render_template("settings.html", 
                           user=user_info, 
                           settings=settings,
                           success_msg=success_msg,
                           error_msg=error_msg)

# ---- AUTO-INIT FOR PRODUCTION (Gunicorn) ----
# When running with gunicorn, the `if __name__=="__main__"` block below won't execute.
# We need to initialize the database at module load time for production.
# Using `CREATE TABLE IF NOT EXISTS` makes this safe to call multiple times.
if os.environ.get("RENDER") or os.environ.get("FLASK_ENV") == "production":
    with app.app_context():
        app.logger.info("Production environment detected. Initializing database...")
        init_db()
        preload_quotes()

# ---- RUN APP ----
if __name__=="__main__":
    # This block is now for DEVELOPMENT ONLY.
    # For production, use a WSGI server like Waitress by running `python run.py`.
    with app.app_context():
        print("Initializing database for development...")
        init_db()
        preload_quotes()
    print("Starting development server on http://127.0.0.1:5000")
    # The debug=True flag enables auto-reloading and a debugger. NEVER use in production.
    app.run(host="127.0.0.1", port=5000, debug=True)
