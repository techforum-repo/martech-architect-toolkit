import unittest
from unittest.mock import patch

from web_inspector.url_safety import validate_public_url

ALLOWED = {"www.example.com"}


def resolves_to(address):
    return patch("web_inspector.url_safety.socket.getaddrinfo",
                 return_value=[(None, None, None, None, (address, 443))])


class UrlSafetyTests(unittest.TestCase):
    def test_public_allowed(self):
        with resolves_to("93.184.215.14"):
            self.assertEqual(validate_public_url("https://www.example.com/a", ALLOWED), "www.example.com")

    def test_private_address_rejected(self):
        for address in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254"):
            with self.subTest(address=address), resolves_to(address):
                with self.assertRaises(ValueError):
                    validate_public_url("https://www.example.com/a", ALLOWED)

    def test_unapproved_or_unsafe_urls_rejected(self):
        for url in ("https://unapproved.example.com", "http://www.example.com",
                    "https://user:pw@www.example.com", "https://www.example.com:8443/"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_public_url(url, ALLOWED)


if __name__ == "__main__":
    unittest.main()
