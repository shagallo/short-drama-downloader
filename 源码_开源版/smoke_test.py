"""Offline checks run inside packaged Windows and macOS executables in CI."""
import json
import subprocess
import sys
import tempfile
import threading
import time
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
    from werkzeug.serving import make_server
    application = sys.modules['__main__'].app
    # Keep this packaging check offline; exercise the real UI and local APIs.
    application.view_functions['api_search'] = lambda: {"items": [], "total": 0}
    server = make_server('127.0.0.1', 0, application, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    results = []
    window = webview.create_window("桌面兼容测试", url=f'http://127.0.0.1:{server.server_port}')

    def verify():
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                ready = window.evaluate_js("""Boolean(
                    document.querySelector('#downloadDir').value &&
                    getComputedStyle(document.querySelector('.page')).display &&
                    typeof bindEvents === 'function')""")
                if ready:
                    break
                time.sleep(0.2)
            else:
                raise AssertionError('完整界面或下载设置未加载')
            window.evaluate_js("document.querySelector('[data-page=downloads]').click()")
            results.append(window.evaluate_js("document.querySelector('#downloadsPage').classList.contains('active')"))
            window.evaluate_js("document.querySelector('[data-page=settings]').click()")
            results.append(window.evaluate_js("document.querySelector('#settingsPage').classList.contains('active')"))
        finally:
            window.destroy()

    window.events.loaded += verify
    try:
        webview.start()
    finally:
        server.shutdown()
        server.server_close()
    assert results == [True, True], "完整桌面界面导航测试失败"
    (data_dir() / "ui-test.json").write_text('{"ok": true, "full_ui": true, "navigation": true}', encoding="utf-8")
