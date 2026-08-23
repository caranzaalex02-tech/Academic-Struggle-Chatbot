from waitress import serve
from app import app, init_db, preload_quotes  # Import your Flask app instance and setup functions
import os
import socket

# Create upload folder if it doesn't exist
UPLOAD_FOLDER = 'static/uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Set secure session cookie settings for production
is_production = bool(os.environ.get("RENDER") or os.environ.get("HEROKU") or os.environ.get("FLASK_ENV") == "production")
app.config.update(
    SESSION_COOKIE_SECURE=is_production,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PREFERRED_URL_SCHEME='https' if is_production else 'http',
)

# It's crucial to initialize the database within the application context before starting the production server.
# This ensures that the database tables are created and seeded before the app handles any requests.
with app.app_context():
    print("Initializing database...")
    init_db()
    print("Preloading daily quotes...")
    preload_quotes()

port = int(os.environ.get("PORT", 8000))

print("=" * 60)
print("Mental Health Chatbot is running!")
print("Local URL:      http://127.0.0.1:{}".format(port))
try:
    # Try to show the LAN URL so it works on mobile/other devices on the same network
    hostname = socket.gethostname()
    lan_ip = socket.gethostbyname(hostname)
    print("Network URL:    http://{}:{}".format(lan_ip, port))
    print("(Open the Network URL on your phone/other devices on the same Wi-Fi)")
except Exception:
    pass
print("=" * 60)
print("Press CTRL+C to stop the server.")
serve(app, host="0.0.0.0", port=port)