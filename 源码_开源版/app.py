"""
短剧下载工具 · 开源版

启动：python app.py
API：
  - GET/POST /api/search
  - GET/POST /hg?vid=VIDEO_ID
"""
import importlib
import json
import os
import re
import subprocess
import sys
import threading
import webbrowser
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request, send_from_directory

from download_manager import DownloadManager
from platform_support import (validate_download_path, resolve_download_dir,
                              ensure_writable_directory, default_download_dir)
from werkzeug.serving import make_server


APP_DIR = Path(__file__).resolve().parent
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
}
ITEMS_PER_PAGE = 50
HONGGUO_BASE_URL = "https://hongguoduanju.com"
HONGGUO_CATEGORY_API = f"{HONGGUO_BASE_URL}/api/category/page"
HONGGUO_SUGGESTION_API = f"{HONGGUO_BASE_URL}/incent_resource/suggestion"


SOURCE_ALIASES = {
    "红果短剧": "hongguo",
    "红果短剧官网": "hongguo",
    "红果漫剧": "hongguo_manju",
    "红果免费漫剧": "hongguo_manju",
    "爱奇艺短剧": "iqiyi",
    "FlexTV": "flextv",
    "熊猫短剧": "xiongmao",
    "趣看看短剧": "qukankan",
    "全网聚合": "all",
    "其他短剧平台": "all",
    "本地导入": "local",
}

# 红果短剧官网分类参数，来自公开分类页。
HONGGUO_CATEGORY_MAP = {
    "现代": "background=cate_757",
    "都市": "background=cate_1",
    "古代": "background=cate_758",
    "乡村": "background=cate_11",
    "年代": "background=cate_79",
    "架空": "background=cate_452",
    "职场": "background=cate_127",
    "民国": "background=cate_390",
    "宫廷": "background=cate_1153",
    "校园": "background=cate_4",
    "现言": "topic=cate_1021",
    "女性成长": "topic=cate_1048",
    "脑洞": "topic=cate_262",
    "奇幻": "topic=cate_1020",
    "玄幻": "topic=cate_1019",
    "古言": "topic=cate_439",
    "战神": "topic=cate_1038",
    "宫斗": "topic=cate_246",
    "仙侠": "topic=cate_1013",
    "权谋": "topic=cate_1047",
    "悬疑": "topic=cate_165",
    "喜剧": "topic=cate_303",
    "科幻": "topic=cate_1092",
    "打脸虐渣": "setting=cate_1051",
    "大女主": "setting=cate_760",
    "大男主": "setting=cate_1207",
    "马甲": "setting=cate_266",
    "重生": "setting=cate_36",
    "穿越": "setting=cate_37",
    "系统": "setting=cate_19",
    "先婚后爱": "setting=cate_265",
    "神豪": "setting=cate_20",
    "破镜重圆": "setting=cate_475",
    "豪门": "setting=cate_936",
    "甜宠": "setting=cate_96",
    "娱乐圈": "setting=cate_43",
    "赘婿": "setting=cate_1044",
    "赘婿逆袭": "setting=cate_1044",
    "神医": "setting=cate_26",
    "男频": "gender=1",
    "女频": "gender=0",
    "最新": "sort_type=2",
    "最热": "sort_type=1",
}


