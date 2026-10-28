import unittest

from web_inspector.detection import (
    consent_violations,
    detect_technologies,
    domain_summary,
    is_first_party,
    technology_for_url,
)


def names(requests=(), scripts=(), page_globals=()):
    return {t["technology"] for t in detect_technologies(
        [{"url": u} for u in requests], list(scripts), list(page_globals))}


class DetectionTests(unittest.TestCase):
    def test_no_substring_false_positives(self):
        # The old substring signatures matched all of these.
        self.assertEqual(names(scripts=[
            "https://www.example.com/js/chat.js",          # "at.js"
            "https://www.example.com/js/format.js",        # "at.js"
            "https://www.example.com/launch-campaign.js",  # "launch-"
            "https://www.example.com/api/delivery-api/x",  # "delivery-api"
            "https://cdnjs.cloudflare.com/ajax/libs/jquery.js",
        ]), set())

    def test_adobe_signatures(self):
        self.assertEqual(names(requests=[
            "https://assets.adobedtm.com/a/b/launch-123.min.js",
            "https://edge.adobedc.net/ee/v1/interact?configId=x",
            "https://example.tt.omtrdc.net/rest/v1/delivery",
            "https://www.example.com/scripts/at.js",
            "https://example.sc.omtrdc.net/b/ss/rsid/1/JS-2.0",
        ]), {"Adobe Tags", "Adobe Experience Platform Web SDK", "Adobe Target", "Adobe Analytics"})

    def test_global_means_confirmed(self):
        result = detect_technologies([], [], ["alloy"])
        self.assertEqual(result[0]["technology"], "Adobe Experience Platform Web SDK")
        self.assertTrue(result[0]["confidence"].startswith("Confirmed"))
        loaded_only = detect_technologies([{"url": "https://edge.adobedc.net/ee/v1/interact"}], [], [])
        self.assertTrue(loaded_only[0]["confidence"].startswith("Observed"))

    def test_tag_manager_lookup(self):
        self.assertEqual(technology_for_url("https://www.googletagmanager.com/gtm.js?id=GTM-1",
                                            tag_managers_only=True).name, "Google Tag Manager")
        self.assertIsNone(technology_for_url("https://connect.facebook.net/en_US/fbevents.js",
                                             tag_managers_only=True))

    def test_first_party(self):
        self.assertTrue(is_first_party("assets.example.com", "www.example.com"))
        self.assertTrue(is_first_party("example.com", "www.example.com"))
        self.assertFalse(is_first_party("example.com.evil.net", "www.example.com"))
        self.assertFalse(is_first_party("notexample.com", "www.example.com"))

    def test_domain_summary_totals(self):
        rows = domain_summary([
            {"url": "https://edge.adobedc.net/a", "domain": "edge.adobedc.net", "bytes": 100,
             "duration_ms": 10, "phase": "before_consent"},
            {"url": "https://edge.adobedc.net/b", "domain": "edge.adobedc.net", "bytes": 50,
             "duration_ms": 5, "phase": "after_consent", "failed": "net::ERR_BLOCKED"},
            {"url": "https://www.example.com/", "domain": "www.example.com", "bytes": 999},
        ], "www.example.com")
        third = rows[0]
        self.assertEqual(third["domain"], "edge.adobedc.net")
        self.assertEqual((third["requests"], third["bytes"], third["total_ms"]), (2, 150, 15))
        self.assertEqual((third["before_consent"], third["failed"]), (1, 1))
        self.assertEqual(third["technology"], "Adobe Experience Platform Web SDK")
        self.assertEqual([d["domain"] for d in consent_violations(rows)], ["edge.adobedc.net"])
        self.assertTrue(rows[-1]["first_party"])

    def test_tag_manager_before_consent_is_expected(self):
        rows = domain_summary([{"url": "https://assets.adobedtm.com/x/launch-1.min.js",
                                "domain": "assets.adobedtm.com", "phase": "before_consent"}], "www.example.com")
        self.assertEqual(consent_violations(rows), [])


if __name__ == "__main__":
    unittest.main()
