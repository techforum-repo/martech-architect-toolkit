"""Which AEM matches are screenshot, and in what order."""

import unittest

from web_inspector.ui.inspect_page import _screenshot_targets

PAGE = "/content/site/en/home"


def hit(node, kind, prop, resource_type="site/components/teaser"):
    return {"node_path": PAGE + "/jcr:content/root/" + node, "page_path": PAGE, "resource_type": resource_type,
            "match": {"kind": kind, "property": prop}}


class TargetTests(unittest.TestCase):
    def test_text_match_first_and_path_matches_still_taken(self):
        analysis = {"aem_references": [
            {"scope": "This page", "hits": [hit("teaser_1", "path", "fileReference"),
                                            hit("teaser_2", "path", "fileReference")]},
            {"scope": "This page: component text",
             "hits": [hit("title", "text", "jcr:title", "site/components/title")]},
        ]}
        targets = _screenshot_targets({"aem_page": {"content_path": PAGE}}, analysis)
        self.assertEqual([t["path"].rsplit("/", 1)[-1] for t in targets], ["title", "teaser_1", "teaser_2"])
        self.assertIn("matched only inside fileReference", targets[1]["title"])
        self.assertNotIn("matched only", targets[0]["title"])


if __name__ == "__main__":
    unittest.main()
