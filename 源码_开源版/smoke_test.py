"""Offline checks run inside the packaged macOS executable in CI."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from platform_support import data_dir, default_download_dir, ensure_writable_directory


def run_bundled_checks(parser):
    runtime = data_dir()
    assert not any(p.lower().endswith(".app") for p in runtime.parts), runtime
    ensure_writable_directory(runtime)
    ffmpeg = parser.get_ffmpeg_binary()
    subprocess.run([ffmpeg, "-version"], check=True, capture_output=True, timeout=20)
    with tempfile.TemporaryDirectory(dir=runtime) as tmp:
        root = Path(tmp)
        video = root / "中文 空格.mp4"
        subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i",
                        "color=c=red:s=160x120:d=0.5", "-c:v", "mpeg4", str(video)],
                       check=True, capture_output=True, timeout=30)
        subprocess.run([ffmpeg, "-v", "error", "-i", str(video), "-f", "null", "-"],
                       check=True, capture_output=True, timeout=30)
        if sys.platform == "darwin":
            subprocess.run(["/usr/bin/open", str(root)], check=True, capture_output=True, timeout=10)
    report = {"ok": True, "platform": sys.platform, "data_dir": str(runtime),
              "default_download_dir": str(default_download_dir(runtime)), "ffmpeg": ffmpeg}
    (runtime / "self-test.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


def run_ui_checks():
    import webview
    results = []
    window = webview.create_window("Mac 兼容测试", html="<html><body>中文界面测试</body></html>")

    def verify():
        try:
            results.append(window.evaluate_js("document.body.textContent") == "中文界面测试")
        finally:
            window.destroy()

    window.events.loaded += verify
    webview.start()
    assert results == [True], "原生 WebKit 窗口测试失败"
    (data_dir() / "ui-test.json").write_text('{"ok": true}', encoding="utf-8")
