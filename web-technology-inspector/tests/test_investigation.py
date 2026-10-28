import unittest
from unittest.mock import patch

from web_inspector import aem_mock, mock_scan
from web_inspector.investigation import analyze_target, run_investigation

MAPPINGS, ENVIRONMENTS = [aem_mock.MAPPING], [aem_mock.ENVIRONMENT]


def run(url=mock_scan.PAGE, **kwargs):
    return run_investigation(url, MAPPINGS, ENVIRONMENTS, mock=True, **kwargs)


class InvestigationTests(unittest.TestCase):
    def test_full_mock_run(self):
        result = run(consent="accept")
        self.assertEqual({s["status"] for s in result["stages"].values()}, {"complete"})
        self.assertEqual(result["aem_page"]["content_path"], "/content/example/us/en/products")
        self.assertIn("Adobe Experience Platform Web SDK", {t["technology"] for t in result["technologies"]})

    def test_vanity_url_outside_prefix(self):
        result = run("https://www.example.com/spring")
        self.assertEqual(result["aem_page"]["content_path"], "/content/example/us/en/campaigns/spring-sale")
        self.assertIn("Vanity", result["aem_page"]["method"])

    def test_unknown_page(self):
        result = run("https://www.example.com/us/en/missing.html")
        self.assertEqual(result["stages"]["aem"]["status"], "not_found")

    def test_unmapped_domain_stops_before_scanning(self):
        result = run("https://www.other.com/")
        self.assertEqual(result["stages"]["mapping"]["status"], "unavailable")
        self.assertIsNone(result["browser"])

    def test_scan_failure_keeps_other_stages(self):
        with patch("web_inspector.investigation.mock_scan.sample", side_effect=RuntimeError("boom")):
            result = run()
        self.assertEqual(result["stages"]["browser"]["status"], "failed")
        self.assertEqual(result["stages"]["aem"]["status"], "complete")

    def test_analyze_target_with_aem_references(self):
        analysis = analyze_target(run(), "tracking.example.com")
        self.assertEqual(analysis["findings"][0]["source"], "Adobe Tags")
        scopes = [r["scope"] for r in analysis["aem_references"]]
        self.assertEqual(scopes[0], "This page")  # page scope is the default
        self.assertIn("Site code", scopes)  # /apps/example, from the page's /etc.clientlibs URLs

        analysis = analyze_target(run(), "tracking.example.com", scope="repository")
        totals = {r["root"]: r["total"] for r in analysis["aem_references"]}
        self.assertEqual(totals, {"/content": 3, "/conf": 1, "/apps": 0})
        self.assertEqual(analyze_target(run(), "x", search_aem=False)["aem_references"], [])


if __name__ == "__main__":
    unittest.main()
