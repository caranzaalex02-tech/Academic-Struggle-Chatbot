import os
import tempfile
import unittest

# Dapat naka-set MUNO bago i-import ang app module — dito nakadepende ang
# DATABASE global sa import time. Route tests lang ito, hindi tumatago ng DB.
os.environ.setdefault(
    "MENTALHEALTHWEB_DB",
    os.path.join(tempfile.gettempdir(), "mentalhealthweb_route_test.db"),
)

import app as app_module  # noqa: E402


class LandingAlwaysFirstTests(unittest.TestCase):
    """Ang landing page ang laging unang bubungad sa pag-open ng link —
    hindi login page, kahit pa naka-login o naka-logout ang user."""

    @classmethod
    def setUpClass(cls):
        app_module.app.config["TESTING"] = True
        cls.client = app_module.app.test_client()

    def setUp(self):
        # Malinis na session bawat test para hindi mag-overlap
        with self.client.session_transaction() as sess:
            sess.clear()

    def _log_in_session(self):
        with self.client.session_transaction() as sess:
            sess["user"] = "student@example.com"
            sess["role"] = "student"

    def test_root_shows_landing_for_guests(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Academic Struggle Support System", resp.data)
        self.assertIn(b"Proceed to Login", resp.data)

    def test_root_shows_landing_even_when_logged_in(self):
        # Kahit naka-login, landing page pa rin ang unang bubungad —
        # hindi chatbot at hindi login page.
        self._log_in_session()
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Academic Struggle Support System", resp.data)
        self.assertNotIn(b"chat-box", resp.data)

    def test_protected_page_without_session_redirects_to_landing(self):
        # Dati: login page. Ngayon: landing page.
        for path in ("/chatbot", "/community", "/settings"):
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 302, path)
            self.assertTrue(
                resp.headers["Location"].endswith("/"),
                f"{path} -> {resp.headers['Location']} (dapat landing '/')",
            )

    def test_logout_redirects_to_landing_not_login(self):
        self._log_in_session()
        resp = self.client.get("/logout")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers["Location"].endswith("/"))
        # Tiyaking walang natirang session pagkatapos ng logout
        with self.client.session_transaction() as sess:
            self.assertNotIn("user", sess)

    def test_login_redirects_already_logged_in_user_to_chatbot(self):
        # Kapag naka-login na at pinindot ang "Proceed to Login",
        # hindi na ipapakita ang login form — diretso chatbot.
        self._log_in_session()
        resp = self.client.get("/login")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers["Location"].endswith("/chatbot"))

    def test_login_page_still_shows_for_guests(self):
        # Nasa landing page ang "Proceed to Login" — dapat buksan ang form.
        resp = self.client.get("/login")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"password", resp.data.lower())


if __name__ == "__main__":
    unittest.main()
