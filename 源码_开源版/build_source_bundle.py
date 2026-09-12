"""Create a clean, reproducible Mac build source zip; never include user data."""
import hashlib
from pathlib import Path
import zipfile


def main():
    source = Path(__file__).resolve().parent
    repo = source.parent
    destination = repo / "安装包" / "短剧下载神器_mac_v1.2.0_构建源码.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)
    files = [source / name for name in (
        "app.py", "1.py", "download_manager.py", "platform_support.py", "smoke_test.py",
        "requirements.txt", "tools_make_icon.py", "README.md", "README_MAC.md",
        "LICENSE", "开源介绍.md",
        "短剧下载神器开源版_mac.spec", "build_source_bundle.py",
    )]
    files += [repo / ".github/workflows/build-mac.yml"]
    files += list((source / "tests").glob("test_*.py"))
    files += [p for p in (source / "liushen").rglob("*.py") if p.name != "test_sign.py"]
    files += [p for p in (source / "static").rglob("*") if p.is_file()
              and p.suffix.lower() in {".html", ".css", ".js", ".png", ".svg", ".ico", ".icns"}]
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(files):
            relative = path.relative_to(repo).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(2026, 9, 11, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            data = path.read_bytes()
            if path.suffix in {".py", ".spec", ".yml", ".md", ".txt", ".js", ".css", ".html"}:
                data = data.replace(b"\r\n", b"\n")
            bundle.writestr(info, data)
    with zipfile.ZipFile(destination) as bundle:
        assert bundle.testzip() is None
        assert not any(Path(n).name in {"config.json", "download_tasks.json", ".env"}
                       or n.endswith((".exe", ".dll", ".mp4")) for n in bundle.namelist())
    print(destination)
    print("SHA256=" + hashlib.sha256(destination.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
