import unittest

from web_inspector import mock_scan
from web_inspector.attribution import investigate


class AttributionTests(unittest.TestCase):
    def setUp(self):
        self.scan = mock_scan.sample()

    def test_requests_grouped_by_tag_manager(self):
        findings = investigate(self.scan, "tracking.example.com")
        self.assertEqual(len(findings), 1)  # two requests (redirect hop + pixel), one finding
        self.assertEqual(findings[0]["source"], "Adobe Tags")
        self.assertEqual(findings[0]["requests"], 2)

    def test_before_consent_is_called_out(self):
        finding = investigate(self.scan, "googletagmanager.com/gtag")[0]
        self.assertIn("before consent", finding["explanation"])

    def test_direct_script_and_inline(self):
        sources = {f["source"] for f in investigate(self.scan, "cookielaw.org")}
        self.assertIn("HTML script element", sources)
        sources = {f["source"] for f in investigate(self.scan, "adobeDataLayer")}
        self.assertEqual(sources, {"Inline JavaScript"})

    def test_not_found(self):
        self.assertEqual(investigate(self.scan, "nothing-like-this")[0]["source"], "Not found")
        self.assertEqual(investigate(self.scan, "  "), [])


if __name__ == "__main__":
    unittest.main()
