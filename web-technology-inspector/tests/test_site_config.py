import unittest

from web_inspector.site_config import clean_mapping

BASE = dict(name="Stage", domain="stage.example.com", prefix="/us/en", root="/content/site/us/en")


def clean(**change):
    return clean_mapping(**{**BASE, **change})


class CleanMappingTests(unittest.TestCase):
    def test_valid(self):
        values, errors = clean()
        self.assertEqual(errors, [])
        self.assertEqual(values, {"name": "Stage", "published_domain": "stage.example.com",
                                  "published_prefix": "/us/en", "content_root": "/content/site/us/en"})

    def test_pasted_forms_are_accepted(self):
        for domain in ("https://stage.example.com", "stage.example.com/", "https://Stage.Example.com/us/en.html",
                       " stage.example.com ", "stage.example.com/us/en", "https://stage.example.com:443/"):
            with self.subTest(domain=domain):
                values, errors = clean(domain=domain)
                self.assertEqual((errors, values["published_domain"]), ([], "stage.example.com"))
        for prefix, expected in (("us/en", "/us/en"), (" /us/en/ ", "/us/en"), ("", "/"), ("/", "/")):
            with self.subTest(prefix=prefix):
                self.assertEqual(clean(prefix=prefix)[0]["published_prefix"], expected)
        self.assertEqual(clean(root=" /content/site/us/en/ ")[0]["content_root"], "/content/site/us/en")

    def test_specific_errors(self):
        cases = {
            "Website name": dict(name=" "),
            "host name": dict(domain="not a domain"),
            "port": dict(domain="stage.example.com:8443"),
            "passwords": dict(domain="https://user:pw@stage.example.com"),
            "under /content/": dict(root="/content"),
            "under /content/ ": dict(root="/site/us/en"),
            "prefix": dict(prefix="/us/../en"),
        }
        for expected, change in cases.items():
            with self.subTest(case=expected):
                errors = clean(**change)[1]
                self.assertTrue(any(expected.strip() in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
