import os
import unittest
from unittest.mock import Mock, patch

import requests

from modules import aem_lookup, aem_mock
from modules.aem import AEMSecurityError, validate_request

AUTHOR = "https://author.example.com"
ORIGINS = {("https", "author.example.com")}
ENVIRONMENT = {"id": "env_test", "name": "Test", "author_base": AUTHOR}


class TestQueryBuilderValidation(unittest.TestCase):

    def qb(self, query):
        return AUTHOR + "/bin/querybuilder.json?" + query

    def test_allowlisted_search_is_permitted(self):
        url = aem_lookup.querybuilder_url(ENVIRONMENT, [
            ("path", "/conf"),
            ("fulltext", '"tracking.example.com"'),
            ("p.limit", "20"),
            ("p.hits", "selective"),
            ("p.properties", "jcr:path sling:resourceType"),
        ])
        self.assertEqual(validate_request("GET", url, ORIGINS), "GET")

    def test_page_node_is_permitted(self):
        url = aem_lookup.page_node_url(ENVIRONMENT, "/content/site/en/page")
        self.assertEqual(validate_request("GET", url, ORIGINS), "GET")

    def test_rejected_queries(self):
        cases = {
            "unknown parameter": "path=/content&fulltext=x&orderby=@jcr:score",
            "root outside allowlist": "path=/home/users&fulltext=x",
            "root prefix trick": "path=/contentx&fulltext=x",
            "path traversal": "path=/content/../home&fulltext=x",
            "repeated parameter": "path=/content&path=/home&fulltext=x",
            "limit too high": "path=/content&fulltext=x&p.limit=5000",
            "missing path": "fulltext=x",
            "empty query": "",
        }
        for reason, query in cases.items():
            with self.subTest(reason=reason):
                with self.assertRaises(AEMSecurityError):
                    validate_request("GET", self.qb(query), ORIGINS)

    def test_querybuilder_is_read_only(self):
        with self.assertRaises(AEMSecurityError):
            validate_request("POST", self.qb("path=/content&fulltext=x"), ORIGINS)

    def test_query_still_blocked_on_content_endpoints(self):
        with self.assertRaises(AEMSecurityError):
            validate_request(
                "GET",
                AUTHOR + "/content/site/en/page/jcr:content.json?x=1",
                ORIGINS,
            )

    def test_other_nodes_and_selectors_blocked(self):
        for path in (
            "/content/site/en/page/jcr:content/root.json",
            "/content/site/en/page.json",
            "/apps/site/components/page.infinity.json",
        ):
            with self.subTest(path=path):
                with self.assertRaises(AEMSecurityError):
                    validate_request("GET", AUTHOR + path, ORIGINS)


class TestMockLookups(unittest.TestCase):

    def setUp(self):
        patcher = patch.dict(os.environ, {"MOCK_AEM": "true"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.environment = aem_mock.ENVIRONMENT

    def test_verify_existing_page(self):
        result = aem_lookup.verify_page(
            self.environment, "/content/example/us/en/products", "t"
        )
        self.assertEqual(result["status"], "found")
        self.assertEqual(result["title"], "Products")

    def test_verify_missing_page(self):
        result = aem_lookup.verify_page(
            self.environment, "/content/example/us/en/missing", "t"
        )
        self.assertEqual(result["status"], "not_found")

    def test_vanity_lookup_strips_html(self):
        result = aem_lookup.find_vanity(self.environment, "/spring.html", "t")
        self.assertEqual(result["vanity"], "/spring")
        self.assertEqual(
            result["pages"], ["/content/example/us/en/campaigns/spring-sale"]
        )

    def test_reference_search_per_root(self):
        results = {
            r["root"]: r
            for r in aem_lookup.search_references(
                self.environment, "tracking.example.com", "t"
            )
        }
        self.assertEqual(results["/content"]["total"], 2)
        self.assertEqual(results["/conf"]["total"], 1)
        self.assertEqual(results["/apps"]["status"], "not_found")
        self.assertEqual(
            results["/content"]["hits"][0]["page_path"],
            "/content/example/us/en/products",
        )


class TestRealModeErrors(unittest.TestCase):

    def setUp(self):
        patcher = patch.dict(os.environ, {"MOCK_AEM": ""})
        patcher.start()
        self.addCleanup(patcher.stop)
        origins = patch("modules.aem.approved_origins", return_value=ORIGINS)
        origins.start()
        self.addCleanup(origins.stop)

    def response(self, status):
        response = Mock()
        response.status_code = status
        if status >= 400:
            response.raise_for_status.side_effect = requests.HTTPError(response=response)
        return response

    @patch("modules.aem.requests.request")
    def test_status_messages(self, request):
        for status, expected in (
            (401, "expired"),
            (403, "not allowed"),
            (404, "Not found"),
        ):
            with self.subTest(status=status):
                request.return_value = self.response(status)
                result = aem_lookup.verify_page(ENVIRONMENT, "/content/site/en", "t")
                self.assertIn(expected, result["message"])
                self.assertEqual(result["http_status"], status)

    @patch("modules.aem.requests.request")
    def test_redirect_reported_not_followed(self, request):
        request.return_value = self.response(300)
        result = aem_lookup.search_references(
            ENVIRONMENT, "x", "t", roots=("/content",)
        )[0]
        self.assertEqual(result["status"], "error")
        self.assertIn("Blocked", result["message"])
        self.assertFalse(request.call_args.kwargs["allow_redirects"])

    @patch("modules.aem.requests.request")
    def test_connection_failure(self, request):
        request.side_effect = requests.ConnectionError()
        result = aem_lookup.find_vanity(ENVIRONMENT, "/promo", "t")
        self.assertEqual(result["status"], "error")
        self.assertIn("Connection failed", result["message"])


if __name__ == "__main__":
    unittest.main()
