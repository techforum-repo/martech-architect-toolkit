import json
import unittest
from unittest.mock import patch

from web_inspector import aem_mock, mock_scan, site_credentials
from web_inspector.database import summarize
from web_inspector.errors import friendly_error
from web_inspector.investigation import run_investigation
from web_inspector.report import build_report, html_report
from web_inspector.scanner import AuthRequired

LOGIN = {"username": "qa-user", "password": "s3cret-pass"}


class CredentialTests(unittest.TestCase):
    def test_browser_credentials_limited_to_site(self):
        self.assertEqual(site_credentials.browser_credentials("Stage.Example.com", LOGIN), {
            "username": "qa-user", "password": "s3cret-pass",
            "origin": "https://stage.example.com"})
        self.assertIsNone(site_credentials.browser_credentials("stage.example.com", None))

    def test_validation(self):
        self.assertTrue(site_credentials.valid("qa", "pw"))
        for username, password in (("", "pw"), ("qa", ""), ("q:a", "pw")):
            self.assertFalse(site_credentials.valid(username, password))

    def test_session_credentials_win_over_saved(self):
        with patch.object(site_credentials, "load", return_value={"username": "saved", "password": "x"}):
            self.assertEqual(site_credentials.resolve("Stage.example.com", {"stage.example.com": LOGIN}),
                             (LOGIN, "session"))
            self.assertEqual(site_credentials.resolve("stage.example.com", {})[1], "saved")
        with patch.object(site_credentials, "load", side_effect=RuntimeError("no keyring")):
            self.assertEqual(site_credentials.resolve("stage.example.com", {}), (None, ""))

    def test_saved_through_encrypted_token_store(self):
        stored = {}
        with patch.object(site_credentials.token_store, "save_token",
                          side_effect=lambda key, value: stored.update({key["id"]: value})), \
             patch.object(site_credentials.token_store, "get_token", side_effect=lambda key: stored.get(key["id"])):
            site_credentials.save("Stage.Example.com", " qa-user ", "s3cret-pass")
            self.assertEqual(list(stored), ["basic-auth|stage.example.com"])
            self.assertEqual(site_credentials.load("stage.example.com"), LOGIN)

    def test_password_never_in_history_or_reports(self):
        result = run_investigation(mock_scan.PAGE, [aem_mock.MAPPING], [aem_mock.ENVIRONMENT],
                                   mock=True, consent="accept", site_login=LOGIN)
        self.assertTrue(result["site_login"])
        report = build_report(result, [], [])
        for text in (json.dumps(summarize(result)), json.dumps(report, default=str), html_report(report)):
            self.assertNotIn("s3cret-pass", text)
            self.assertNotIn("qa-user", text)

    def test_friendly_errors(self):
        missing = friendly_error(AuthRequired("HTTP 401", credentials_sent=False))
        rejected = friendly_error(AuthRequired("HTTP 401", credentials_sent=True))
        self.assertIn("needs a username and password", missing.title)
        self.assertIn("rejected", rejected.title)


if __name__ == "__main__":
    unittest.main()
