import unittest
from unittest.mock import Mock, patch

import requests

from web_inspector import aem_lookup, aem_mock
from web_inspector.aem_client import AEMSecurityError, validate_request

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
            "/content/site/en/page.infinity.json",
        ):
            with self.subTest(path=path):
                with self.assertRaises(AEMSecurityError):
                    validate_request("GET", AUTHOR + path, ORIGINS)


class TestMockLookups(unittest.TestCase):

    def setUp(self):
        # The sample environment is always answered from sample data.
        self.environment = aem_mock.ENVIRONMENT

    def test_verify_existing_page(self):
        result = aem_lookup.verify_page(
            self.environment, "/content/example/us/en/products", "t"
        )
        self.assertEqual(result["status"], "found")
        self.assertEqual(result["title"], "Products")

    def test_title_component_found_by_its_exact_title(self):
        # Even when full-text search doesn't find it, a component whose
        # jcr:title is the term (punctuation around it ignored) is a hit.
        page = {"content_path": "/content/example/us/en/products", "template": ""}
        results = aem_lookup.search_page_scope(self.environment, page, "Tracking embed..", "t")
        titles = next(r for r in results if r["scope"] == "This page: titles")
        [hit] = titles["hits"]
        self.assertTrue(hit["node_path"].endswith("/root/container/embed"))
        self.assertEqual(hit["match"], {"kind": "text", "property": "jcr:title"})

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
        self.assertEqual(results["/content"]["total"], 3)
        self.assertEqual(results["/conf"]["total"], 1)
        self.assertEqual(results["/apps"]["status"], "not_found")
        self.assertEqual(
            results["/content"]["hits"][0]["page_path"],
            "/content/example/us/en/products",
        )


class TestRealModeErrors(unittest.TestCase):

    def response(self, status):
        response = Mock()
        response.status_code = status
        if status >= 400:
            response.raise_for_status.side_effect = requests.HTTPError(response=response)
        return response

    @patch("web_inspector.aem_client.requests.request")
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

    @patch("web_inspector.aem_client.requests.request")
    def test_redirect_reported_not_followed(self, request):
        request.return_value = self.response(300)
        result = aem_lookup.search_references(
            ENVIRONMENT, "x", "t", roots=("/content",)
        )[0]
        self.assertEqual(result["status"], "error")
        self.assertIn("Sign in again", result["message"])  # a redirect means AEM's sign-in page
        self.assertFalse(request.call_args.kwargs["allow_redirects"])

    @patch("web_inspector.aem_client.requests.request")
    def test_connection_failure(self, request):
        request.side_effect = requests.ConnectionError()
        result = aem_lookup.find_vanity(ENVIRONMENT, "/promo", "t")
        self.assertEqual(result["status"], "error")
        self.assertIn("Connection failed", result["message"])


if __name__ == "__main__":
    unittest.main()


class TestPageScope(unittest.TestCase):
    def setUp(self):
        self.environment = aem_mock.ENVIRONMENT
        self.page = aem_lookup.verify_page(self.environment, "/content/example/us/en/products", "t")

    def search(self, term="tracking.example.com", folders=("/apps/example",)):
        return {e["scope"]: e for e in aem_lookup.search_page_scope(self.environment, self.page, term, "t", folders)}

    def test_scopes_and_hits(self):
        results = self.search()
        self.assertEqual(list(results), ["This page", "Experience fragment", "Inherited from parent pages",
                                         "Page template", "Site policies", "Site code"])
        self.assertEqual(results["This page"]["root"], "/content/example/us/en/products/jcr:content")
        self.assertEqual(results["This page"]["total"], 1)
        self.assertEqual(results["Experience fragment"]["root"],
                         "/content/experience-fragments/example/us/en/site/footer/master")
        self.assertEqual(results["Experience fragment"]["total"], 1)
        inherited = results["Inherited from parent pages"]["hits"]
        self.assertEqual([(h["page_path"], h["resource_type"]) for h in inherited],
                         [("/content/example/us/en", "property analyticsTrackingDomain")])
        self.assertEqual(results["Site policies"]["root"], "/conf/example/settings/wcm/policies")
        self.assertEqual(results["Site policies"]["total"], 1)

    def test_page_scope_excludes_other_pages(self):
        # The whole-repository search also finds nodes the page doesn't use; page scope must not.
        everything = {h["node_path"] for e in aem_lookup.search_references(self.environment, "tracking.example.com", "t")
                      for h in e["hits"]}
        scoped = {h["node_path"] for e in self.search().values() for h in e["hits"]}
        self.assertTrue(scoped)
        self.assertTrue(all(p.startswith(("/content/example/us/en/products/", "/content/experience-fragments/",
                                          "/content/example/us/en/jcr:content", "/conf/example/"))
                            for p in scoped), scoped)
        self.assertLessEqual(len(scoped - everything), 1)  # only the inherited property is extra
        self.assertIn("/content/example/us/en/campaigns/spring-sale/jcr:content/root/embed", everything)
        self.assertNotIn("/content/example/us/en/campaigns/spring-sale/jcr:content/root/embed", scoped)

    def test_ancestors(self):
        self.assertEqual(aem_lookup._ancestors("/content/site/us/en/products"),
                         ["/content/site", "/content/site/us", "/content/site/us/en"])

    def test_operation_is_restricted(self):
        url = aem_lookup.querybuilder_url(self.environment, [
            ("path", "/content"), ("property", "x"), ("property.operation", "like")])
        with self.assertRaises(AEMSecurityError):
            validate_request("GET", url, {("https", "author-p00000-e000000.adobeaemcloud.com")})
