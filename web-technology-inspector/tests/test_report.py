import csv
import io
import json
import unittest

from web_inspector import aem_mock, mock_scan
from web_inspector.investigation import analyze_target, run_investigation
from web_inspector.report import build_report, dot_graph, html_report, request_graph, requests_csv


class ReportTests(unittest.TestCase):
    def report(self, target="tracking.example.com"):
        result = run_investigation(mock_scan.PAGE, [aem_mock.MAPPING], [aem_mock.ENVIRONMENT],
                                   mock=True, consent="accept")
        analysis = analyze_target(result, target)
        return build_report(result, analysis["findings"], analysis["aem_references"], target)

    def test_html_report_sections(self):
        page = html_report(self.report())
        for text in ("Web Technology Inspection", "1 third-party domain(s) tracked before consent",
                     "Expected: tag management", "Adobe Experience Platform Web SDK",
                     "/content/example/us/en/products", "How “tracking.example.com” was added",
                     "experience-fragments", "sample data (mock mode)"):
            self.assertIn(text, page)
        self.assertNotIn("<script", page)  # self-contained and inert

    def test_html_is_escaped(self):
        report = self.report(target="<img src=x onerror=alert(1)>")
        report["url"] = "https://www.example.com/<script>alert(1)</script>"
        page = html_report(report)
        self.assertNotIn("<script>alert", page)
        self.assertNotIn("<img src=x", page)
        self.assertIn("&lt;script&gt;", page)

    def test_report_has_no_secrets(self):
        report = self.report()
        text = json.dumps(report, default=str)
        for field in ("inline_scripts", "screenshot", "token", "adobeDataLayer = window"):
            self.assertNotIn(field, text)

    def test_csv_has_one_row_per_request(self):
        text = requests_csv([{"url": "https://a/x", "bytes": 10, "phase": "before_consent"},
                             {"url": "https://b/y, with comma"}])
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["url"], "https://b/y, with comma")

    def test_graph(self):
        edges = request_graph({"requests": [{"url": "https://b", "initiator_url": "https://a"},
                                            {"url": "https://c", "stack_urls": ["https://a"]}]})
        self.assertEqual(edges, [("https://a", "https://b"), ("https://a", "https://c")])
        self.assertIn('"https://a" -> "https://b";', dot_graph(edges))


if __name__ == "__main__":
    unittest.main()
