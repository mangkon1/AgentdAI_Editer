"""
conversation_store.py
---------------------
Local multi-conversation store (offline cache) next to the app / .exe:

    chats/index.json      -> {"conversations": [meta...], "deleted": [ids...]}
    chats/<id>.json       -> {meta..., "messages": [{id, role, content, time, ts}]}

Also migrates the legacy single chat_history.json into one conversation.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import threading
import time
import uuid

logger = logging.getLogger(__name__)

AVATAR_COLORS = ["#ff3b8d", "#8b5cf6", "#14b8a6", "#f59e0b", "#a0673a", "#f97316"]
DEFAULT_TITLE = "แชทใหม่"
META_KEYS = ("id", "title", "preview", "avatarColor", "createdAt", "updatedAt")


def now_ms() -> int:
    return int(time.time() * 1000)


def new_id() -> str:
    return uuid.uuid4().hex


def make_title(text: str, limit: int = 40) -> str:
    line = " ".join(text.strip().split())
    return (line[:limit] + "…") if len(line) > limit else (line or DEFAULT_TITLE)


def make_preview(text: str, limit: int = 80) -> str:
    line = " ".join(text.strip().replace("```", "").split())
    return (line[:limit] + "…") if len(line) > limit else line


def build_markdown(history: list[dict], title: str | None = None) -> str:
    """Conversation -> Markdown (same format as the original export)."""
    lines = [
        "# 🤖 Local AI Coding Agent — Chat History\n",
        f"*Exported on: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n",
    ]
    if title:
        lines.append(f"**Conversation:** {title}\n")
    lines.append("---\n")
    for msg in history:
        role = msg.get("role", "user")
        time_str = msg.get("time", "")
        content = msg.get("content", "").strip()
        if role == "user":
            lines.append(f"### 👤 User {f'({time_str})' if time_str else ''}\n")
            lines.append(f"{content}\n\n---\n")
        elif role == "assistant":
            lines.append(f"### 🤖 Agent {f'({time_str})' if time_str else ''}\n")
            lines.append(f"{content}\n\n---\n")
        elif role == "system":
            lines.append(f"> ℹ️ **System:** {content}\n\n---\n")
    return "".join(lines)


class ConversationStore:
    def __init__(self, app_dir: str) -> None:
        self.app_dir = app_dir
        self.dir = os.path.join(app_dir, "chats")
        self.index_file = os.path.join(self.dir, "index.json")
        self._lock = threading.RLock()
        self.metas: dict[str, dict] = {}
        self.deleted: set[str] = set()
        self._cache: dict[str, dict] = {}
        os.makedirs(self.dir, exist_ok=True)
        self._load_index()

    # ── persistence ───────────────────────────────────────────────────
    def _write_json(self, path: str, data) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, path)

    def _load_index(self) -> None:
        try:
            if os.path.isfile(self.index_file):
                with open(self.index_file, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                for m in data.get("conversations", []):
                    self.metas[m["id"]] = m
                self.deleted = set(data.get("deleted", []))
        except Exception as exc:
            logger.warning("Could not load chats/index.json: %s", exc)

    def save_index(self) -> None:
        with self._lock:
            try:
                self._write_json(self.index_file, {
                    "conversations": self.list(),
                    "deleted": sorted(self.deleted),
                })
            except Exception as exc:
                logger.warning("Could not save chats/index.json: %s", exc)

    def _conv_file(self, conv_id: str) -> str:
        return os.path.join(self.dir, f"{conv_id}.json")

    def get(self, conv_id: str) -> dict:
        with self._lock:
            if conv_id in self._cache:
                return self._cache[conv_id]
            conv = dict(self.metas.get(conv_id, {"id": conv_id}))
            conv["messages"] = []
            try:
                path = self._conv_file(conv_id)
                if os.path.isfile(path):
                    with open(path, "r", encoding="utf-8") as fh:
                        conv.update(json.load(fh))
            except Exception as exc:
                logger.warning("Could not load conversation %s: %s", conv_id, exc)
            self._cache[conv_id] = conv
            return conv

    def save(self, conv_id: str) -> None:
        with self._lock:
            conv = self.get(conv_id)
            self.metas[conv_id] = {k: conv.get(k) for k in META_KEYS}
            try:
                self._write_json(self._conv_file(conv_id), conv)
            except Exception as exc:
                logger.warning("Could not save conversation %s: %s", conv_id, exc)
            self.save_index()

    # ── operations ────────────────────────────────────────────────────
    def list(self) -> list[dict]:
        with self._lock:
            return sorted(self.metas.values(), key=lambda m: m.get("updatedAt") or 0, reverse=True)

    def create(self, title: str = DEFAULT_TITLE) -> dict:
        with self._lock:
            ts = now_ms()
            color = AVATAR_COLORS[len(self.metas) % len(AVATAR_COLORS)]
            conv = {"id": new_id(), "title": title, "preview": "", "avatarColor": color,
                    "createdAt": ts, "updatedAt": ts, "messages": []}
            self._cache[conv["id"]] = conv
            self.save(conv["id"])
            return conv

    def add_message(self, conv_id: str, role: str, content: str) -> dict:
        with self._lock:
            conv = self.get(conv_id)
            ts = now_ms()
            msg = {"id": new_id(), "role": role, "content": content,
                   "time": datetime.datetime.now().strftime("%H:%M"), "ts": ts}
            conv["messages"].append(msg)
            if role in ("user", "assistant"):
                if role == "user" and conv.get("title") in (None, "", DEFAULT_TITLE):
                    conv["title"] = make_title(content)
                conv["preview"] = make_preview(content)
                conv["updatedAt"] = ts
            self.save(conv_id)
            return msg

    def rename(self, conv_id: str, title: str) -> dict:
        with self._lock:
            conv = self.get(conv_id)
            conv["title"] = title.strip() or DEFAULT_TITLE
            conv["updatedAt"] = now_ms()
            self.save(conv_id)
            return conv

    def delete(self, conv_id: str) -> list[str]:
        with self._lock:
            conv = self.get(conv_id)
            ids = [m["id"] for m in conv.get("messages", []) if "id" in m]
            self.metas.pop(conv_id, None)
            self._cache.pop(conv_id, None)
            self.deleted.add(conv_id)
            try:
                os.remove(self._conv_file(conv_id))
            except OSError:
                pass
            self.save_index()
            return ids

    def markdown(self, conv_id: str) -> str:
        conv = self.get(conv_id)
        return build_markdown(conv.get("messages", []), conv.get("title"))

    def migrate_legacy(self, legacy_file: str) -> str | None:
        """Import old chat_history.json as one conversation (once)."""
        if not os.path.isfile(legacy_file):
            return None
        try:
            with open(legacy_file, "r", encoding="utf-8") as fh:
                history = json.load(fh)
        except Exception as exc:
            logger.warning("Could not read legacy history: %s", exc)
            return None
        if not isinstance(history, list) or not history:
            return None
        with self._lock:
            conv = self.create()
            base = now_ms() - len(history) * 1000
            for i, m in enumerate(history):
                msg = {"id": new_id(), "role": m.get("role", "user"), "content": m.get("content", ""),
                       "time": m.get("time", ""), "ts": base + i * 1000}
                conv["messages"].append(msg)
            users = [m for m in conv["messages"] if m["role"] == "user"]
            chat = [m for m in conv["messages"] if m["role"] in ("user", "assistant")]
            conv["title"] = make_title(users[0]["content"]) if users else "ประวัติแชทเดิม"
            conv["preview"] = make_preview(chat[-1]["content"]) if chat else ""
            conv["updatedAt"] = now_ms()
            self.save(conv["id"])
        try:
            os.replace(legacy_file, legacy_file + ".migrated")
        except OSError:
            pass
        logger.info("Migrated legacy chat history into conversation %s", conv["id"])
        return conv["id"]

    def merge_remote(self, remote: list[dict]) -> tuple[list[str], list[str]]:
        """
        Merge conversations pulled from Firestore.
        Returns (changed_local_ids, ids_where_local_is_newer_or_missing_remotely).
        """
        changed: list[str] = []
        with self._lock:
            remote_ids = set()
            for r in remote:
                rid = r.get("id")
                if not rid or rid in self.deleted:
                    continue
                remote_ids.add(rid)
                local = self.metas.get(rid)
                r_upd = int(r.get("updatedAt") or 0)
                if local is None or r_upd > int(local.get("updatedAt") or 0):
                    conv = self.get(rid) if local else {"id": rid, "messages": []}
                    known = {m.get("id") for m in conv.get("messages", [])}
                    for m in r.get("messages", []):
                        if m["id"] not in known:
                            ts = int(m.get("ts") or 0)
                            m = dict(m)
                            m["time"] = datetime.datetime.fromtimestamp(ts / 1000).strftime("%H:%M") if ts else ""
                            conv["messages"].append(m)
                    conv["messages"].sort(key=lambda m: m.get("ts") or 0)
                    for k in ("title", "preview", "avatarColor", "createdAt", "updatedAt"):
                        if r.get(k) is not None:
                            conv[k] = r[k]
                    conv.setdefault("avatarColor", AVATAR_COLORS[0])
                    self._cache[rid] = conv
                    self.save(rid)
                    changed.append(rid)
            remote_upd = {r.get("id"): int(r.get("updatedAt") or 0) for r in remote}
            to_upload = [cid for cid, m in self.metas.items()
                         if cid not in remote_ids or int(m.get("updatedAt") or 0) > remote_upd.get(cid, 0)]
        return changed, to_upload
