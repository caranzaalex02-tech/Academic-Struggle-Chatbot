import os
import unittest


TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "templates",
    "index.html",
)


class FrontendRenderTests(unittest.TestCase):
    """Regression tests para sa renderBotReply() sa templates/index.html.

    Dati, pini-join ng renderer ang mga linya gamit ang "<br>" BAGO i-escape,
    kaya lumalabas ang literal na "&lt;br&gt;" sa chat bubble ng user. Dapat
    laging i-escape ang bawat linya muna bago ang pagdagdag ng line break.
    """

    @classmethod
    def setUpClass(cls):
        with open(TEMPLATE_PATH, encoding="utf-8") as fh:
            cls.source = fh.read()

    def test_paragraph_lines_are_escaped_before_br_is_inserted(self):
        # Ang maling pattern: i-e-escape ang kabuuang string na may nakakabit na <br>
        self.assertNotIn('inlineFormat(seg.lines.join("<br>"))', self.source)
        self.assertNotIn('inlineFormat(lines.join("<br>"))', self.source)
        # Ang tamang pattern: i-escape ang bawat linya, saka i-join ng <br>
        self.assertIn('seg.lines.map(inlineFormat).join("<br>")', self.source)

    def test_renderer_converts_raw_br_with_attributes_to_newline(self):
        # Dapat kahitin ang <br class="x"> o <br/> ay nagiging newline
        self.assertIn(r"<br\b[^>]*>", self.source)

    def test_renderer_decodes_html_entities_before_stripping_tags(self):
        # Dapat i-decode muna ang &lt;br&gt; bago alisin ang mga HTML tag
        self.assertIn("&lt;/gi", self.source)
        self.assertIn("&gt;/gi", self.source)

    def test_renderer_strips_remaining_html_tags_before_escaping(self):
        # Walang anumang HTML tag ang dapat makapasok nang hindi na-escape
        self.assertIn(r"<[^>]+>/g", self.source)


LANDING_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "templates",
    "landing.html",
)


class LandingPageMobileTests(unittest.TestCase):
    """Dapat nakikita at madaling gamitin ang landing page sa Android/mobile."""

    @classmethod
    def setUpClass(cls):
        with open(LANDING_PATH, encoding="utf-8") as fh:
            cls.source = fh.read()
        # Para sa CSS checks: tanggalin ang spaces para pare-pareho ang format
        cls.compact = cls.source.replace(" ", "").replace("\n", "")

    def test_landing_page_has_mobile_viewport_meta(self):
        self.assertIn('name="viewport"', self.source)
        self.assertIn("width=device-width", self.source)

    def test_landing_page_has_mobile_media_queries(self):
        self.assertIn("@media", self.source)
        self.assertIn("@media(max-width:768px)", self.compact)
        self.assertIn("@media(max-width:480px)", self.compact)

    def test_mobile_uses_scroll_background_not_fixed(self):
        # Ang background-attachment:fixed ay hindi maayos sa Android/iOS
        self.assertIn("background-attachment:scroll", self.compact)

    def test_mobile_buttons_are_full_width_and_tappable(self):
        # Nakahiga (stacked) at malalaki ang button sa maliliit na screen
        self.assertIn("flex-direction:column", self.compact)
        self.assertIn(".btn{justify-content:center", self.compact)


if __name__ == "__main__":
    unittest.main()
