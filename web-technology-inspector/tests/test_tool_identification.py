"""What loaded each technology, its IDs and versions, and labelled domains."""

import unittest

from web_inspector import custom_signatures, mock_scan
from web_inspector.detection import (
    PAGE_HTML,
    detect_technologies,
    domain_summary,
    loaded_by,
    technology_details,
    technology_for_url,
    unidentified_third_parties,
)

LAUNCH = "https://assets.adobedtm.com/a/b/launch-0a1b-staging.min.js"


def request(url, initiator="", initiator_type="script", stack=()):
    return {"url": url, "domain": url.split("/")[2], "initiator_url": initiator, "initiator_type": initiator_type,
            "stack_urls": list(stack), "bytes": 100, "duration_ms": 10, "phase": "page_load", "failed": ""}


class LoadedByTests(unittest.TestCase):
    def test_tag_manager_anywhere_in_the_chain(self):
        vendor = "https://cdn.vendor.com/v.js"
        self.assertEqual(loaded_by(request("https://px.vendor.com/p", vendor, stack=[vendor, LAUNCH])), "Adobe Tags")

    def test_page_html_and_scripts(self):
        self.assertEqual(loaded_by(request(LAUNCH, "https://www.example.com/", "parser")), PAGE_HTML)
        self.assertEqual(loaded_by(request("https://x.com/a", "https://www.example.com/js/app.js")),
                         "Script www.example.com/…/app.js")
        self.assertEqual(loaded_by(request("https://x.com/a", "", "other")), "")

    def test_mock_scan(self):
        browser = mock_scan.sample()
        rows = {t["technology"]: t for t in detect_technologies(
            browser["requests"], browser["scripts"], browser["globals"], browser["page_details"])}
        self.assertEqual(rows["Google Analytics 4"]["loaded_by"], ["Adobe Tags"])
        self.assertEqual(rows["Meta Pixel"]["loaded_by"], ["Adobe Tags"])
        self.assertEqual(rows["Adobe Tags"]["loaded_by"], [PAGE_HTML])
        self.assertIn("Datastream ID: abc", rows["Adobe Experience Platform Web SDK"]["details"])
        self.assertIn("Property: Example.com Web", rows["Adobe Tags"]["details"])


class DetailTests(unittest.TestCase):
    def test_ids_from_urls(self):
        details = technology_details([
            {"url": "https://edge.example.com/ee/irl1/v1/interact?requestId=1&configId=1a2b-3c4d:dev"},
            {"url": "https://example.sc.omtrdc.net/b/ss/rs-global,rs-us/10/JS-2.22.0/s123"},
            {"url": "https://acme.tt.omtrdc.net/rest/v1/delivery?client=acme"},
            {"url": "https://www.googletagmanager.com/gtm.js?id=GTM-AB12CD"},
            {"url": "https://www.facebook.com/tr/?id=123456789&ev=PageView"},
        ], [LAUNCH], {})
        self.assertEqual(details["Adobe Experience Platform Web SDK"], ["Datastream ID: 1a2b-3c4d:dev"])
        self.assertEqual(details["Adobe Analytics"], ["Report suite: rs-global, rs-us"])
        self.assertEqual(details["Adobe Target"], ["Client code: acme"])
        self.assertEqual(details["Adobe Tags"], ["Library environment: Staging"])
        self.assertEqual(details["Google Tag Manager"], ["Container: GTM-AB12CD"])
        self.assertEqual(details["Meta Pixel"], ["Pixel ID: 123456789"])

    def test_versions_from_the_page(self):
        details = technology_details([], [], {"adobe.target.VERSION": "2.11.4", "s_c_il.version": "2.26.0",
                                              "Visitor.version": "5.5.0", "unknown.path": "x"})
        self.assertEqual(details["Adobe Target"], ["at.js version: 2.11.4"])
        self.assertEqual(details["Adobe Analytics"], ["AppMeasurement version: 2.26.0"])
        self.assertEqual(details["Adobe Experience Cloud ID"], ["VisitorAPI version: 5.5.0"])

    def test_first_party_edge_domain_is_the_web_sdk(self):
        tech = technology_for_url("https://edge.example.com/ee/v1/interact?configId=x")
        self.assertEqual(tech.name, "Adobe Experience Platform Web SDK")


class LabelTests(unittest.TestCase):
    def test_label_names_an_unknown_domain_for_later_scans(self):
        requests = [request("https://cdn.unknownvendor.io/tag.js", "https://www.example.com/", "parser"),
                    request("https://www.googletagmanager.com/gtm.js?id=GTM-X", "https://www.example.com/", "parser")]
        unknown = unidentified_third_parties(domain_summary(requests, "www.example.com"))
        self.assertEqual([d["domain"] for d in unknown], ["cdn.unknownvendor.io"])

        custom_signatures.save("unknownvendor.io", "  Unknown   Vendor ", "Advertising")
        self.assertEqual(unidentified_third_parties(domain_summary(requests, "www.example.com")), [])
        [row] = [t for t in detect_technologies(requests, [], []) if t["technology"] == "Unknown Vendor"]
        self.assertEqual((row["category"], row["confidence"]), ("Advertising", "Labelled by you (loaded)"))

        custom_signatures.delete("unknownvendor.io")
        self.assertEqual(len(unidentified_third_parties(domain_summary(requests, "www.example.com"))), 1)

    def test_built_in_signatures_win(self):
        custom_signatures.save("googletagmanager.com", "Something else", "Other")
        self.assertEqual(technology_for_url("https://www.googletagmanager.com/gtm.js").name, "Google Tag Manager")
        names = [t["technology"] for t in detect_technologies(
            [request("https://www.googletagmanager.com/gtm.js?id=GTM-X")], [], [])]
        self.assertEqual(names, ["Google Tag Manager"])

    def test_invalid_labels(self):
        _, errors = custom_signatures.clean("https://x.com/a", "", "Other")
        self.assertEqual(len(errors), 2)
        with self.assertRaises(ValueError):
            custom_signatures.save("not a domain", "Name", "Other")


if __name__ == "__main__":
    unittest.main()