def load_dotenv_file(path: Path) -> None:
    """Load simple KEY=VALUE pairs from .env without adding a dependency."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv_file(APP_DIR / ".env")

if getattr(sys, "frozen", False):
    EXE_DIR = Path(sys.executable).resolve().parent
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", EXE_DIR / "_internal"))
else:
    RESOURCE_DIR = APP_DIR

LIUSHEN_DIR = RESOURCE_DIR / "liushen"
STATIC_DIR = RESOURCE_DIR / "static"

for path in (RESOURCE_DIR, LIUSHEN_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="")

parser_module = importlib.import_module("1")
handle_video_request = parser_module.handle_video_request


# ───────────────────────── 配置 ─────────────────────────

def get_config_path() -> Path:
    return parser_module.get_runtime_base_dir() / "config.json"


def mask_value(value: str) -> str:
    value = str(value or "")
    if len(value) <= 6:
        return "*" * len(value)
    return value[:3] + "*" * (len(value) - 6) + value[-3:]


def read_local_config() -> dict:
    path = get_config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_local_config(data: dict) -> Path:
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp_path, path)
    return path


def get_effective_config() -> dict:
    """Return the credentials the downloader will actually use."""
    cfg = read_local_config()
    return {
        **cfg,
        "device_id": str(os.getenv("DUANJU_DEVICE_ID") or cfg.get("device_id") or "").strip(),
        "install_id": str(os.getenv("DUANJU_INSTALL_ID") or cfg.get("install_id") or "").strip(),
        "platform": str(os.getenv("DUANJU_PLATFORM") or cfg.get("platform") or "android").strip() or "android",
    }


DEVICE_CONFIG_LOCK = threading.Lock()


def generate_device_config() -> dict:
    """Generate a fresh credential pair using the project's registration tool."""
    with DEVICE_CONFIG_LOCK:
        if os.getenv("DUANJU_DEVICE_ID") or os.getenv("DUANJU_INSTALL_ID"):
            raise RuntimeError("当前配置由环境变量控制，请先移除环境变量后再生成")
        registrar = importlib.import_module("device_register")
        generated = registrar.device_register()
        device_id = str(generated.get("device_id") or "").strip()
        install_id = str(generated.get("install_id") or "").strip()
        if not device_id or not install_id:
            raise RuntimeError("设备注册工具没有返回完整参数")
        cfg = read_local_config()
        cfg.update({
            "device_id": device_id,
            "install_id": install_id,
            "platform": str(generated.get("platform") or "android"),
            "device_config_source": "generated",
        })
        write_local_config(cfg)
        download_manager.notify_config_changed(retry_failed=True)
        return {
            "device_id_masked": mask_value(device_id),
            "install_id_masked": mask_value(install_id),
            "platform": cfg["platform"],
            "activation_warning": str(generated.get("activation_warning") or ""),
        }


def ensure_default_device_config() -> bool:
    """Create a default generated pair when no usable configuration exists."""
    effective = get_effective_config()
    if effective.get("device_id") and effective.get("install_id"):
        return False
    generate_device_config()
    return True


download_manager = DownloadManager(
    runtime_dir=parser_module.get_runtime_base_dir(),
    downloader=handle_video_request,
    config_getter=get_effective_config,
)


@app.route("/api/config", methods=["GET", "DELETE"])
def get_config():
    cfg = read_local_config()
    env_device_id = str(os.getenv("DUANJU_DEVICE_ID") or "").strip()
    env_install_id = str(os.getenv("DUANJU_INSTALL_ID") or "").strip()
    device_id = env_device_id or str(cfg.get("device_id", ""))
    install_id = env_install_id or str(cfg.get("install_id", ""))
    platform = os.getenv("DUANJU_PLATFORM") or str(cfg.get("platform", "android"))

    if request.method == "DELETE":
        for key in ("device_id", "install_id", "platform", "device_config_source"):
            cfg.pop(key, None)
        write_local_config(cfg)
        download_manager.notify_config_changed()
        return jsonify({
            "ok": True,
            "configured": bool(env_device_id and env_install_id),
            "environment_override": bool(env_device_id or env_install_id),
        })

    return jsonify({
        "configured": bool(device_id and install_id),
        "device_id": device_id,
        "install_id": install_id,
        "device_id_masked": mask_value(device_id),
        "install_id_masked": mask_value(install_id),
        "platform": platform or "android",
        "source": (
            "environment"
            if env_device_id or env_install_id
            else (str(cfg.get("device_config_source") or "local") if device_id or install_id else "none")
        ),
        "environment_override": bool(env_device_id or env_install_id),
        "config_path": str(get_config_path()),
    })


@app.route("/api/config", methods=["POST"])
def save_config():
    data = request.get_json(silent=True) or {}
    device_id = str(data.get("device_id", "")).strip()
    install_id = str(data.get("install_id", "")).strip()
    platform = str(data.get("platform", "android")).strip() or "android"

    if not device_id or not install_id:
        return jsonify({"error": "device_id and install_id are required"}), 400
    if platform not in {"android", "ios"}:
        return jsonify({"error": "platform must be android or ios"}), 400

    cfg = read_local_config()
    cfg.update({
        "device_id": device_id,
        "install_id": install_id,
        "platform": platform,
        "device_config_source": "manual",
    })
    path = write_local_config(cfg)
    download_manager.notify_config_changed(retry_failed=True)
    return jsonify({"ok": True, "config_path": str(path)})


@app.route("/api/config/generate", methods=["POST"])
def generate_config_api():
    try:
        generated = generate_device_config()
        return jsonify({"ok": True, **generated})
    except Exception as exc:
        return jsonify({"error": f"生成设备配置失败：{exc}"}), 502


