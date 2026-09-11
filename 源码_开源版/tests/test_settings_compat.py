import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class SettingsCompatibilityTests(unittest.TestCase):
    def test_rejected_write_does_not_save_bad_directory(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch("app.ensure_writable_directory", side_effect=PermissionError("denied")), \
                patch("app.write_local_config") as save:
            response = app.app.test_client().post("/api/download-settings", json={"download_dir": tmp})
            self.assertEqual(response.status_code, 400)
            self.assertIn("denied", response.json["error"])
            save.assert_not_called()

    def test_bad_directory_does_not_break_settings_page(self):
        with patch("app.ensure_writable_directory", side_effect=PermissionError("denied")):
            response = app.app.test_client().get("/api/download-settings")
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json["writable"])
            self.assertIn("denied", response.json["error_message"])

    def test_finder_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app.sys, "platform", "darwin"), \
                patch.object(app.os, "name", "posix"), \
                patch("app.subprocess.run") as run:
            run.return_value.returncode = 1
            run.return_value.stderr = "Finder refused"
            # Use the native pathlib concrete class to avoid platform monkeypatch side effects.
            path = type(app.APP_DIR)(tmp)
            with self.assertRaisesRegex(OSError, "Finder refused"):
                app.open_local_folder(path)
            self.assertEqual(run.call_args.args[0], ["/usr/bin/open", str(path.resolve())])
