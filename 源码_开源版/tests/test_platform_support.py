import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
import platform_support as paths


class PlatformTests(unittest.TestCase):
    def test_mac_data_lives_outside_app(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(paths.sys, "platform", "darwin"), \
                patch.object(paths.Path, "home", return_value=Path(tmp)), \
                patch.dict(paths.os.environ, {"DUANJU_DATA_DIR": ""}):
            path = paths.data_dir()
            self.assertEqual(path, Path(tmp).resolve() / "Library/Application Support/ShortDramaDownloader")
            paths.ensure_writable_directory(path)
            self.assertEqual(paths.default_download_dir(path), Path(tmp) / "Downloads" / paths.APP_NAME)

    def test_foreign_windows_path_uses_default_with_notice(self):
        native_path = type(Path.cwd())
        with patch.object(paths, "Path", native_path), patch.object(paths.os, "name", "posix"):
            path, notice = paths.resolve_download_dir(r"D:\videos", native_path.cwd())
            self.assertTrue(notice)
            self.assertNotIn("D:\\videos", str(path))

    def test_relative_path_rejected(self):
        with self.assertRaises(ValueError):
            paths.validate_download_path("relative/videos")

    def test_mac_app_internal_path_rejected(self):
        with patch.object(paths.sys, "platform", "darwin"):
            with self.assertRaises(ValueError):
                paths.validate_download_path(str(Path.cwd() / "Example.app/Contents/downloads"))

    def test_actual_write_probe_and_file_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths.ensure_writable_directory(root / "中文 空格")
            (root / "file").write_text("test")
            with self.assertRaises(OSError):
                paths.ensure_writable_directory(root / "file")

    def test_long_chinese_filename_fits_apfs(self):
        from download_manager import safe_filename
        self.assertLessEqual(len(safe_filename("测试" * 120).encode("utf-8")), 200)

    def test_disconnected_volume_is_not_recreated(self):
        target = Mock(parts=("/", "Volumes", "MissingDisk", "Shows"))
        volume = Mock()
        volume.is_mount.return_value = False
        with patch.object(paths.sys, "platform", "darwin"), patch.object(paths, "Path", return_value=volume):
            with self.assertRaisesRegex(OSError, "外部磁盘未挂载"):
                paths.ensure_writable_directory(target)
        target.mkdir.assert_not_called()
