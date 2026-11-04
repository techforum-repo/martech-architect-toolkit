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

    def test_featured_image_goes_to_page_properties(self):
        analysis = {"aem_references": [{"scope": "This page", "hits": [
            hit("x", "path", "fileReference") | {"node_path": PAGE + "/jcr:content/cq:featuredimage",
                                                 "resource_type": "core/wcm/components/image/v3/image"}]}]}
        [target] = _screenshot_targets({"aem_page": {"content_path": PAGE}}, analysis)
        self.assertEqual((target["kind"], target["path"]), ("page", PAGE))

    def test_multifield_item_opens_the_component_holding_it(self):
        item = PAGE + "/jcr:content/root/teaser/actions/item0"
        analysis = {"aem_references": [{"scope": "This page", "hits": [
            hit("x", "text", "link") | {"node_path": item, "resource_type": ""},
            hit("x", "text", "x") | {"node_path": "/content/dam/site/a.jpg/jcr:content/metadata", "resource_type": ""},
        ]}]}
        [target] = _screenshot_targets({"aem_page": {"content_path": PAGE}}, analysis)
        self.assertEqual((target["kind"], target["path"], target["parent_fallback"]), ("component", item, True))
        self.assertIn("Component holding", target["title"])


if __name__ == "__main__":
    unittest.main()


class ComponentNameTests(unittest.TestCase):
    def test_readable_names(self):
        from web_inspector.ui.inspect_page import component_name
        self.assertEqual(component_name("core/wcm/components/title/v3/title"), "Title component")
        self.assertEqual(component_name("site/components/title/v3"), "Title component")
        self.assertEqual(component_name("site/components/hero-banner"), "Hero banner component")
