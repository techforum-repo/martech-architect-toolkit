import unittest
from unittest.mock import patch
from modules.advanced import validate_public_url, request_graph, html_report
from modules.dialog_inspector import locate_fields

class AdvancedTests(unittest.TestCase):
    @patch("modules.advanced.socket.getaddrinfo", return_value=[(None,None,None,None,("93.184.215.14",443))])
    def test_public_allowed(self, _):
        self.assertEqual(validate_public_url("https://www.example.com/a", {"www.example.com"}), "www.example.com")
    @patch("modules.advanced.socket.getaddrinfo", return_value=[(None,None,None,None,("127.0.0.1",443))])
    def test_private_rejected(self, _):
        with self.assertRaises(ValueError):
            validate_public_url("https://www.example.com/a", {"www.example.com"})
    def test_nonapproved_rejected(self):
        with self.assertRaises(ValueError):
            validate_public_url("https://unapproved.example.com", {"www.example.com"})
    def test_dialog_field(self):
        data={"items":{"field":{"name":"./trackingId","fieldLabel":"Tracking ID"}}}
        self.assertEqual(locate_fields(data,"trackingId")[0]["label"],"Tracking ID")
    def test_graph(self):
        self.assertEqual(len(request_graph({"requests":[{"url":"https://b", "initiator_url":"https://a"}]})),1)
    def test_escaped_report(self):
        self.assertIn("&lt;script&gt;", html_report({"test":"<script>"}))
