import tempfile
import time
import unittest
from pathlib import Path

from download_manager import DownloadManager


class DownloadManagerTests(unittest.TestCase):
    def test_unwritable_destination_does_not_kill_worker(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            bad = runtime / "not-a-directory"
            bad.write_bytes(b"file")
            config = {"device_id": "test", "install_id": "test", "download_dir": str(bad)}

            def download(video_id, **kwargs):
                source = runtime / "src" / f"{video_id}.mp4"
                source.parent.mkdir(exist_ok=True)
                source.write_bytes(b"test-video")
                return {"url": f"http://127.0.0.1/src/{source.name}"}

            manager = DownloadManager(runtime, download, lambda: config)

            def add_and_wait(series_id, expected):
                manager.add_task({"series_id": series_id, "title": series_id,
                                  "episodes": [{"number": 1, "vid": series_id}]})
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    task = next(t for t in manager.snapshot()["tasks"] if t["series_id"] == series_id)
                    if task["status"] == expected:
                        return task
                    time.sleep(0.02)
                self.fail(f"Task did not reach {expected}: {task}")

            failed = add_and_wait("bad-path", "failed")
            self.assertIn("下载失败", failed["episodes"][0]["message"])
            config["download_dir"] = str(runtime / "saved")
            add_and_wait("good-path", "completed")

    def test_episode_queue_downloads_and_tracks_overall_progress(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime_dir = Path(temp)
            download_dir = runtime_dir / "saved"

            def fake_downloader(video_id, request=None, max_retries=3):
                source_dir = runtime_dir / "src"
                source_dir.mkdir(parents=True, exist_ok=True)
                path = source_dir / f"{video_id}.mp4"
                path.write_bytes(f"video-{video_id}".encode())
                return {"url": f"http://127.0.0.1/src/{path.name}", "quality": "1080p"}

            manager = DownloadManager(
                runtime_dir=runtime_dir,
                downloader=fake_downloader,
                config_getter=lambda: {
                    "download_dir": str(download_dir),
                    "device_id": "test-device",
                    "install_id": "test-install",
                },
            )
            manager.add_task(
                {
                    "series_id": "series-1",
                    "title": "测试短剧",
                    "episodes": [
                        {"number": 1, "vid": "video-1"},
                        {"number": 2, "vid": "video-2"},
                    ],
                }
            )

            deadline = time.time() + 3
            task = None
            while time.time() < deadline:
                task = manager.snapshot()["tasks"][0]
                if task["status"] == "completed":
                    break
                time.sleep(0.02)
            self.assertIsNotNone(task)
            self.assertEqual(task["status"], "completed")
            self.assertEqual(task["progress"], 100)
            self.assertTrue((download_dir / "测试短剧" / "第001集.mp4").exists())
            self.assertTrue((download_dir / "测试短剧" / "第002集.mp4").exists())

    def test_paused_queue_waits_until_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime_dir = Path(temp)

            def fake_downloader(video_id, request=None, max_retries=3):
                source_dir = runtime_dir / "src"
                source_dir.mkdir(parents=True, exist_ok=True)
                path = source_dir / f"{video_id}.mp4"
                path.write_bytes(b"video")
                return {"url": f"http://127.0.0.1/src/{path.name}"}

            manager = DownloadManager(
                runtime_dir,
                fake_downloader,
                lambda: {"device_id": "test-device", "install_id": "test-install", "download_dir": str(runtime_dir / "saved")},
            )
            manager.pause_all()
            manager.add_task(
                {"series_id": "series-2", "title": "暂停测试", "episodes": [{"number": 1, "vid": "video-1"}]}
            )
            time.sleep(0.05)
            self.assertEqual(manager.snapshot()["tasks"][0]["status"], "paused")

            manager.resume_all()
            deadline = time.time() + 3
            while time.time() < deadline:
                task = manager.snapshot()["tasks"][0]
                if task["status"] == "completed":
                    break
                time.sleep(0.02)
            self.assertEqual(task["status"], "completed")

    def test_unconfigured_task_is_visible_and_starts_after_config_save(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime_dir = Path(temp)
            config = {"download_dir": str(runtime_dir / "saved")}

            def fake_downloader(video_id, request=None, max_retries=3):
                source_dir = runtime_dir / "src"
                source_dir.mkdir(parents=True, exist_ok=True)
                path = source_dir / f"{video_id}.mp4"
                path.write_bytes(b"video")
                return {"url": f"http://127.0.0.1/src/{path.name}"}

            manager = DownloadManager(runtime_dir, fake_downloader, lambda: config)
            manager.add_task(
                {"series_id": "series-3", "title": "等待配置测试", "episodes": [{"number": 1, "vid": "video-1"}]}
            )
            time.sleep(0.05)
            self.assertEqual(manager.snapshot()["tasks"][0]["status"], "waiting_config")

            config.update(device_id="test-device", install_id="test-install")
            manager.notify_config_changed()
            deadline = time.time() + 3
            while time.time() < deadline:
                task = manager.snapshot()["tasks"][0]
                if task["status"] == "completed":
                    break
                time.sleep(0.02)
            self.assertEqual(task["status"], "completed")

    def test_waiting_task_resumes_after_restart_with_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime_dir = Path(temp)
            config = {"download_dir": str(runtime_dir / "saved")}

            def fake_downloader(video_id, request=None, max_retries=3):
                source_dir = runtime_dir / "src"
                source_dir.mkdir(parents=True, exist_ok=True)
                path = source_dir / f"{video_id}.mp4"
                path.write_bytes(b"video")
                return {"url": f"http://127.0.0.1/src/{path.name}"}

            first = DownloadManager(runtime_dir, fake_downloader, lambda: config)
            first.add_task({
                "series_id": "series-restart",
                "title": "重启恢复测试",
                "episodes": [{"number": 1, "vid": "restart-video"}],
            })
            deadline = time.time() + 3
            while time.time() < deadline and first.wake.is_set():
                time.sleep(0.02)
            self.assertEqual(first.snapshot()["tasks"][0]["status"], "waiting_config")

            config.update(device_id="test-device", install_id="test-install")
            restarted = DownloadManager(runtime_dir, fake_downloader, lambda: config)
            deadline = time.time() + 3
            task = restarted.snapshot()["tasks"][0]
            while time.time() < deadline and task["status"] != "completed":
                time.sleep(0.02)
                task = restarted.snapshot()["tasks"][0]

            self.assertEqual(task["status"], "completed")


if __name__ == "__main__":
    unittest.main()
