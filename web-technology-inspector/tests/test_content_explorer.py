import unittest

from modules.content_explorer import (
    inspect_tree,
    component_inventory,
    page_properties,
    find_matches,
    compare_scans
)


class ContentExplorerTests(unittest.TestCase):

    def setUp(self):
        self.data = {
            "jcr:content": {
                "jcr:title": "Example",
                "trackingId": "ABC123",
                "root": {
                    "component": {
                        "sling:resourceType":
                            "example/components/tracking",
                        "trackingCode": "XYZ"
                    }
                }
            }
        }

    def test_page_properties(self):
        props = page_properties(self.data)
        self.assertEqual(
            props["trackingId"], "ABC123"
        )

    def test_recursive_search(self):
        matches = find_matches(
            self.data, "XYZ"
        )
        self.assertEqual(len(matches), 1)

    def test_component_inventory(self):
        self.assertEqual(
            len(component_inventory(self.data)),
            1
        )

    def test_tree(self):
        self.assertTrue(
            len(inspect_tree(self.data)) >= 2
        )

    def test_comparison(self):
        a = {
            "domains": ["a.example"],
            "request_count": 10,
            "script_count": 2
        }
        b = {
            "domains": ["b.example"],
            "request_count": 12,
            "script_count": 3
        }

        diff = compare_scans(a, b)

        self.assertEqual(
            diff["request_change"], 2
        )
        self.assertEqual(
            diff["added_domains"],
            ["b.example"]
        )


if __name__ == "__main__":
    unittest.main()
