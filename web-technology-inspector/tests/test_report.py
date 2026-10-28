import csv
import io
import unittest

from web_inspector.report import dot_graph, html_report, request_graph, requests_csv


class ReportTests(unittest.TestCase):
    def test_html_is_escaped(self):
        self.assertIn("&lt;script&gt;", html_report({"test": "<script>"}))

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
