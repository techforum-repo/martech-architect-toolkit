import tempfile
import unittest
from unittest.mock import patch

from web_inspector import database, mock_scan
from web_inspector.investigation import run_investigation
from web_inspector import aem_mock


def mock_result(consent="accept"):
    return run_investigation(mock_scan.PAGE, [aem_mock.MAPPING], [aem_mock.ENVIRONMENT],
                             mock=True, consent=consent)


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = patch.object(database.settings, "data_dir", folder.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        database.initialize()

    def test_summary_has_no_sensitive_data(self):
        summary = database.summarize(mock_result())
        self.assertIn("Adobe Tags", summary["technologies"])
        # The tag manager and consent tool load before consent by design; GA does not have to.
        self.assertEqual(summary["before_consent_domains"], ["www.googletagmanager.com"])
        self.assertEqual(summary["aem_page"], "/content/example/us/en/products")
        text = str(summary)
        for leaked in ("inline_scripts", "screenshot", "adobeDataLayer = window"):
            self.assertNotIn(leaked, text)

    def test_previous_scan_and_compare(self):
        first = database.save_scan(mock_result(), "accept")
        changed = mock_result()
        changed["technologies"] = [t for t in changed["technologies"] if t["technology"] != "Meta Pixel"]
        changed["domains"].append({"domain": "new.vendor.com", "requests": 1, "bytes": 10,
                                   "first_party": False, "before_consent": 1, "category": ""})
        second = database.save_scan(changed, "accept")

        self.assertIsNone(database.previous_scan(first))
        self.assertEqual(database.previous_scan(second)["id"], first)
        diff = database.compare(database.get_scan(first)["summary"], database.get_scan(second)["summary"])
        self.assertEqual(diff["technologies"]["removed"], ["Meta Pixel"])
        self.assertEqual(diff["domains"]["added"], ["new.vendor.com"])
        self.assertEqual(diff["before_consent_domains"]["added"], ["new.vendor.com"])

    def test_list_scans_newest_first(self):
        ids = [database.save_scan(mock_result(), "accept") for _ in range(3)]
        self.assertEqual([s["id"] for s in database.list_scans(mock_scan.PAGE)], ids[::-1])


if __name__ == "__main__":
    unittest.main()
