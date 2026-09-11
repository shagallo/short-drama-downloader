"""Persistent, episode-aware download queue for the local web application."""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse
from platform_support import resolve_download_dir, ensure_writable_directory


INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_filename(value: str, fallback: str = "未命名短剧") -> str:
    name = INVALID_FILENAME_CHARS.sub("_", str(value or "")).strip(" .")
    # APFS limits a filename component by UTF-8 bytes, not character count.
    return name.encode("utf-8")[:200].decode("utf-8", errors="ignore") or fallback


def now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class DownloadManager:
    def __init__(
        self,
        runtime_dir: Path,
        downloader: Callable[..., dict[str, Any]],
        config_getter: Callable[[], dict[str, Any]],
    ) -> None:
        self.runtime_dir = Path(runtime_dir)
        self.downloader = downloader
        self.config_getter = config_getter
        self.state_path = self.runtime_dir / "download_tasks.json"
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.tasks: dict[str, dict[str, Any]] = {}
        self.paused = False
        self._load()
        with self.lock:
            for task in self.tasks.values():
                self._refresh_task_locked(task)
            self._save_locked()
        self.worker = threading.Thread(target=self._worker_loop, daemon=True, name="download-manager")
        self.worker.start()
        if any(
            episode.get("status") == "pending"
            for task in self.tasks.values()
            for episode in task.get("episodes", [])
        ) and self._configured() and not self.paused:
            self.wake.set()

    def download_dir(self) -> Path:
        configured = str(self.config_getter().get("download_dir") or "").strip()
        return resolve_download_dir(configured, self.runtime_dir)[0]

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "paused": self.paused,
                "configured": self._configured(),
                "download_dir": str(self.download_dir()),
                "tasks": json.loads(json.dumps(list(self.tasks.values()), ensure_ascii=False)),
            }

    def notify_config_changed(self, retry_failed: bool = False) -> None:
        """Re-evaluate waiting tasks after credentials are saved."""
        with self.lock:
            for task in self.tasks.values():
                if retry_failed:
                    for episode in task.get("episodes", []):
                        if episode.get("status") == "failed":
                            episode.update(status="pending", progress=0, message="配置已更新，等待重试")
                self._refresh_task_locked(task)
            self._save_locked()
            if self._configured() and not self.paused:
                self.wake.set()

    def add_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        series_id = str(payload.get("series_id") or "").strip()
        title = str(payload.get("title") or series_id or "未命名短剧").strip()
        requested = payload.get("episodes") or []
        if not series_id:
            raise ValueError("缺少短剧 ID")
        if not isinstance(requested, list) or not requested:
            raise ValueError("请至少选择一集")

        episodes = []
        seen = set()
        for index, item in enumerate(requested, start=1):
            if not isinstance(item, dict):
                continue
            vid = str(item.get("vid") or item.get("id") or "").strip()
            if not vid or vid in seen:
                continue
            seen.add(vid)
            try:
                number = max(int(item.get("number") or index), 1)
            except (TypeError, ValueError):
                number = index
            episodes.append(
                {
                    "number": number,
                    "vid": vid,
                    "status": "pending",
                    "progress": 0,
                    "message": "等待下载",
                    "file_path": "",
                    "quality": "",
                    "size": "",
                }
            )
        if not episodes:
            raise ValueError("所选分集缺少可下载的视频 ID")

        with self.lock:
            existing = next(
                (
                    task
                    for task in self.tasks.values()
                    if task.get("series_id") == series_id
                    and task.get("status") not in {"completed", "cancelled"}
                ),
                None,
            )
            if existing:
                existing_vids = {ep.get("vid") for ep in existing.get("episodes", [])}
                existing["episodes"].extend(ep for ep in episodes if ep["vid"] not in existing_vids)
                existing["updated_at"] = now_text()
                existing["message"] = "已追加分集，等待下载"
                self._refresh_task_locked(existing)
                task = existing
            else:
                task_id = uuid.uuid4().hex[:12]
                task = {
                    "id": task_id,
                    "series_id": series_id,
                    "title": title,
                    "cover_url": str(payload.get("cover_url") or ""),
                    "source": str(payload.get("source") or "红果短剧"),
                    "status": "paused" if self.paused else "queued",
                    "progress": 0,
                    "message": "已暂停" if self.paused else "等待下载",
                    "created_at": now_text(),
                    "updated_at": now_text(),
                    "folder_path": "",
                    "episodes": episodes,
                }
                self.tasks[task_id] = task
                self._refresh_task_locked(task)
            self._save_locked()
            self.wake.set()
            return json.loads(json.dumps(task, ensure_ascii=False))

    def pause_all(self) -> None:
        with self.lock:
            self.paused = True
            for task in self.tasks.values():
                self._refresh_task_locked(task)
            self._save_locked()

    def resume_all(self) -> None:
        with self.lock:
            self.paused = False
            for task in self.tasks.values():
                self._refresh_task_locked(task)
            self._save_locked()
            self.wake.set()

    def retry(self, task_id: str) -> dict[str, Any]:
        with self.lock:
            task = self._require_task_locked(task_id)
            changed = False
            for episode in task.get("episodes", []):
                if episode.get("status") == "failed":
                    episode.update(status="pending", progress=0, message="等待重试")
                    changed = True
            if not changed:
                raise ValueError("没有可重试的失败分集")
            task["updated_at"] = now_text()
            self._refresh_task_locked(task)
            self._save_locked()
            self.wake.set()
            return json.loads(json.dumps(task, ensure_ascii=False))

    def delete(self, task_id: str) -> dict[str, Any]:
        with self.lock:
            task = self._require_task_locked(task_id)
            removed = self.tasks.pop(task_id)
            self._save_locked()
            return json.loads(json.dumps(removed, ensure_ascii=False))

    def clear(self, scope: str = "completed") -> int:
        with self.lock:
            if scope == "all":
                task_ids = list(self.tasks)
            elif scope == "failed":
                task_ids = [key for key, task in self.tasks.items() if task.get("status") == "failed"]
            else:
                task_ids = [key for key, task in self.tasks.items() if task.get("status") == "completed"]
            for task_id in task_ids:
                self.tasks.pop(task_id, None)
            self._save_locked()
            return len(task_ids)

    def _require_task_locked(self, task_id: str) -> dict[str, Any]:
        task = self.tasks.get(task_id)
        if not task:
            raise KeyError("下载任务不存在")
        return task

    def _worker_loop(self) -> None:
        while True:
            self.wake.wait()
            while True:
                with self.lock:
                    if self.paused:
                        self.wake.clear()
                        break
                    work = self._next_episode_locked()
                    if work is None:
                        self.wake.clear()
                        break
                    task_id, episode_vid = work
                try:
                    self._download_episode(task_id, episode_vid)
                except Exception as exc:
                    # A missing disk or denied folder must not kill the worker.
                    with self.lock:
                        task = self.tasks.get(task_id)
                        episode = self._find_episode(task, episode_vid)
                        if task and episode:
                            episode.update(status="failed", progress=0, message=f"下载失败：{exc}")
                            self._refresh_task_locked(task)
                            self._save_locked()

    def _next_episode_locked(self) -> tuple[str, str] | None:
        if not self._configured():
            for task in self.tasks.values():
                self._refresh_task_locked(task)
            self._save_locked()
            return None
        for task_id, task in self.tasks.items():
            for episode in task.get("episodes", []):
                if episode.get("status") == "pending":
                    episode.update(status="downloading", progress=35, message="正在解析视频地址")
                    task["updated_at"] = now_text()
                    self._refresh_task_locked(task)
                    self._save_locked()
                    return task_id, str(episode.get("vid"))
        return None

    def _download_episode(self, task_id: str, episode_vid: str) -> None:
        with self.lock:
            task = self.tasks.get(task_id)
            episode = self._find_episode(task, episode_vid)
            if not task or not episode:
                return
            destination = self._destination_path(task, episode)
            ensure_writable_directory(destination.parent)
            if destination.exists() and destination.stat().st_size > 0:
                episode.update(
                    status="completed",
                    progress=100,
                    message="文件已存在",
                    file_path=str(destination),
                )
                task["folder_path"] = str(destination.parent)
                task["updated_at"] = now_text()
                self._refresh_task_locked(task)
                self._save_locked()
                return
            episode.update(progress=55, message="正在下载并处理视频")
            self._refresh_task_locked(task)
            self._save_locked()

        temp_path: Path | None = None
        try:
            result = self.downloader(episode_vid, request=None, max_retries=3)
            local_url = str(result.get("url") or "")
            temp_name = Path(unquote(urlparse(local_url).path)).name
            temp_path = self.runtime_dir / "src" / temp_name
            if not temp_name or not temp_path.exists():
                raise RuntimeError("下载器没有生成本地视频文件")

            with self.lock:
                task = self.tasks.get(task_id)
                episode = self._find_episode(task, episode_vid)
                if not task or not episode:
                    temp_path.unlink(missing_ok=True)
                    return
                destination = self._destination_path(task, episode)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    destination.unlink()
                shutil.move(str(temp_path), str(destination))
                episode.update(
                    status="completed",
                    progress=100,
                    message="下载完成",
                    file_path=str(destination),
                    quality=str(result.get("quality") or ""),
                    size=str(result.get("size") or ""),
                )
                task["folder_path"] = str(destination.parent)
                task["updated_at"] = now_text()
                self._refresh_task_locked(task)
                self._save_locked()
        except Exception as exc:
            if temp_path:
                temp_path.unlink(missing_ok=True)
            with self.lock:
                task = self.tasks.get(task_id)
                episode = self._find_episode(task, episode_vid)
                if not task or not episode:
                    return
                episode.update(status="failed", progress=100, message=f"下载失败：{exc}")
                task["updated_at"] = now_text()
                self._refresh_task_locked(task)
                self._save_locked()

    @staticmethod
    def _find_episode(task: dict[str, Any] | None, episode_vid: str) -> dict[str, Any] | None:
        if not task:
            return None
        return next((ep for ep in task.get("episodes", []) if str(ep.get("vid")) == episode_vid), None)

    def _destination_path(self, task: dict[str, Any], episode: dict[str, Any]) -> Path:
        folder = self.download_dir() / safe_filename(task.get("title") or task.get("series_id"))
        number = max(int(episode.get("number") or 1), 1)
        return folder / f"第{number:03d}集.mp4"

    def _refresh_task_locked(self, task: dict[str, Any]) -> None:
        episodes = task.get("episodes", [])
        total = len(episodes)
        completed = sum(ep.get("status") == "completed" for ep in episodes)
        downloading = [ep for ep in episodes if ep.get("status") == "downloading"]
        failed = sum(ep.get("status") == "failed" for ep in episodes)
        pending = sum(ep.get("status") == "pending" for ep in episodes)
        active_fraction = sum(float(ep.get("progress") or 0) / 100 for ep in downloading)
        task["progress"] = round(((completed + active_fraction) / total) * 100) if total else 0

        if downloading:
            task["status"] = "downloading"
            task["message"] = f"正在下载第 {downloading[0].get('number')} 集"
        elif pending:
            if self.paused:
                task["status"] = "paused"
                task["message"] = "已暂停"
            elif not self._configured():
                task["status"] = "waiting_config"
                task["message"] = "等待设备配置 · 保存配置后自动开始"
            else:
                task["status"] = "queued"
                task["message"] = f"等待下载 · 剩余 {pending} 集"
        elif failed:
            task["status"] = "failed"
            task["message"] = f"完成 {completed} 集，失败 {failed} 集"
        else:
            task["status"] = "completed"
            task["progress"] = 100
            task["message"] = f"已完成全部 {completed} 集"

    def _configured(self) -> bool:
        config = self.config_getter() or {}
        return bool(str(config.get("device_id") or "").strip() and str(config.get("install_id") or "").strip())

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                self.paused = bool(payload.get("paused", False))
            stored = payload.get("tasks") if isinstance(payload, dict) else payload
            if not isinstance(stored, list):
                return
            for task in stored:
                if not isinstance(task, dict) or not task.get("id"):
                    continue
                for episode in task.get("episodes", []):
                    if episode.get("status") == "downloading":
                        episode.update(status="pending", progress=0, message="等待恢复")
                self.tasks[str(task["id"])] = task
                self._refresh_task_locked(task)
        except Exception as exc:
            print(f"[downloads] failed_to_load_state={exc}")

    def _save_locked(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.state_path.with_suffix(".tmp")
        payload = {"paused": self.paused, "tasks": list(self.tasks.values())}
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp_path, self.state_path)
