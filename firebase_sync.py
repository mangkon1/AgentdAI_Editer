"""
firebase_sync.py
----------------
Realtime background sync of conversations to Firebase Cloud Firestore.

* Pure standard library (urllib) -> PyInstaller friendly, no extra deps.
* Firebase Auth anonymous sign-in via REST; refresh token + uid kept in config.json.
* Every write goes through a queue processed by one daemon worker thread.
  Failed writes stay in an offline backlog (sync_backlog.json) and are retried
  with exponential backoff, so the UI is never blocked and never crashes.

Firestore layout:
    users/{uid}/conversations/{convId}
        {title, preview, avatarColor, createdAt, updatedAt, markdown}
    users/{uid}/conversations/{convId}/messages/{msgId}
        {role, text, ts}
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

logger = logging.getLogger(__name__)

DEFAULT_PROJECT_ID = "agentdai-editer"
DEFAULT_API_KEY = "AIzaSyCoDWYqQW4RmqT4MTQZtGcDJn3xI3vWTio"

SIGNUP_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={key}"
REFRESH_URL = "https://securetoken.googleapis.com/v1/token?key={key}"
FIRESTORE_BASE = "https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents"

STATE_OK = "ok"
STATE_SYNCING = "syncing"
STATE_ERROR = "error"
STATE_DISABLED = "disabled"


class SyncError(Exception):
    pass


# ---------------------------------------------------------------------------
# Firestore value encoding
# ---------------------------------------------------------------------------

def encode_value(v: Any) -> dict:
    if v is None:
        return {"nullValue": None}
    if isinstance(v, bool):
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"integerValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, dict):
        return {"mapValue": {"fields": {k: encode_value(x) for k, x in v.items()}}}
    if isinstance(v, (list, tuple)):
        return {"arrayValue": {"values": [encode_value(x) for x in v]}}
    return {"stringValue": str(v)}


def decode_value(v: dict) -> Any:
    if "stringValue" in v:
        return v["stringValue"]
    if "integerValue" in v:
        return int(v["integerValue"])
    if "doubleValue" in v:
        return float(v["doubleValue"])
    if "booleanValue" in v:
        return bool(v["booleanValue"])
    if "nullValue" in v:
        return None
    if "timestampValue" in v:
        return v["timestampValue"]
    if "mapValue" in v:
        return {k: decode_value(x) for k, x in v["mapValue"].get("fields", {}).items()}
    if "arrayValue" in v:
        return [decode_value(x) for x in v["arrayValue"].get("values", [])]
    return None


def encode_fields(d: dict) -> dict:
    return {"fields": {k: encode_value(v) for k, v in d.items()}}


def decode_doc(doc: dict) -> dict:
    out = {k: decode_value(v) for k, v in doc.get("fields", {}).items()}
    out["_id"] = doc.get("name", "").rsplit("/", 1)[-1]
    return out


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def http_json(method: str, url: str, body: Any = None, token: str | None = None,
              form: bool = False, timeout: float = 20) -> dict:
    headers = {}
    data = None
    if body is not None:
        if form:
            data = urllib.parse.urlencode(body).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        raw = ""
        try:
            raw = exc.read().decode("utf-8", "replace")
            msg = json.loads(raw).get("error", {})
            msg = msg.get("message", raw) if isinstance(msg, dict) else str(msg)
        except Exception:
            msg = raw or str(exc)
        err = SyncError(f"HTTP {exc.code}: {msg}")
        err.status = exc.code  # type: ignore[attr-defined]
        raise err from None
    except urllib.error.URLError as exc:
        raise SyncError(f"Network error: {exc.reason}") from None
    except TimeoutError:
        raise SyncError("Network timeout") from None


# ---------------------------------------------------------------------------
# Auth + Firestore client
# ---------------------------------------------------------------------------

class FirebaseClient:
    def __init__(self, project_id: str, api_key: str, auth_state: dict | None = None,
                 on_auth_change: Callable[[dict], None] | None = None,
                 http: Callable[..., dict] = http_json) -> None:
        self.project_id = project_id
        self.api_key = api_key
        self.auth = dict(auth_state or {})
        self.on_auth_change = on_auth_change
        self.http = http
        self._id_token: str | None = None
        self._expiry = 0.0

    @property
    def uid(self) -> str | None:
        return self.auth.get("uid")

    def sign_up_anonymous(self) -> dict:
        res = self.http("POST", SIGNUP_URL.format(key=self.api_key), {"returnSecureToken": True})
        self.auth = {"uid": res["localId"], "refreshToken": res["refreshToken"],
                     "projectId": self.project_id}
        self._id_token = res["idToken"]
        self._expiry = time.time() + int(res.get("expiresIn", 3600)) - 120
        if self.on_auth_change:
            self.on_auth_change(dict(self.auth))
        return res

    def refresh(self) -> None:
        res = self.http("POST", REFRESH_URL.format(key=self.api_key),
                        {"grant_type": "refresh_token", "refresh_token": self.auth["refreshToken"]},
                        form=True)
        self._id_token = res["id_token"]
        self._expiry = time.time() + int(res.get("expires_in", 3600)) - 120
        changed = res.get("refresh_token") != self.auth.get("refreshToken")
        self.auth["refreshToken"] = res.get("refresh_token", self.auth["refreshToken"])
        self.auth["uid"] = res.get("user_id", self.auth.get("uid"))
        if changed and self.on_auth_change:
            self.on_auth_change(dict(self.auth))

    def token(self) -> str:
        if self._id_token and time.time() < self._expiry:
            return self._id_token
        if self.auth.get("refreshToken") and self.auth.get("projectId", self.project_id) == self.project_id:
            try:
                self.refresh()
                return self._id_token  # type: ignore[return-value]
            except SyncError as exc:
                # Revoked / invalid refresh token -> fall back to new anonymous user
                if "TOKEN" not in str(exc).upper() and "USER" not in str(exc).upper():
                    raise
                logger.warning("Refresh failed (%s); signing up again", exc)
        self.sign_up_anonymous()
        return self._id_token  # type: ignore[return-value]

    # ── Firestore primitives ──────────────────────────────────────────
    def _url(self, path: str, query: dict | None = None) -> str:
        url = FIRESTORE_BASE.format(project=self.project_id) + "/" + path
        if query:
            url += "?" + urllib.parse.urlencode(query, doseq=True)
        return url

    def user_path(self, *parts: str) -> str:
        return "/".join(["users", self.uid or ""] + [urllib.parse.quote(p, safe="") for p in parts])

    def set_doc(self, path: str, data: dict) -> dict:
        tok = self.token()
        q = {"updateMask.fieldPaths": list(data.keys())}
        return self.http("PATCH", self._url(self.user_path(*path.split("/")), q), encode_fields(data), token=tok)

    def delete_doc(self, path: str) -> None:
        tok = self.token()
        try:
            self.http("DELETE", self._url(self.user_path(*path.split("/"))), token=tok)
        except SyncError as exc:
            if getattr(exc, "status", 0) != 404:
                raise

    def list_docs(self, path: str, order_by: str | None = None) -> list[dict]:
        out: list[dict] = []
        page = None
        while True:
            q: dict = {"pageSize": 300}
            if order_by:
                q["orderBy"] = order_by
            if page:
                q["pageToken"] = page
            res = self.http("GET", self._url(self.user_path(*path.split("/")), q), token=self.token())
            out.extend(decode_doc(d) for d in res.get("documents", []))
            page = res.get("nextPageToken")
            if not page:
                return out


# ---------------------------------------------------------------------------
# Background sync manager
# ---------------------------------------------------------------------------

class SyncManager:
    """Queue + worker thread. All public methods are non-blocking and thread safe."""

    def __init__(self, app_dir: str, cfg: dict, save_cfg: Callable[[dict], None],
                 on_status: Callable[[str, str], None],
                 on_remote: Callable[[list[dict]], None] | None = None,
                 http: Callable[..., dict] = http_json,
                 backoff_max: float = 60.0) -> None:
        self.cfg = cfg
        self.save_cfg = save_cfg
        self.on_status = on_status
        self.on_remote = on_remote
        self.http = http
        self.backoff_max = backoff_max
        self.backlog_file = os.path.join(app_dir, "sync_backlog.json")
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._ops: list[dict] = self._load_backlog()
        self._stop = False
        self._pull_requested = True
        self._thread: threading.Thread | None = None
        self.client: FirebaseClient | None = None
        self.last_error = ""

    # ── public API ────────────────────────────────────────────────────
    @property
    def enabled(self) -> bool:
        return bool(self.cfg.get("firebase_enabled", True))

    def start(self) -> None:
        if not self.enabled:
            self.on_status(STATE_DISABLED, "")
            return
        self._build_client()
        if self._thread is None or not self._thread.is_alive():
            self._stop = False
            self._thread = threading.Thread(target=self._run, name="firebase-sync", daemon=True)
            self._thread.start()

    def restart(self) -> None:
        """Re-read config (project/apiKey/enabled) and request a fresh pull."""
        with self._cv:
            self._pull_requested = True
            self._cv.notify_all()
        if not self.enabled:
            self.stop()
            self.on_status(STATE_DISABLED, "")
            return
        self._build_client()
        self.start()

    def stop(self) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify_all()

    def push_message(self, conv_id: str, msg: dict) -> None:
        self._enqueue({"op": "set", "path": f"conversations/{conv_id}/messages/{msg['id']}",
                       "data": {"role": msg.get("role", "user"), "text": msg.get("content", ""),
                                "ts": int(msg.get("ts", time.time() * 1000))}})

    def push_conversation(self, meta: dict, markdown: str | None = None) -> None:
        data = {k: meta.get(k) for k in ("title", "preview", "avatarColor", "createdAt", "updatedAt")}
        if markdown is not None:
            data["markdown"] = markdown
        self._enqueue({"op": "set", "path": f"conversations/{meta['id']}", "data": data})

    def delete_conversation(self, conv_id: str, msg_ids: list[str]) -> None:
        self._enqueue({"op": "delete_conv", "conv": conv_id, "msgs": list(msg_ids)})

    def pending(self) -> int:
        with self._lock:
            return len(self._ops)

    # ── internals ─────────────────────────────────────────────────────
    def _build_client(self) -> None:
        project = (self.cfg.get("firebase_project_id") or DEFAULT_PROJECT_ID).strip()
        key = (self.cfg.get("firebase_api_key") or DEFAULT_API_KEY).strip()
        auth = self.cfg.get("firebase_auth") or {}
        if auth.get("projectId") not in (None, project):
            auth = {}
        if self.client and self.client.project_id == project and self.client.api_key == key:
            return
        self.client = FirebaseClient(project, key, auth, self._save_auth, http=self.http)

    def _save_auth(self, auth: dict) -> None:
        self.cfg["firebase_auth"] = auth
        try:
            self.save_cfg(self.cfg)
        except Exception as exc:
            logger.warning("Could not persist firebase auth: %s", exc)

    def _load_backlog(self) -> list[dict]:
        try:
            if os.path.isfile(self.backlog_file):
                with open(self.backlog_file, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                return data if isinstance(data, list) else []
        except Exception as exc:
            logger.warning("Could not load sync backlog: %s", exc)
        return []

    def _persist_backlog_locked(self) -> None:
        try:
            if self._ops:
                tmp = self.backlog_file + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(self._ops, fh, ensure_ascii=False)
                os.replace(tmp, self.backlog_file)
            elif os.path.isfile(self.backlog_file):
                os.remove(self.backlog_file)
        except Exception as exc:
            logger.warning("Could not persist sync backlog: %s", exc)

    def _enqueue(self, op: dict) -> None:
        with self._cv:
            # Coalesce: a newer "set" on the same path replaces the older one (merge fields)
            if op["op"] == "set":
                for old in self._ops[1:]:  # ops[0] may be in flight
                    if old["op"] == "set" and old["path"] == op["path"]:
                        old["data"].update(op["data"])
                        break
                else:
                    self._ops.append(op)
            else:
                self._ops.append(op)
            self._persist_backlog_locked()
            self._cv.notify_all()
        if self.enabled:
            self.on_status(STATE_SYNCING, "")

    def _execute(self, op: dict) -> None:
        c = self.client
        assert c is not None
        if op["op"] == "set":
            c.set_doc(op["path"], op["data"])
        elif op["op"] == "delete_conv":
            conv = op["conv"]
            ids = set(op.get("msgs") or [])
            try:
                ids |= {d["_id"] for d in c.list_docs(f"conversations/{conv}/messages")}
            except SyncError as exc:
                if getattr(exc, "status", 0) != 404:
                    raise
            for mid in ids:
                c.delete_doc(f"conversations/{conv}/messages/{mid}")
            c.delete_doc(f"conversations/{conv}")

    def pull(self) -> list[dict]:
        """Fetch all conversations (with messages) for this user."""
        c = self.client
        assert c is not None
        convs = c.list_docs("conversations")
        for conv in convs:
            conv["id"] = conv.pop("_id")
            msgs = c.list_docs(f"conversations/{conv['id']}/messages", order_by="ts")
            conv["messages"] = [{"id": m["_id"], "role": m.get("role", "user"),
                                 "content": m.get("text", ""), "ts": m.get("ts", 0)} for m in msgs]
        return convs

    def _run(self) -> None:
        delay = 2.0
        while True:
            with self._cv:
                while not self._stop and not self._ops and not self._pull_requested:
                    self._cv.wait(timeout=30)
                if self._stop:
                    return
                op = self._ops[0] if self._ops else None
                do_pull = self._pull_requested and not self._ops
            try:
                self.on_status(STATE_SYNCING, "")
                self.client.token()  # type: ignore[union-attr]
                if op is not None:
                    self._execute(op)
                    with self._cv:
                        if self._ops and self._ops[0] is op:
                            self._ops.pop(0)
                        self._persist_backlog_locked()
                elif do_pull:
                    remote = self.pull()
                    with self._cv:
                        self._pull_requested = False
                    if self.on_remote:
                        self.on_remote(remote)
                delay = 2.0
                self.last_error = ""
                with self._lock:
                    idle = not self._ops and not self._pull_requested
                if idle:
                    self.on_status(STATE_OK, "")
            except Exception as exc:  # never let the worker die
                self.last_error = str(exc)
                logger.warning("Firebase sync failed: %s", exc)
                self.on_status(STATE_ERROR, self.last_error)
                with self._cv:
                    self._cv.wait(timeout=delay)
                delay = min(delay * 2, self.backoff_max)