@app.route("/api/download-settings", methods=["GET", "POST"])
def download_settings():
    if request.method == "GET":
        raw = str(read_local_config().get("download_dir") or "").strip()
        path, notice = resolve_download_dir(raw, download_manager.runtime_dir)
        try:
            ensure_writable_directory(path)
            writable, error = True, ""
        except OSError as exc:
            writable, error = False, f"目录不可写，请选择其他目录或允许文件夹访问：{exc}"
        return jsonify({"download_dir": str(path), "exists": path.is_dir(),
                        "writable": writable, "notice": notice, "error_message": error,
                        "default_download_dir": str(default_download_dir(download_manager.runtime_dir))})

    payload = request.get_json(silent=True) or {}
    raw_path = str(payload.get("download_dir") or "").strip()
    if not raw_path:
        return jsonify({"error": "下载目录不能为空"}), 400
    try:
        path = validate_download_path(raw_path)
        ensure_writable_directory(path)
        cfg = read_local_config()
        cfg["download_dir"] = str(path)
        write_local_config(cfg)
        return jsonify({"ok": True, "download_dir": str(path)})
    except Exception as exc:
        return jsonify({"error": f"无法使用该下载目录：{exc}"}), 400


def open_local_folder(path: Path) -> None:
    path = path.resolve()
    ensure_writable_directory(path)
    if not path.is_dir():
        raise NotADirectoryError(f"不是有效目录：{path}")
    if os.name == "nt":
        # os.startfile can return WinError 5 when Flask is launched from a
        # restricted parent process. Calling Explorer directly also reuses an
        # existing Explorer session and works in that environment.
        subprocess.Popen(["explorer.exe", "/n,", str(path)])
    elif sys.platform == "darwin":
        result = subprocess.run(["/usr/bin/open", str(path)], capture_output=True,
                                text=True, timeout=10)
        if result.returncode:
            raise OSError(result.stderr.strip() or "Finder 无法打开目录")
    else:
        subprocess.Popen(["xdg-open", str(path)])


@app.route("/api/download-folder/open", methods=["POST"])
def open_download_folder():
    try:
        path = download_manager.download_dir()
        open_local_folder(path)
        return jsonify({"ok": True, "path": str(path)})
    except Exception as exc:
        return jsonify({"error": f"无法打开下载目录：{exc}"}), 500


@app.route("/api/downloads", methods=["GET", "POST", "DELETE"])
def downloads():
    if request.method == "GET":
        return jsonify(download_manager.snapshot())
    if request.method == "DELETE":
        scope = str(request.args.get("scope") or "completed")
        if scope not in {"completed", "failed", "all"}:
            return jsonify({"error": "不支持的清理范围"}), 400
        removed = download_manager.clear(scope)
        return jsonify({"ok": True, "removed": removed})

    try:
        task = download_manager.add_task(request.get_json(silent=True) or {})
        return jsonify({"ok": True, "task": task}), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/downloads/control", methods=["POST"])
def control_downloads():
    action = str((request.get_json(silent=True) or {}).get("action") or "").strip()
    if action == "pause":
        download_manager.pause_all()
    elif action == "resume":
        download_manager.resume_all()
    else:
        return jsonify({"error": "操作必须是 pause 或 resume"}), 400
    return jsonify({"ok": True, **download_manager.snapshot()})


@app.route("/api/downloads/<task_id>", methods=["DELETE"])
def delete_download(task_id: str):
    try:
        removed = download_manager.delete(task_id)
        return jsonify({"ok": True, "task": removed})
    except KeyError as exc:
        return jsonify({"error": str(exc)}), 404


@app.route("/api/downloads/<task_id>/retry", methods=["POST"])
def retry_download(task_id: str):
    try:
        task = download_manager.retry(task_id)
        return jsonify({"ok": True, "task": task})
    except KeyError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/downloads/<task_id>/open", methods=["POST"])
def open_task_folder(task_id: str):
    task = next(
        (item for item in download_manager.snapshot()["tasks"] if item.get("id") == task_id),
        None,
    )
    if not task:
        return jsonify({"error": "下载任务不存在"}), 404
    try:
        path = Path(task.get("folder_path") or download_manager.download_dir())
        open_local_folder(path)
        return jsonify({"ok": True, "path": str(path.resolve())})
    except Exception as exc:
        return jsonify({"error": f"无法打开任务目录：{exc}"}), 500


# ───────────────────────── 搜索源 ─────────────────────────

def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def estimate_duration_from_episodes(episode_text: str) -> str:
    """Return a conservative series duration estimate when official duration is absent."""
    m = re.search(r"(\d+)", episode_text or "")
    if not m:
        return ""
    episodes = int(m.group(1))
    # Most short-drama episodes are about 1-2 minutes; use a neutral range.
    return f"\u7ea6 {episodes}-{episodes * 2} \u5206\u949f\uff08\u6309\u6bcf\u96c6 1-2 \u5206\u949f\u4f30\u7b97\uff09"


