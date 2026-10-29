"""The app's session after a browser refresh."""

import types
import unittest
from unittest import mock

from web_inspector.ui import shared


class RefreshTests(unittest.TestCase):
    def test_open_aem_window_sign_in_is_picked_up_after_refresh(self):
        fresh = types.SimpleNamespace(session_state={})  # a refresh: empty session
        window = types.SimpleNamespace(storage_state={"cookies": [{"name": "login-token"}]})
        with mock.patch.object(shared, "st", fresh), \
                mock.patch.object(shared.aem_browser, "open_windows", return_value={"env1": window}):
            shared.init_session_state()
        self.assertEqual(fresh.session_state["aem_ui_sessions"], {"env1": window.storage_state})

    def test_a_session_sign_in_is_kept(self):
        current = types.SimpleNamespace(session_state={"aem_ui_sessions": {"env1": {"cookies": []}}})
        window = types.SimpleNamespace(storage_state={"cookies": [{"name": "login-token"}]})
        with mock.patch.object(shared, "st", current), \
                mock.patch.object(shared.aem_browser, "open_windows", return_value={"env1": window}):
            shared.init_session_state()
        self.assertEqual(current.session_state["aem_ui_sessions"], {"env1": {"cookies": []}})


if __name__ == "__main__":
    unittest.main()
