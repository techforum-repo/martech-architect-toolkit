import unittest
from unittest.mock import patch, Mock

from web_inspector.aem_client import (
    AEMSecurityError,
    validate_request,
    aem_request
)

TEST_URL = (
    "https://author.example.com"
    "/content/example/en/page/jcr:content.json"
)


class TestAEMReadOnly(unittest.TestCase):

    def setUp(self):
        self.origin_patch = patch(
            "web_inspector.aem_client.approved_origins",
            return_value={
                ("https", "author.example.com")
            }
        )
        self.origin_patch.start()
        self.addCleanup(self.origin_patch.stop)

    def test_get_allowed(self):
        self.assertEqual(
            validate_request("GET", TEST_URL),
            "GET"
        )

    def test_head_allowed(self):
        self.assertEqual(
            validate_request("HEAD", TEST_URL),
            "HEAD"
        )

    def test_write_methods_blocked(self):
        for method in (
            "POST", "PUT", "PATCH",
            "DELETE", "COPY", "MOVE"
        ):
            with self.subTest(method=method):
                with self.assertRaises(AEMSecurityError):
                    validate_request(method, TEST_URL)

    def test_external_origin_blocked(self):
        with self.assertRaises(AEMSecurityError):
            validate_request(
                "GET",
                "https://other.example.com"
                "/content/example/jcr:content.json"
            )

    def test_query_parameters_blocked(self):
        with self.assertRaises(AEMSecurityError):
            validate_request(
                "GET",
                TEST_URL + "?operation=delete"
            )

    def test_path_traversal_blocked(self):
        with self.assertRaises(AEMSecurityError):
            validate_request(
                "GET",
                "https://author.example.com"
                "/content/../apps/example/jcr:content.json"
            )

    def test_infinity_json_no_longer_permitted(self):
        with self.assertRaises(AEMSecurityError):
            validate_request(
                "GET",
                "https://author.example.com"
                "/content/example/en/page.infinity.json"
            )

    @patch("web_inspector.aem_client.requests.request")
    def test_write_never_reaches_network(self, request):
        with self.assertRaises(AEMSecurityError):
            aem_request("DELETE", TEST_URL, "test-token")
        request.assert_not_called()

    @patch("web_inspector.aem_client.requests.request")
    def test_redirect_rejected(self, request):
        response = Mock()
        response.status_code = 302
        request.return_value = response

        with self.assertRaises(AEMSecurityError):
            aem_request("GET", TEST_URL, "test-token")

        self.assertFalse(
            request.call_args.kwargs["allow_redirects"]
        )


if __name__ == "__main__":
    unittest.main()