def public_unknown_time() -> str:
    return "\u5b98\u7f51\u672a\u516c\u5f00"


def fetch_text(url: str, timeout: int = 20) -> str:
    resp = requests.get(url, headers=HTTP_HEADERS, timeout=timeout)
    resp.raise_for_status()
    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = "utf-8"
    return resp.text


def fetch_json(url: str, params: dict | None = None, timeout: int = 20) -> dict:
    headers = dict(HTTP_HEADERS)
    headers["Referer"] = f"{HONGGUO_BASE_URL}/category"
    resp = requests.get(url, params=params, headers=headers, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict):
        raise ValueError("Unexpected JSON response")
    return payload


def dedupe_items(items: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for item in items:
        key = item.get("drama_id") or item.get("source_url") or item.get("title")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def matches_keywords(item: dict, keyword: str, category_filter: str) -> bool:
    keys = []
    if keyword:
        keys.extend([x.strip() for x in re.split(r"[,，\s]+", keyword) if x.strip()])
    if category_filter:
        keys.extend([x.strip() for x in re.split(r"[,，]+", category_filter) if x.strip()])
    if not keys:
        return True
    haystack = " ".join(str(item.get(k, "")) for k in ("title", "category", "author", "desc", "source"))
    return any(k in haystack for k in keys)


def apply_page(items: list[dict], page: int) -> list[dict]:
    page = max(int(page or 1), 1)
    start = (page - 1) * ITEMS_PER_PAGE
    return items[start:start + ITEMS_PER_PAGE]


def first_category_query(keyword: str, category_filter: str) -> str:
    text = f"{keyword},{category_filter}"
    for name, query in HONGGUO_CATEGORY_MAP.items():
        if name and name in text:
            return query
    return "sort_type=1"


def parse_hongguo_cards(html_text: str, base_url: str = HONGGUO_BASE_URL) -> list[dict]:
    soup = BeautifulSoup(html_text, "html.parser")
    items = []
    for a in soup.select('a[href*="/detail?series_id="]'):
        href = a.get("href") or ""
        parsed = urlparse(urljoin(base_url, href))
        series_id = (parse_qs(parsed.query).get("series_id") or [""])[0]
        if not series_id:
            continue

        texts = [clean_text(x) for x in a.stripped_strings if clean_text(x)]
        text_join = " ".join(texts)
        episode = next((x for x in texts if re.search(r"全\d+集", x)), "")

        title = ""
        title_node = a.select_one('[class*="title"]')
        if title_node:
            title = clean_text(title_node.get_text(" "))
        if not title:
            # fallback: 去掉“全xx集”和标签后，取第一段不像标签的文本
            candidates = [x for x in texts if not re.fullmatch(r"全\d+集", x)]
            title = candidates[0] if candidates else text_join[:40]

        tag_texts = []
        for node in a.select('[class*="tag-text"], [class*="tag"] span'):
            t = clean_text(node.get_text(" "))
            if t and t not in tag_texts and len(t) <= 12:
                tag_texts.append(t)
        if not tag_texts:
            # fallback: anchor 文本中除标题/集数外的短词作为标签
            tag_texts = [x for x in texts if x not in {title, episode} and 1 <= len(x) <= 12][:5]

        items.append({
            "author": "红果短剧",
            "title": title,
            "drama_id": series_id,
            "episodes": episode,
            "duration": estimate_duration_from_episodes(episode),
            "online_time": public_unknown_time(),
            "category": " / ".join(tag_texts),
            "source": "红果短剧官网",
            "source_url": urljoin(base_url, href),
            "downloadable": True,
            "desc": text_join,
            "duration_source": "estimated_from_episode_count" if episode else "not_public",
            "online_time_source": "not_public",
        })
    return dedupe_items(items)


def build_hongguo_api_params(keyword: str, page: int, category_filter: str) -> dict:
    selected = parse_qs(first_category_query(keyword, category_filter))
    params: dict[str, Any] = {
        "page_num": max(int(page or 1), 1),
        "sort_type": (selected.get("sort_type") or ["1"])[0],
    }

    for key in ("background", "topic", "setting"):
        value = (selected.get(key) or [""])[0]
        if value:
            params["categories_v2"] = value
            break

    gender = (selected.get("gender") or [""])[0]
    if gender:
        params["gender"] = gender
    return params


def parse_hongguo_api_items(payload: dict) -> list[dict]:
    raw_items = payload.get("recommendList") or []
    if not isinstance(raw_items, list):
        return []

    items = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        series_id = clean_text(raw.get("series_id"))
        title = clean_text(raw.get("series_name"))
        if not series_id or not title:
            continue

        episode_count = raw.get("episode_cnt") or ""
        episode_text = clean_text(raw.get("episode_right_text"))
        if not episode_text and episode_count:
            episode_text = f"\u5168{episode_count}\u96c6"

        tags = raw.get("tags") or []
        if not isinstance(tags, list):
            tags = []
        tag_texts = [clean_text(tag) for tag in tags if clean_text(tag)]

        episode_ids = raw.get("vid_list") or []
        if not isinstance(episode_ids, list):
            episode_ids = []
        episode_ids = [clean_text(vid) for vid in episode_ids if clean_text(vid)]

        celebrities = raw.get("celebrities") or []
        actor_names = []
        if isinstance(celebrities, list):
            actor_names = [
                clean_text(actor.get("nickname"))
                for actor in celebrities
                if isinstance(actor, dict) and clean_text(actor.get("nickname"))
            ][:3]

        items.append({
            "author": " / ".join(actor_names) or "\u7ea2\u679c\u77ed\u5267",
            "title": title,
            "drama_id": series_id,
            "episodes": episode_text,
            "duration": estimate_duration_from_episodes(episode_text),
            "online_time": public_unknown_time(),
            "category": " / ".join(tag_texts),
            "source": "\u7ea2\u679c\u77ed\u5267\u5b98\u7f51",
            "source_url": f"{HONGGUO_BASE_URL}/detail?series_id={series_id}",
            "cover_url": clean_text(raw.get("series_cover")),
            "episode_ids": episode_ids,
            "downloadable": True,
            "desc": clean_text(raw.get("series_intro")),
            "duration_source": "estimated_from_episode_count" if episode_text else "not_public",
            "online_time_source": "not_public",
        })
    return dedupe_items(items)


def find_series_detail(value: Any, series_id: str) -> dict | None:
    if isinstance(value, dict):
        if clean_text(value.get("series_id")) == series_id and isinstance(value.get("vid_list"), list):
            return value
        for child in value.values():
            found = find_series_detail(child, series_id)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_series_detail(child, series_id)
            if found:
                return found
    return None


@lru_cache(maxsize=128)
def fetch_hongguo_series_item(series_id: str) -> dict:
    """Read the complete episode extract from the official detail page router data."""
    series_id = clean_text(series_id)
    if not series_id or not series_id.isdigit():
        raise ValueError("短剧 ID 格式不正确")

    html_text = fetch_text(f"{HONGGUO_BASE_URL}/detail?series_id={series_id}")
    marker = "_ROUTER_DATA ="
    marker_pos = html_text.find(marker)
    if marker_pos < 0:
        raise ValueError("官网详情页没有返回剧目信息")
    json_start = html_text.find("{", marker_pos + len(marker))
    if json_start < 0:
        raise ValueError("官网详情数据格式异常")
    router_data, _ = json.JSONDecoder().raw_decode(html_text[json_start:])
    detail = find_series_detail(router_data, series_id)
    if not detail:
        raise ValueError("官网详情页没有找到该短剧")

    items = parse_hongguo_api_items({"recommendList": [detail]})
    if not items:
        raise ValueError("无法解析短剧详情")
    item = items[0]
    item["source"] = "红果短剧官网详情"
    return item


def parse_hongguo_suggestion_items(payload: dict) -> list[dict]:
    """Normalize the official keyword suggestion response into drama cards."""
    raw_items = payload.get("suggest_list") or []
    if not isinstance(raw_items, list):
        return []

    items = []
    for raw in raw_items:
        if not isinstance(raw, dict) or raw.get("word_type") not in {"title", "short_play_name"}:
            continue
        video = raw.get("video_data") if isinstance(raw.get("video_data"), dict) else {}
        series_id = clean_text(video.get("series_id") or raw.get("keyword"))
        if not series_id or not series_id.isdigit():
            continue
        title = clean_text(video.get("series_title") or video.get("series_name") or raw.get("name"))
        if not title:
            continue

        episode_ids = video.get("vid_list") or []
        if not isinstance(episode_ids, list):
            episode_ids = []
        episode_ids = [clean_text(vid) for vid in episode_ids if clean_text(vid)]
        episode_count = video.get("episode_cnt") or ""
        try:
            episode_total = max(int(episode_count), 0)
        except (TypeError, ValueError):
            episode_total = 0
        episode_text = clean_text(video.get("episode_right_text"))
        if episode_total:
            episode_text = f"全{episode_total}集"
        if not episode_text and episode_ids:
            episode_text = f"可选{len(episode_ids)}集"

        categories = video.get("category_list") or []
        category_names = [
            clean_text(category.get("name"))
            for category in categories
            if isinstance(category, dict) and clean_text(category.get("name"))
        ]
        celebrities = video.get("celebrities") or []
        actor_names = [
            clean_text(actor.get("nickname") or actor.get("name"))
            for actor in celebrities
            if isinstance(actor, dict) and clean_text(actor.get("nickname") or actor.get("name"))
        ][:3]

        items.append({
            "author": " / ".join(actor_names) or "红果短剧",
            "title": title,
            "drama_id": series_id,
            "episodes": episode_text or "集数待加载",
            "duration": estimate_duration_from_episodes(episode_text),
            "online_time": public_unknown_time(),
            "category": " / ".join(category_names) or "关键词搜索",
            "source": "红果短剧官网搜索",
            "source_url": f"{HONGGUO_BASE_URL}/detail?series_id={series_id}",
            "cover_url": clean_text(video.get("series_cover")),
            "episode_ids": episode_ids,
            "downloadable": bool(episode_ids),
            "desc": clean_text(video.get("series_intro")) or f"红果官网中与“{title}”相关的搜索结果。",
            "duration_source": "estimated_from_episode_count" if episode_text else "not_public",
            "online_time_source": "not_public",
        })
    return dedupe_items(items)


def search_hongguo_keyword(keyword: str, page: int) -> list[dict]:
    """Use the official keyword endpoint; never replace an empty match with recommendations."""
    if page > 1:
        return []
    try:
        payload = fetch_json(
            HONGGUO_SUGGESTION_API,
            params={"app_id": "8662", "query": keyword, "count": 20},
        )
        return parse_hongguo_suggestion_items(payload)
    except Exception as exc:
        print(f"[search][hongguo-keyword] failed keyword={keyword} error={exc}")
        return []


def search_hongguo(keyword: str, page: int, category_filter: str) -> list[dict]:
    if keyword:
        return search_hongguo_keyword(keyword, page)

    try:
        payload = fetch_json(
            HONGGUO_CATEGORY_API,
            params=build_hongguo_api_params(keyword, page, category_filter),
        )
        if not payload.get("isSuccess"):
            raise ValueError("Hongguo category API returned an unsuccessful response")
        items = parse_hongguo_api_items(payload)
        if items:
            filtered = [x for x in items if matches_keywords(x, "", category_filter)]
            return filtered if category_filter else items
    except Exception as exc:
        print(f"[search][hongguo-api] failed error={exc}")

    # Compatibility fallback for older server-rendered versions of the website.
    urls = []
    query = first_category_query(keyword, category_filter)
    urls.append(f"{HONGGUO_BASE_URL}/category?{query}")
    urls.append(f"{HONGGUO_BASE_URL}/category?sort_type=1")
    urls.append(f"{HONGGUO_BASE_URL}/")

    items = []
    for url in urls:
        try:
            items.extend(parse_hongguo_cards(fetch_text(url), HONGGUO_BASE_URL))
        except Exception as exc:
            print(f"[search][hongguo] failed url={url} error={exc}")
    items = dedupe_items(items)
    filtered = [x for x in items if matches_keywords(x, "", category_filter)]
    return apply_page(filtered if category_filter else items, page)


def parse_generic_cards(html_text: str, base_url: str, source_name: str, keyword: str = "") -> list[dict]:
    soup = BeautifulSoup(html_text, "html.parser")
    items = []
    for a in soup.find_all("a", href=True):
        title = clean_text(a.get_text(" "))
        href = urljoin(base_url, a.get("href") or "")
        if len(title) < 2:
            continue
        if keyword and keyword not in title:
            continue
        if not any(x in title for x in ["短剧", "漫剧", "剧", keyword]) and not re.search(r"\d+集", title):
            continue
        drama_id = ""
        m = re.search(r"(?:series_id|book_id|album_id|id)=([0-9A-Za-z_-]+)", href)
        if m:
            drama_id = m.group(1)
        items.append({
            "author": source_name,
            "title": title[:80],
            "drama_id": drama_id,
            "episodes": next(iter(re.findall(r"全?\d+集", title)), ""),
            "duration": "",
            "online_time": "",
            "category": source_name,
            "source": source_name,
            "source_url": href,
            "downloadable": False,
            "desc": title,
        })
    return dedupe_items(items)


def search_bing_web(query: str, source_name: str, limit: int = 30) -> list[dict]:
    """Use public Bing result pages as a fallback source for platforms without public list APIs."""
    url = "https://www.bing.com/search?q=" + quote_plus(query)
    try:
        html_text = fetch_text(url)
    except Exception as exc:
        print(f"[search][bing] failed query={query} error={exc}")
        return []

    soup = BeautifulSoup(html_text, "html.parser")
    items = []
    for block in soup.select("li.b_algo"):
        a = block.select_one("h2 a") or block.select_one("a")
        if not a or not a.get("href"):
            continue
        title = clean_text(a.get_text(" "))
        href = a.get("href")
        desc = clean_text((block.select_one("p") or block).get_text(" "))
        drama_id = ""
        m = re.search(r"(?:series_id|book_id|album_id|id)=([0-9A-Za-z_-]+)", href)
        if m:
            drama_id = m.group(1)
        items.append({
            "author": source_name,
            "title": title,
            "drama_id": drama_id,
            "episodes": next(iter(re.findall(r"全?\d+集", title + " " + desc)), ""),
            "duration": "",
            "online_time": "",
            "category": source_name,
            "source": source_name,
            "source_url": href,
            "downloadable": bool(drama_id and "hongguoduanju.com" in href),
            "desc": desc[:180],
        })
        if len(items) >= limit:
            break
    return dedupe_items(items)


def search_yuyue_manju(keyword: str, page: int, category_filter: str) -> list[dict]:
    items = []
    # 官网是动态落地页，公开 HTML 中暂无剧目列表，先提取官网入口。
    try:
        html_text = fetch_text("https://yuyuedushu.com/")
        soup = BeautifulSoup(html_text, "html.parser")
        desc = clean_text((soup.find("meta", attrs={"name": "description"}) or {}).get("content", ""))
        items.append({
            "author": "红果漫剧",
            "title": "红果漫剧官网",
            "drama_id": "",
            "episodes": "",
            "duration": "",
            "online_time": "",
            "category": "漫剧 / 短剧平台",
            "source": "红果漫剧官网",
            "source_url": "https://yuyuedushu.com/",
            "downloadable": False,
            "desc": desc or "红果漫剧公开官网入口",
        })
    except Exception as exc:
        print(f"[search][yuyue] home failed error={exc}")

    q = f"{keyword or category_filter or '热门'} 红果漫剧 短剧 漫剧"
    items.extend(search_bing_web(q, "红果漫剧公开检索", limit=20))
    all_items = dedupe_items(items)
    filtered = [x for x in all_items if matches_keywords(x, keyword, category_filter) or not keyword]
    return apply_page(filtered or all_items, page)


def search_official_page(url: str, source_name: str, keyword: str, page: int, category_filter: str) -> list[dict]:
    items = []
    try:
        items.extend(parse_generic_cards(fetch_text(url), url, source_name, keyword=keyword))
    except Exception as exc:
        print(f"[search][page] failed url={url} error={exc}")
    if len(items) < 5:
        domain = urlparse(url).netloc
        q = f"site:{domain} {keyword or category_filter or '热门短剧'}"
        items.extend(search_bing_web(q, source_name, limit=30))
    all_items = dedupe_items(items)
    if not all_items:
        all_items = [{
            "author": source_name,
            "title": f"{source_name} \u5b98\u7f51/\u516c\u5f00\u5165\u53e3",
            "drama_id": "",
            "episodes": "",
            "duration": "",
            "online_time": "",
            "category": "\u5e73\u53f0\u5165\u53e3",
            "source": source_name,
            "source_url": url,
            "downloadable": False,
            "desc": f"\u672a\u5728\u516c\u5f00\u9875\u9762\u68c0\u7d22\u5230\u300a{keyword}\u300b\u7ed3\u679c\uff0c\u53ef\u6253\u5f00\u5b98\u7f51\u7ee7\u7eed\u641c\u7d22\u3002",
        }]
    filtered = [x for x in all_items if matches_keywords(x, keyword, category_filter) or not keyword]
    return apply_page(filtered or all_items, page)


def search_short_drama(keyword: str, page: int, source: str, category_filter: str) -> list[dict]:
    source_key = SOURCE_ALIASES.get(source, source)
    if source_key == "local":
        return []
    if source_key == "hongguo":
        return search_hongguo(keyword, page, category_filter)
    if source_key == "hongguo_manju":
        return search_yuyue_manju(keyword, page, category_filter)
    if source_key == "iqiyi":
        return search_official_page("https://www.iqiyi.com/microdrama/", "爱奇艺短剧", keyword, page, category_filter)
    if source_key == "flextv":
        return search_official_page("https://www.flextv.cc/tc", "FlexTV", keyword, page, category_filter)
    if source_key == "xiongmao":
        return search_official_page("https://www.xiongmao-player.com/", "熊猫短剧", keyword, page, category_filter)
    if source_key == "qukankan":
        return search_official_page("https://keying.contentchina.com/", "趣看看短剧", keyword, page, category_filter)

    # 全网聚合：红果官网结果 + 几个公开平台检索结果。
    items = []
    items.extend(search_hongguo(keyword, 1, category_filter))
    query = f"{keyword or category_filter or '热门'} 短剧 site:hongguoduanju.com OR site:iqiyi.com OR site:flextv.cc OR site:yuyuedushu.com"
    items.extend(search_bing_web(query, "全网公开检索", limit=40))
    return apply_page(dedupe_items(items), page)


@app.route("/api/search", methods=["GET", "POST"])
def api_search():
    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
        keyword = str(payload.get("keyword", "")).strip()
        page = int(payload.get("page") or 1)
        source = str(payload.get("source", "红果短剧")).strip()
        category_filter = str(payload.get("category_filter", "")).strip()
    else:
        keyword = request.args.get("keyword", "").strip()
        page = int(request.args.get("page") or 1)
        source = request.args.get("source", "红果短剧").strip()
        category_filter = request.args.get("category_filter", "").strip()

    try:
        items = search_short_drama(keyword, page, source, category_filter)
        message = f"搜索完成：{source}，第 {page} 页，返回 {len(items)} 条。"
        has_more = bool(items) and not bool(keyword)
        return jsonify({"items": items, "page": page, "source": source, "has_more": has_more, "message": message})
    except Exception as exc:
        return jsonify({"items": [], "page": page, "source": source, "message": f"搜索失败：{exc}"}), 500


@app.route("/api/dramas/<series_id>", methods=["GET"])
def api_drama_detail(series_id: str):
    try:
        return jsonify({"item": fetch_hongguo_series_item(series_id)})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        return jsonify({"error": f"加载完整分集失败：{exc}"}), 502


# ───────────────────────── 页面和下载 ─────────────────────────

@app.route("/")
def index():
    return send_from_directory(str(STATIC_DIR), "index.html")


@app.route("/src/<path:filename>")
def generated_video(filename):
    src_dir = parser_module.get_runtime_base_dir() / "src"
    return send_from_directory(str(src_dir), filename)


@app.route("/hg", methods=["GET", "POST"])
def hg():
    video_id = request.args.get("vid") or (request.form.get("vid") if request.method == "POST" else None)
    if not video_id:
        return jsonify({"error": "Missing vid parameter"}), 400

    try:
        result = handle_video_request(video_id.strip(), request, max_retries=3)
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def _should_open_browser() -> bool:
    return os.getenv("OPEN_BROWSER", "1").strip().lower() not in {"0", "false", "no", "off"}


def _window_mode_enabled() -> bool:
    """Built-in window is the default; set APP_WINDOW=0 to fall back to browser mode."""
    if os.getenv("APP_WINDOW", "1").strip().lower() in {"0", "false", "no", "off"}:
        return False
    try:
        import webview  # noqa: F401
    except Exception:
        return False
    return True


def _wait_for_server(url: str, timeout: float = 15.0) -> bool:
    import time
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except Exception:
            time.sleep(0.3)
    return False


def _run_with_window(port: int) -> None:
    """Bind before opening a native window; never connect to an unrelated listener."""
    import webview
    # Native app uses an OS-assigned port (AirPlay often occupies 5000 on Mac).
    server = make_server("127.0.0.1", port, app, threaded=True)
    os.environ["APP_PORT"] = str(server.server_port)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="flask-server")
    thread.start()
    try:
        webview.create_window(
            "短剧下载神器", f"http://127.0.0.1:{server.server_port}",
            width=1360, height=880, min_size=(960, 640), text_select=True,
        )
        webview.start()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        from smoke_test import run_bundled_checks
        run_bundled_checks(parser_module)
        sys.exit(0)
    if "--ui-smoke-test" in sys.argv:
        from smoke_test import run_ui_checks
        run_ui_checks()
        sys.exit(0)
    window_mode = _window_mode_enabled()
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.getenv("APP_PORT", "0" if window_mode else "5055"))
    url = f"http://127.0.0.1:{port}"
    os.environ["APP_PORT"] = str(port)

    def initialize_device():
        try:
            ensure_default_device_config()
        except Exception as exc:
            print(f"默认设备配置生成失败，可在设置页重试：{exc}")
    if os.getenv("AUTO_DEVICE_CONFIG", "1") != "0":
        threading.Thread(target=initialize_device, daemon=True, name="device-setup").start()

    if window_mode:
        _run_with_window(port)
    else:
        if _should_open_browser():
            def open_browser():
                import time
                time.sleep(1)
                webbrowser.open(url)

            threading.Thread(target=open_browser, daemon=True).start()

        print(f"短剧下载工具 开源版: {url}")
        app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
