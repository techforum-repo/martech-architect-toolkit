"""The author sign-in as the main way to authenticate AEM lookups."""

import unittest
from unittest.mock import Mock, patch

from web_inspector import aem_lookup, aem_mock, mock_scan
from web_inspector.investigation import environment_auth, lookup_aem_page, needs_sign_in, run_investigation

ENVIRONMENT = {"id": "env_real", "name": "Stage", "author_base": "https://author-p1-e2.adobeaemcloud.com"}
MAPPING = dict(aem_mock.MAPPING, environment_id="env_real")
SESSION = {"cookies": [
    {"name": "login-token", "value": "abc", "domain": "author-p1-e2.adobeaemcloud.com"},
    {"name": "affinity", "value": "x", "domain": ".adobeaemcloud.com"},
    {"name": "ims_sid", "value": "secret-ims", "domain": ".adobelogin.com"},  # another site: never sent
]}


def response(status, payload=None):
    result = Mock(status_code=status)
    result.json.return_value = payload or {}
    result.raise_for_status.side_effect = None
    return result


class SessionAuthTests(unittest.TestCase):
    def test_only_author_cookies_are_used(self):
        self.assertEqual(aem_lookup.session_auth(ENVIRONMENT, SESSION),
                         {"cookies": {"login-token": "abc", "affinity": "x"}})
        self.assertIsNone(aem_lookup.session_auth(ENVIRONMENT, None))
        self.assertIsNone(aem_lookup.session_auth(ENVIRONMENT, {"cookies": SESSION["cookies"][2:]}))

    @patch("web_inspector.aem_client.requests.request")
    def test_cookies_sent_without_bearer_header(self, request):
        request.return_value = response(200, {"jcr:title": "Home"})
        page = aem_lookup.verify_page(ENVIRONMENT, "/content/site/en", aem_lookup.session_auth(ENVIRONMENT, SESSION))
        self.assertEqual(page["status"], "found")
        kwargs = request.call_args.kwargs
        self.assertEqual(kwargs["cookies"], {"login-token": "abc", "affinity": "x"})
        self.assertNotIn("Authorization", kwargs["headers"])
        self.assertFalse(kwargs["allow_redirects"])

    @patch("web_inspector.aem_client.requests.request")
    def test_expired_sign_in_redirect_says_sign_in_again(self, request):
        request.return_value = response(302)
        page = aem_lookup.verify_page(ENVIRONMENT, "/content/site/en", {"cookies": {"login-token": "old"}})
        self.assertEqual(page["status"], "error")
        self.assertIn("Sign in again", page["message"])

    def test_no_auth_is_refused_before_sending(self):
        with patch("web_inspector.aem_client.requests.request") as request:
            page = aem_lookup.verify_page(ENVIRONMENT, "/content/site/en", None)
        request.assert_not_called()
        self.assertEqual((page["status"], page["message"]), ("error", "Not signed in to AEM"))


@patch("web_inspector.token_store.get_token", return_value=None)
class EnvironmentAuthTests(unittest.TestCase):
    def test_sign_in_preferred_over_token(self, _):
        identity = "env_real|" + ENVIRONMENT["author_base"]
        auth = environment_auth(ENVIRONMENT, {identity: "a-token"}, {"env_real": SESSION})
        self.assertEqual((auth["method"], auth["auth"]["cookies"]["login-token"]), ("sign-in", "abc"))
        auth = environment_auth(ENVIRONMENT, {identity: "a-token"}, {})
        self.assertEqual((auth["method"], auth["auth"]), ("token", "a-token"))

    def test_nothing_configured_asks_to_sign_in(self, _):
        auth = environment_auth(ENVIRONMENT, {}, {})
        self.assertEqual((auth["auth"], auth["message"]), (None, "Not signed in to AEM"))

    @patch("web_inspector.aem_client.requests.request")
    def test_sign_in_after_scan_reruns_only_aem(self, request, _):
        result = run_investigation(mock_scan.PAGE, [MAPPING], [ENVIRONMENT], mock=True)
        self.assertTrue(needs_sign_in(result))
        self.assertIsNone(result["aem_page"])
        request.assert_not_called()

        browser_before = result["browser"]
        request.return_value = response(200, {"jcr:title": "Products"})
        lookup_aem_page(result, ui_sessions={"env_real": SESSION})
        self.assertEqual(result["stages"]["aem"]["status"], "complete")
        self.assertEqual(result["aem_page"]["content_path"], "/content/example/us/en/products")
        self.assertIs(result["browser"], browser_before)  # the page wasn't scanned again
        self.assertFalse(needs_sign_in(result))

    @patch("web_inspector.aem_client.requests.request")
    def test_expired_session_is_flagged(self, request, _):
        result = run_investigation(mock_scan.PAGE, [MAPPING], [ENVIRONMENT], mock=True)
        request.return_value = response(302)
        lookup_aem_page(result, ui_sessions={"env_real": SESSION})
        self.assertTrue(needs_sign_in(result))


if __name__ == "__main__":
    unittest.main()
