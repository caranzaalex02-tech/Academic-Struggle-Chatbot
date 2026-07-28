from waitress import serve
from app import app, init_db, preload_quotes  # Import your Flask app instance and setup functions
import os

# Create upload folder if it doesn't exist
UPLOAD_FOLDER = 'static/uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Set secure session cookie settings for production
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)

# It's crucial to initialize the database within the application context before starting the production server.
# This ensures that the database tables are created and seeded before the app handles any requests.
with app.app_context():
    print("Initializing database for production...")
    init_db()
    print("Preloading daily quotes...")
    preload_quotes()

print(f"Starting production server with Waitress on http://0.0.0.0:{os.environ.get('PORT', 8000)}") # type: ignore
serve(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))