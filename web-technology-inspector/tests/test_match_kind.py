"""How a Search AEM hit matched: AEM's full-text search matches words, so
a phrase can also hit the words of a path, e.g. an image's file name."""

import unittest

from web_inspector.aem_lookup import match_kind


class MatchKindTests(unittest.TestCase):
    def test_text_in_a_property(self):
        self.assertEqual(match_kind({"jcr:title": "Featured stories"}, "Featured stories.."),
                         {"kind": "text", "property": "jcr:title"})

    def test_rich_text(self):
        self.assertEqual(match_kind({"text": "<p>Featured&nbsp;<b>stories</b></p>"}, "featured stories")["kind"],
                         "text")

    def test_words_in_another_order(self):
        self.assertEqual(match_kind({"jcr:title": "Stories we featured"}, "featured stories")["kind"], "words")

    def test_only_an_image_file_name_is_a_path_match(self):
        teaser = {"fileReference": "/content/dam/site/featured-stories.jpg", "sling:resourceType": "site/teaser"}
        self.assertEqual(match_kind(teaser, "Featured stories.."),
                         {"kind": "path", "property": "fileReference"})

    def test_text_beats_a_path(self):
        node = {"fileReference": "/content/dam/featured-stories.jpg", "jcr:title": "Featured stories"}
        self.assertEqual(match_kind(node, "featured stories")["property"], "jcr:title")

    def test_nothing_on_the_node_itself(self):
        self.assertEqual(match_kind({"sling:resourceType": "site/container"}, "featured stories")["kind"],
                         "indirect")

    def test_a_domain_in_a_script_is_text(self):
        node = {"analyticsJS": "<script src='https://www.googletagmanager.com/gtm.js'></script>"}
        self.assertEqual(match_kind(node, "www.googletagmanager.com")["kind"], "text")


if __name__ == "__main__":
    unittest.main()
