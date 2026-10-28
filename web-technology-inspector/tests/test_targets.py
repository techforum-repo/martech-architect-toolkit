import unittest

from web_inspector.targets import available_targets


class TargetSelectorTests(unittest.TestCase):

    def test_empty_scan(self):
        self.assertEqual(available_targets({}), [])

    def test_domain_detection(self):
        result = {
            "requests": [
                {
                    "url": "https://tracker.example.com/pixel",
                    "domain": "tracker.example.com"
                }
            ],
            "scripts": []
        }

        targets = available_targets(result)

        values = [item["value"] for item in targets]

        self.assertIn("tracker.example.com", values)

    def test_script_detection(self):
        result = {
            "requests": [],
            "scripts": [
                "https://cdn.example.com/script.js"
            ]
        }

        targets = available_targets(result)

        self.assertEqual(len(targets), 1)

    def test_duplicate_resources(self):
        result = {
            "requests": [
                {
                    "url": "https://cdn.example.com/a.js",
                    "domain": "cdn.example.com"
                },
                {
                    "url": "https://cdn.example.com/a.js",
                    "domain": "cdn.example.com"
                }
            ],
            "scripts": []
        }

        targets = available_targets(result)

        self.assertEqual(len(targets), 2)


if __name__ == "__main__":
    unittest.main()
