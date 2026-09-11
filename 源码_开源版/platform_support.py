"""Keep writable user data separate from immutable application resources."""
import os
import sys
import tempfile
from pathlib import Path, PureWindowsPath

APP_NAME = "短剧下载神器"


def resource_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def data_dir() -> Path:
    override = os.getenv("DUANJU_DATA_DIR", "").strip()
    if override:
        path = Path(override).expanduser()
        if not path.is_absolute():
            raise ValueError("DUANJU_DATA_DIR 必须是绝对路径")
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / "ShortDramaDownloader"
    elif getattr(sys, "frozen", False):
        if os.name == "nt":
            # Keep existing Windows installations and their saved task history.
            path = Path(sys.executable).resolve().parent
        else:
            path = Path(os.getenv("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "short-drama-downloader"
    else:
        path = Path(__file__).resolve().parent
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def default_download_dir(runtime: Path) -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Downloads" / APP_NAME
    return runtime / "downloads"


def validate_download_path(raw: str) -> Path:
    raw = raw.strip()
    if not raw:
        raise ValueError("下载目录不能为空")
    if os.name != "nt" and PureWindowsPath(raw).drive:
        raise ValueError("这是 Windows 路径，请选择本机目录，例如 ~/Downloads/短剧下载神器")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError("请输入本机完整路径，或使用 ~/Downloads/短剧下载神器")
    path = path.resolve()
    if sys.platform == "darwin" and any(part.lower().endswith(".app") for part in path.parts):
        raise ValueError("不能把下载目录设在应用包内部，请选择用户下载目录")
    return path


def resolve_download_dir(raw: str, runtime: Path) -> tuple[Path, str]:
    if raw:
        try:
            return validate_download_path(raw), ""
        except ValueError as exc:
            return default_download_dir(runtime).resolve(), f"{exc}；已使用本机默认目录"
    return default_download_dir(runtime).resolve(), ""


def ensure_writable_directory(path: Path) -> None:
    # Do not silently redirect downloads when a custom disk is disconnected.
    if sys.platform == "darwin" and len(path.parts) > 2 and path.parts[1] == "Volumes":
        volume = Path(*path.parts[:3])
        if not volume.is_mount():
            raise OSError(f"外部磁盘未挂载：{volume}")
    path.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile(dir=path) as probe:
        probe.write(b"write-test")
        probe.flush()
