"""Runs the real scanner in Chromium against fixture pages served by Playwright
routing, so no network is used. Skipped when the browser isn't installed."""

import unittest

import base64
import datetime
import ssl
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from web_inspector.scanner import BLOCK_PAGE_TITLE, AuthRequired, ScanBlocked, _desktop_user_agent, scan
from web_inspector.site_credentials import browser_credentials

SITE = "https://www.example.test"

PAGE = """<!doctype html><html><head><title>Fixture</title>
<script src="https://vendor.example.net/early.js"></script>
<script>window.adobeDataLayer = [];</script></head>
<body style="height:3000px">
<div id="onetrust-banner-sdk"><button id="onetrust-accept-btn-handler"
  onclick="document.cookie='consent=yes;path=/'; var s=document.createElement('script');
  s.src='https://vendor.example.net/after-consent.js'; document.head.appendChild(s);">Accept</button></div>
<img src="https://vendor.example.net/redirect">
</body></html>"""


def serve(context):
    def handle(route):
        url = route.request.url
        if url == SITE + "/page.html":
            route.fulfill(status=200, content_type="text/html", body=PAGE,
                          headers={"Set-Cookie": "session=1; Path=/"})
        elif url.endswith("/redirect"):
            route.fulfill(status=302, headers={"Location": "https://vendor.example.net/pixel.gif"})
        elif url.endswith(".gif"):
            route.fulfill(status=200, content_type="image/gif", body=b"GIF89a")
        elif url.endswith("/blocked.html"):
            route.fulfill(status=403, content_type="text/html", body="<title>Access Denied</title>")
        else:
            route.fulfill(status=200, content_type="application/javascript", body="window.loaded=1;")
    context.route("**/*", handle)


def browser_available():
    try:
        scan(SITE + "/page.html", settle=1, prepare_context=serve)
        return True
    except Exception as exc:  # noqa: BLE001
        return "Executable doesn't exist" not in str(exc) and _raise(exc)


def _raise(exc):
    raise exc


class ScannerHelperTests(unittest.TestCase):
    def test_user_agent_is_not_headless(self):
        agent = _desktop_user_agent("156.0.8078.4")
        self.assertIn("Chrome/156.0.0.0", agent)
        self.assertNotIn("Headless", agent)

    def test_block_titles(self):
        for title in ("Access Denied", "Attention Required! | Cloudflare", "Just a moment..."):
            self.assertTrue(BLOCK_PAGE_TITLE.search(title))
        self.assertFalse(BLOCK_PAGE_TITLE.search("Products | Example"))


@unittest.skipUnless(browser_available(), "Chromium for Playwright is not installed")
class ScannerBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = scan(SITE + "/page.html", consent="accept", settle=1, prepare_context=serve)

    def by_url(self, suffix):
        return [r for r in self.result["requests"] if r["url"].endswith(suffix)]

    def test_consent_splits_requests(self):
        self.assertEqual(self.result["consent"], {"mode": "accept", "platform": "OneTrust", "accepted": True})
        self.assertEqual(self.by_url("early.js")[0]["phase"], "before_consent")
        self.assertEqual(self.by_url("after-consent.js")[0]["phase"], "after_consent")

    def test_consent_splits_cookies(self):
        before = {c["name"] for c in self.result["cookies_before_consent"]}
        after = {c["name"] for c in self.result["cookies"]}
        self.assertEqual(before, {"session"})
        self.assertEqual(after, {"session", "consent"})

    def test_redirect_hop_is_kept(self):
        hop = self.by_url("/redirect")[0]
        self.assertEqual(hop["status"], 302)
        self.assertEqual(hop["redirected_to"], "https://vendor.example.net/pixel.gif")
        self.assertEqual(self.by_url("pixel.gif")[0]["redirect_from"], "https://vendor.example.net/redirect")

    def test_globals_cookies_and_screenshot(self):
        self.assertIn("adobeDataLayer", self.result["globals"])
        self.assertTrue(self.result["screenshot"].startswith(b"\x89PNG"))
        self.assertNotIn("Headless", self.result["user_agent"])

    def test_mobile_device(self):
        result = scan(SITE + "/page.html", device="mobile", settle=1, prepare_context=serve)
        self.assertIn("Mobile", result["user_agent"])
        self.assertEqual(result["consent"]["mode"], "none")
        self.assertEqual({r["phase"] for r in result["requests"]}, {"page_load"})

    def test_blocked_site(self):
        with self.assertRaises(ScanBlocked):
            scan(SITE + "/blocked.html", settle=1, prepare_context=serve)


EXPECTED_AUTH = "Basic " + base64.b64encode(b"qa-user:s3cret").decode()


class _Handler(BaseHTTPRequestHandler):
    """Stage site behind Basic auth, plus a third-party script host, on one server."""
    seen: list = []

    def do_GET(self):  # noqa: N802 - http.server API
        host = self.headers.get("Host", "").split(":")[0]
        auth = self.headers.get("Authorization")
        type(self).seen.append((host, self.path, auth))
        if host == "stage.example.test":
            if auth != EXPECTED_AUTH:
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="stage"')
                self.end_headers()
                return
            body = b"<title>Stage</title><script src='https://vendor.example.net/tag.js'></script>"
            content_type = "text/html"
        else:
            body, content_type = b"1;", "application/javascript"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _self_signed(directory):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "stage.example.test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now)
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("stage.example.test"),
                                                        x509.DNSName("vendor.example.net")]), critical=False)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = Path(directory) / "cert.pem", Path(directory) / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    return cert_path, key_path


@unittest.skipUnless(browser_available(), "Chromium for Playwright is not installed")
class BasicAuthTests(unittest.TestCase):
    """A real HTTPS server, so the browser's own Basic-auth handling runs."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cert, key = _self_signed(cls.folder.name)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        cls.server.socket = context.wrap_socket(cls.server.socket, server_side=True)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        port = cls.server.server_address[1]
        cls.args = [
            f"--host-resolver-rules=MAP stage.example.test:443 127.0.0.1:{port},"
            f" MAP vendor.example.net:443 127.0.0.1:{port}",
            "--ignore-certificate-errors",  # the fixture's certificate is self-signed
        ]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.folder.cleanup()

    def setUp(self):
        _Handler.seen = []

    def run_scan(self, password=None):
        login = browser_credentials("stage.example.test", {"username": "qa-user", "password": password}) \
            if password else None
        return scan("https://stage.example.test/page.html", settle=1, http_credentials=login,
                    launch_args=self.args)

    def test_signs_in_only_to_the_site(self):
        result = self.run_scan("s3cret")
        self.assertEqual((result["main_status"], result["title"]), (200, "Stage"))
        site = [auth for host, _, auth in _Handler.seen if host == "stage.example.test"]
        third_party = [auth for host, _, auth in _Handler.seen if host == "vendor.example.net"]
        # Standard Basic-auth handshake: unauthenticated, 401 challenge, then the retry with credentials.
        self.assertEqual(site, [None, EXPECTED_AUTH])
        self.assertTrue(third_party, "the third-party script should have been requested")
        self.assertEqual(set(third_party), {None})  # the password never leaves the site

    def test_missing_credentials(self):
        with self.assertRaises(AuthRequired) as raised:
            self.run_scan()
        self.assertFalse(raised.exception.credentials_sent)

    def test_wrong_credentials(self):
        with self.assertRaises(AuthRequired) as raised:
            self.run_scan("wrong")
        self.assertTrue(raised.exception.credentials_sent)
