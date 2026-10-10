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
        # Kombinadong page na ngayon: nasa mismong page na ang login form
        # sa kanang side, kaya wala nang hiwalay na "Proceed to Login" o
        # "Create Account" na button sa landing side.
        self.assertIn(b"login-panel", resp.data)
        self.assertIn(b'name="password"', resp.data)
        self.assertNotIn(b"Proceed to Login", resp.data)

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


class EssuGuiuanEmailGateTests(unittest.TestCase):
    """ESSU-Guiuan students LANG (@essu.edu.ph) ang puwedeng mag-register.

    Ang gate ay naka-validate BAGO pa maabot ang DB insert, kaya kapag
    tinanggihan ang email, walang user na naidagdag at walang email na naipadala.
    """

    @classmethod
    def setUpClass(cls):
        # Iwasang magpadala ng totoong email habang nagte-test.
        os.environ.setdefault("EMAIL_BACKEND", "console")
        app_module.app.config["TESTING"] = True
        cls.client = app_module.app.test_client()
        # Siguraduhing may `users` table sa test DB para gumana ang verify queries.
        with app_module.app.app_context():
            app_module.init_db()

    def setUp(self):
        with self.client.session_transaction() as sess:
            sess.clear()

    def _valid_form(self, email):
        return {
            "first_name": "Juan",
            "last_name": "Dela Cruz",
            "email": email,
            "password": "strongpassword123",
            "confirm_password": "strongpassword123",
            "student_id": "23-0768",
            "age": "20",
            "gender": "Male",
            "course": "BSIT",
            "accept_terms": "yes",
        }

    def test_non_essu_email_is_rejected(self):
        resp = self.client.post("/register", data=self._valid_form("juan@gmail.com"))
        self.assertEqual(resp.status_code, 200)  # buo ulit ang form, may error
        self.assertIn(b"ESSU-Guiuan", resp.data)

    def test_non_essu_email_is_not_inserted(self):
        email = "outsider@gmail.com"
        self.client.post("/register", data=self._valid_form(email))
        # get_db() ay nangangailangan ng application context.
        with app_module.app.app_context():
            db = app_module.get_db()
            c = db.cursor()
            c.execute("SELECT id FROM users WHERE email = ?", (email,))
            self.assertIsNone(c.fetchone())

    def test_essu_email_passes_the_domain_gate(self):
        # Tamang @essu.edu.ph domain ay dapat MAKALAMPAS sa gate. Upang hindi
        # ma-abot ang DB insert/email, ginawang invalid ang student_id (isang
        # validation na nasa PAGKATAPOS ng gate) — kaya lumalabas ang ibang
        # error, HINDI ang ESSU-Guiuan rejection.
        form = self._valid_form("juan@essu.edu.ph")
        form["student_id"] = "bad"
        resp = self.client.post("/register", data=form)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(b"Only ESSU-Guiuan students can register", resp.data)


if __name__ == "__main__":
    unittest.main()
