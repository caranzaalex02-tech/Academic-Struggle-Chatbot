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


if __name__ == "__main__":
    unittest.main()
