import tempfile
import unittest
from unittest.mock import patch

from web_inspector import preferences


class PreferencesTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = patch.object(preferences.settings, "data_dir", folder.name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_default_until_set(self):
        self.assertTrue(preferences.get("mock_mode", True))
        preferences.set("mock_mode", False)
        self.assertFalse(preferences.get("mock_mode", True))

    def test_other_keys_kept(self):
        preferences.set("a", 1)
        preferences.set("mock_mode", False)
        self.assertEqual(preferences.load(), {"a": 1, "mock_mode": False})

    def test_unreadable_file_falls_back(self):
        preferences._path().parent.mkdir(parents=True, exist_ok=True)
        preferences._path().write_text("{broken")
        self.assertEqual(preferences.get("mock_mode", True), True)


if __name__ == "__main__":
    unittest.main()
