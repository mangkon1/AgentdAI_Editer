"""
main.py
-------
Local AI Coding Agent — Desktop GUI powered by Google Gemini + customtkinter.

Features:
  - Grok-style layout: left conversation sidebar + centered chat with pill header
  - Multi-conversation history (chats/<id>.json + chats/index.json offline cache)
  - Automatic realtime sync to Firebase Cloud Firestore (firebase_sync.py)
  - Modal Settings Popup (CTkToplevel) for API Key, Model, and Workspace
  - Persistent config.json (properly resolved for both dev & PyInstaller .exe)
  - Persistent Chat History (chat_history.json) — resume conversations across restarts
  - Export Chat History to Markdown (CHAT_HISTORY.md) for GitHub & documentation
  - Multi-turn AI conversation with automatic function calling (tools)
  - Threading so the UI never freezes while the AI is working
  - Universal Ctrl+C / Ctrl+V / Ctrl+A / Ctrl+X / Ctrl+Z support for Thai & English
  - Right-click context menus (Cut / Copy / Paste / Select All)
  - Native Thai & English typography using Leelawadee UI font
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import queue
import re
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
from google import genai
from google.genai import types as genai_types

import agent_tools as tools
import firebase_sync as fbsync
from conversation_store import AVATAR_COLORS, ConversationStore, build_markdown

# ---------------------------------------------------------------------------
# Path resolution helpers (Bundling & Persistence Compatibility)
# ---------------------------------------------------------------------------

def get_app_dir() -> str:
    """
    Return the persistent directory where the app / .exe resides.
    When running as a PyInstaller standalone .exe, sys.executable points to the .exe folder.
    When running from source, __file__ points to the project folder.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(relative: str) -> str:
    """Return the absolute path to a bundled resource (works for dev & .exe temp folder)."""
    base = getattr(sys, "_MEIPASS", get_app_dir())
    return os.path.join(base, relative)


APP_DIR = get_app_dir()
CONFIG_FILE = os.path.join(APP_DIR, "config.json")
CHAT_HISTORY_FILE = os.path.join(APP_DIR, "chat_history.json")
LOG_FILE = os.path.join(APP_DIR, "app.log")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
APP_TITLE = "🤖 Local AI Coding Agent"

DEFAULT_MODELS = ["gemini-4-argon", "gemini-2.5-pro", "gemini-2.5-flash"]
DEFAULT_WORKSPACE = r"D:\For AI" if os.path.isdir(r"D:\For AI") else os.path.expanduser("~")

# Font configuration — optimized for Windows Thai + English UI
FONT_FAMILY = "Leelawadee UI"  # Windows standard modern Thai font (prevents diacritic overlap)
FONT_CODE   = "Consolas"

# Colour palette — dark charcoal (Grok Bot desktop style)
C_BG          = "#1e1e1e"
C_SIDEBAR     = "#171717"
C_CARD        = "#2b2b2b"
C_SELECTED    = "#2a2a2a"
C_HOVER       = "#242424"
C_ACCENT      = "#ff3b8d"
C_ACCENT_HVR  = "#ff5aa0"
C_ACCENT2     = "#3a3a3a"
C_ACCENT2_HVR = "#4a4a4a"
C_DANGER      = "#da3633"
C_DANGER_HVR  = "#f85149"
C_TEXT        = "#f2f2f2"
C_TEXT_DIM    = "#9a9a9a"
C_BORDER      = "#3a3a3a"
C_USER_BUBBLE = "#3a3a3a"
C_AI_BUBBLE   = "#2b2b2b"
C_CODE_BG     = "#161616"
C_OK          = "#3fb950"
C_WARN        = "#d29922"

SYSTEM_PROMPT = """You are a highly skilled Local AI Coding Agent running on the user's Windows desktop.
You have direct access to the user's file system through built-in tools:

- list_files(directory): Explore the project structure
- read_file(filepath): Read any source code or text file
- write_file(filepath, content): Create or modify files directly
- run_command(command): Execute shell/PowerShell commands in the workspace

GUIDELINES:
1. Always explore the project structure FIRST before making changes.
2. Read existing files to understand the codebase before writing.
3. Be proactive — use tools to verify your work (e.g., run_command to test).
4. Communicate clearly what you are doing at each step.
5. Support both English and Thai language conversations.
6. When writing code, prefer complete, production-ready implementations.
7. Use run_command to install packages, run scripts, or check git status as needed.
"""


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def load_config() -> dict:
    """Load configuration from config.json, returning defaults if missing."""
    defaults = {
        "api_key": "",
        "model": DEFAULT_MODELS[0],
        "workspace": DEFAULT_WORKSPACE,
        "firebase_enabled": True,
        "firebase_project_id": fbsync.DEFAULT_PROJECT_ID,
        "firebase_api_key": fbsync.DEFAULT_API_KEY,
    }
    try:
        if os.path.isfile(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            defaults.update(data)
            logger.info("Loaded config from: %s", CONFIG_FILE)
    except Exception as exc:
        logger.warning("Could not load config: %s", exc)
    return defaults


def save_config(cfg: dict) -> None:
    """Persist configuration to config.json."""
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2, ensure_ascii=False)
        logger.info("Saved config to: %s", CONFIG_FILE)
    except Exception as exc:
        logger.error("Could not save config: %s", exc)


# ---------------------------------------------------------------------------
# Chat History Persistence helpers
# ---------------------------------------------------------------------------

def load_chat_history() -> list[dict]:
    """Load stored chat history from chat_history.json."""
    if os.path.isfile(CHAT_HISTORY_FILE):
        try:
            with open(CHAT_HISTORY_FILE, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception as exc:
            logger.warning("Could not load chat history: %s", exc)
    return []


def save_chat_history(history: list[dict]) -> None:
    """Save chat history list to chat_history.json."""
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(CHAT_HISTORY_FILE, "w", encoding="utf-8") as fh:
            json.dump(history, fh, indent=2, ensure_ascii=False)
    except Exception as exc:
        logger.warning("Could not save chat history: %s", exc)



def export_chat_to_markdown(history: list[dict], target_path: str, title: str | None = None) -> None:
    """Export a conversation into a Markdown file (same format synced to Firestore)."""
    with open(target_path, "w", encoding="utf-8") as fh:
        fh.write(build_markdown(history, title))
    logger.info("Exported chat history to: %s", target_path)


def format_date_separator(ts_ms: int) -> str:
    dt = datetime.datetime.fromtimestamp(ts_ms / 1000) if ts_ms else datetime.datetime.now()
    today = datetime.date.today()
    if dt.date() == today:
        day = "วันนี้"
    elif dt.date() == today - datetime.timedelta(days=1):
        day = "เมื่อวาน"
    else:
        day = dt.strftime("%d/%m/%Y")
    return f"{day} {dt.strftime('%H:%M')}"


class Tooltip:
    """Tiny hover tooltip for any widget."""

    def __init__(self, widget: tk.Widget, text: str = "") -> None:
        self.widget = widget
        self.text = text
        self.tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _show(self, _e=None) -> None:
        if not self.text or self.tip:
            return
        x = self.widget.winfo_rootx() - 120
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{max(x, 0)}+{y}")
        tk.Label(self.tip, text=self.text, bg="#2b2b2b", fg=C_TEXT, justify="left",
                 wraplength=380, padx=8, pady=6, font=(FONT_FAMILY, 9)).pack()

    def _hide(self, _e=None) -> None:
        if self.tip:
            self.tip.destroy()
            self.tip = None



# ---------------------------------------------------------------------------
# Settings Popup Window (Modal Dialog)
# ---------------------------------------------------------------------------

class SettingsDialog(ctk.CTkToplevel):
    """Modern popup dialog for configuring API Key, Model, and Workspace."""

    def __init__(self, parent: App) -> None:
        super().__init__(parent)
        self.parent_app = parent
        self.show_api_key = False

        self.title("⚙️ การตั้งค่าระบบ (Settings)")
        self.geometry("540x700")
        self.resizable(False, False)
        self.configure(fg_color=C_BG)

        # Make modal & centered
        self.transient(parent)
        self.grab_set()
        self._center_window()

        self._build_ui()

    def _center_window(self) -> None:
        self.update_idletasks()
        pw = self.parent_app.winfo_width()
        ph = self.parent_app.winfo_height()
        px = self.parent_app.winfo_x()
        py = self.parent_app.winfo_y()
        w = 540
        h = 700
        x = px + max((pw - w) // 2, 0)
        y = py + max((ph - h) // 2, 0)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build_ui(self) -> None:
        card = ctk.CTkFrame(self, fg_color=C_SIDEBAR, corner_radius=12, border_color=C_BORDER, border_width=1)
        card.pack(fill="both", expand=True, padx=20, pady=20)
        card.columnconfigure(0, weight=1)

        # ── Header ────────────────────────────────────────────────────────
        hdr_frame = ctk.CTkFrame(card, fg_color="transparent")
        hdr_frame.pack(fill="x", padx=20, pady=(20, 10))
        ctk.CTkLabel(
            hdr_frame,
            text="⚙️  การตั้งค่าระบบ (Settings)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=18, weight="bold"),
            text_color=C_TEXT,
        ).pack(side="left")

        ctk.CTkFrame(card, height=1, fg_color=C_BORDER).pack(fill="x", padx=16, pady=(0, 16))

        # ── 1. API Key Section ─────────────────────────────────────────────
        key_lbl_frame = ctk.CTkFrame(card, fg_color="transparent")
        key_lbl_frame.pack(fill="x", padx=20, pady=(0, 4))
        ctk.CTkLabel(
            key_lbl_frame,
            text="Gemini API Key:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            text_color=C_TEXT,
        ).pack(side="left")

        current_key = self.parent_app.config_data.get("api_key", "")
        status_text = "✅ ตั้งค่าแล้ว" if current_key else "⚠️ ยังไม่ได้ตั้งค่า"
        status_color = "#3fb950" if current_key else "#d29922"
        self.key_status_lbl = ctk.CTkLabel(
            key_lbl_frame,
            text=status_text,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=status_color,
        )
        self.key_status_lbl.pack(side="right")

        key_box = ctk.CTkFrame(card, fg_color="transparent")
        key_box.pack(fill="x", padx=20, pady=(0, 14))
        key_box.columnconfigure(0, weight=1)

        self.api_key_var = tk.StringVar(value=current_key)
        self.api_key_entry = ctk.CTkEntry(
            key_box,
            textvariable=self.api_key_var,
            show="•",
            fg_color=C_CARD,
            border_color=C_BORDER,
            text_color=C_TEXT,
            font=ctk.CTkFont(family=FONT_CODE, size=12),
            height=36,
        )
        self.api_key_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.parent_app._attach_context_menu(self.api_key_entry)

        self.eye_btn = ctk.CTkButton(
            key_box,
            text="👁",
            width=38,
            height=36,
            fg_color=C_CARD,
            hover_color=C_BORDER,
            text_color=C_TEXT,
            command=self._toggle_eye,
        )
        self.eye_btn.grid(row=0, column=1, padx=(0, 6))

        paste_btn = ctk.CTkButton(
            key_box,
            text="📋 วาง",
            width=55,
            height=36,
            fg_color=C_ACCENT2,
            hover_color=C_ACCENT2_HVR,
            text_color="white",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            command=self._paste_api_key,
        )
        paste_btn.grid(row=0, column=2)

        # ── 2. Model Selection ─────────────────────────────────────────────
        ctk.CTkLabel(
            card,
            text="Model (เลือกโมเดล Gemini หรือพิมพ์ชื่อโมเดลเอง):",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            text_color=C_TEXT,
        ).pack(anchor="w", padx=20, pady=(0, 4))

        current_model = self.parent_app.config_data.get("model", DEFAULT_MODELS[0])
        self.model_var = tk.StringVar(value=current_model)
        model_values = DEFAULT_MODELS if current_model in DEFAULT_MODELS else DEFAULT_MODELS + [current_model]
        self.model_combo = ctk.CTkComboBox(
            card,
            variable=self.model_var,
            values=model_values,
            fg_color=C_CARD,
            border_color=C_BORDER,
            text_color=C_TEXT,
            dropdown_fg_color=C_CARD,
            dropdown_text_color=C_TEXT,
            button_color=C_ACCENT2,
            button_hover_color=C_ACCENT2_HVR,
            font=ctk.CTkFont(family=FONT_CODE, size=12),
            height=36,
        )
        self.model_combo.pack(fill="x", padx=20, pady=(0, 14))

        # ── 3. Workspace Folder ────────────────────────────────────────────
        ctk.CTkLabel(
            card,
            text="Workspace Folder (โฟลเดอร์ทำงานหลักในเครื่อง):",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            text_color=C_TEXT,
        ).pack(anchor="w", padx=20, pady=(0, 4))

        ws_box = ctk.CTkFrame(card, fg_color="transparent")
        ws_box.pack(fill="x", padx=20, pady=(0, 14))
        ws_box.columnconfigure(0, weight=1)

        current_ws = self.parent_app.config_data.get("workspace", DEFAULT_WORKSPACE)
        self.workspace_var = tk.StringVar(value=current_ws)
        self.workspace_entry = ctk.CTkEntry(
            ws_box,
            textvariable=self.workspace_var,
            fg_color=C_CARD,
            border_color=C_BORDER,
            text_color=C_TEXT,
            font=ctk.CTkFont(family=FONT_CODE, size=11),
            height=36,
        )
        self.workspace_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.parent_app._attach_context_menu(self.workspace_entry)

        browse_btn = ctk.CTkButton(
            ws_box,
            text="📂 เลือกโฟลเดอร์",
            width=110,
            height=36,
            fg_color=C_ACCENT2,
            hover_color=C_ACCENT2_HVR,
            text_color="white",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            command=self._browse_folder,
        )
        browse_btn.grid(row=0, column=1)

        # ── 4. Firebase Sync ───────────────────────────────────────────────
        fb_hdr = ctk.CTkFrame(card, fg_color="transparent")
        fb_hdr.pack(fill="x", padx=20, pady=(0, 4))
        ctk.CTkLabel(
            fb_hdr,
            text="☁️ Firebase Cloud Firestore Sync:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            text_color=C_TEXT,
        ).pack(side="left")
        self.fb_enabled_var = tk.BooleanVar(value=bool(self.parent_app.config_data.get("firebase_enabled", True)))
        ctk.CTkSwitch(
            fb_hdr, text="เปิดใช้งาน", variable=self.fb_enabled_var,
            progress_color=C_ACCENT, text_color=C_TEXT,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
        ).pack(side="right")

        fb_box = ctk.CTkFrame(card, fg_color="transparent")
        fb_box.pack(fill="x", padx=20, pady=(0, 20))
        fb_box.columnconfigure(1, weight=1)
        self.fb_project_var = tk.StringVar(
            value=self.parent_app.config_data.get("firebase_project_id") or fbsync.DEFAULT_PROJECT_ID)
        self.fb_key_var = tk.StringVar(
            value=self.parent_app.config_data.get("firebase_api_key") or fbsync.DEFAULT_API_KEY)
        for r, (lbl, var) in enumerate((("Project ID", self.fb_project_var), ("Web API Key", self.fb_key_var))):
            ctk.CTkLabel(fb_box, text=lbl, text_color=C_TEXT_DIM,
                         font=ctk.CTkFont(family=FONT_FAMILY, size=11)).grid(row=r, column=0, sticky="w", padx=(0, 8), pady=2)
            ent = ctk.CTkEntry(fb_box, textvariable=var, fg_color=C_CARD, border_color=C_BORDER,
                               text_color=C_TEXT, font=ctk.CTkFont(family=FONT_CODE, size=11), height=32)
            ent.grid(row=r, column=1, sticky="ew", pady=2)
            self.parent_app._attach_context_menu(ent)

        # ── Footer / Actions ──────────────────────────────────────────────
        ctk.CTkFrame(card, height=1, fg_color=C_BORDER).pack(fill="x", padx=16, pady=(0, 16))

        btn_box = ctk.CTkFrame(card, fg_color="transparent")
        btn_box.pack(fill="x", padx=20, pady=(0, 16))

        save_btn = ctk.CTkButton(
            btn_box,
            text="💾  บันทึกการตั้งค่า (Save Settings)",
            fg_color=C_ACCENT,
            hover_color=C_ACCENT_HVR,
            text_color="white",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            height=40,
            command=self._save_and_close,
        )
        save_btn.pack(side="left", fill="x", expand=True, padx=(0, 10))

        cancel_btn = ctk.CTkButton(
            btn_box,
            text="ปิด (Close)",
            fg_color=C_CARD,
            hover_color=C_BORDER,
            text_color=C_TEXT,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            height=40,
            width=80,
            command=self.destroy,
        )
        cancel_btn.pack(side="right")

    def _toggle_eye(self) -> None:
        self.show_api_key = not self.show_api_key
        self.api_key_entry.configure(show="" if self.show_api_key else "•")
        self.eye_btn.configure(text="🙈" if self.show_api_key else "👁")

    def _paste_api_key(self) -> None:
        try:
            txt = self.clipboard_get().strip()
            if txt:
                self.api_key_var.set(txt)
        except Exception:
            pass

    def _browse_folder(self) -> None:
        curr = self.workspace_var.get() or DEFAULT_WORKSPACE
        folder = filedialog.askdirectory(title="เลือกโฟลเดอร์ Workspace", initialdir=curr)
        if folder:
            self.workspace_var.set(folder)

    def _save_and_close(self) -> None:
        key = self.api_key_var.get().strip()
        model = self.model_var.get().strip() or DEFAULT_MODELS[0]
        workspace = self.workspace_var.get().strip() or DEFAULT_WORKSPACE

        if not key:
            messagebox.showwarning("ยังไม่ได้ใส่ API Key", "กรุณาระบุ Gemini API Key ก่อนบันทึกครับ")
            return

        # Update parent configuration
        self.parent_app.config_data["api_key"] = key
        self.parent_app.config_data["model"] = model
        self.parent_app.config_data["workspace"] = workspace

        cfg = self.parent_app.config_data
        cfg["firebase_enabled"] = bool(self.fb_enabled_var.get())
        cfg["firebase_project_id"] = self.fb_project_var.get().strip() or fbsync.DEFAULT_PROJECT_ID
        cfg["firebase_api_key"] = self.fb_key_var.get().strip() or fbsync.DEFAULT_API_KEY

        # Persist config to config.json
        save_config(self.parent_app.config_data)
        self.parent_app.sync.restart()

        # Apply workspace to tool runner
        tools.set_workspace(workspace)

        # Reset chat session with updated credentials
        self.parent_app.chat_sessions.clear()

        # Update parent topbar badges
        self.parent_app._update_topbar_badges()

        # Feedback
        self.parent_app.status_var.set(f"✅ บันทึกการตั้งค่าเรียบร้อย (Model: {model}) — พร้อมใช้งาน")
        self.parent_app._add_system_message(
            f"✅ **บันทึกการตั้งค่าเรียบร้อยแล้ว**\n"
            f"• โมเดล: `{model}`\n"
            f"• โฟลเดอร์ Workspace: `{workspace}`"
        )

        messagebox.showinfo(
            "บันทึกสำเร็จ",
            "✅ บันทึกการตั้งค่าเรียบร้อยแล้ว!\n"
            f"ข้อมูลถูกบันทึกลง: {CONFIG_FILE}"
        )
        self.destroy()


# ---------------------------------------------------------------------------
# Main Application Window
# ---------------------------------------------------------------------------

class App(ctk.CTk):
    """Main application window — Grok-style sidebar + chat, synced to Firestore."""

    SIDEBAR_W = 260

    def __init__(self) -> None:
        super().__init__()

        # ── Appearance ───────────────────────────────────────────────────
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        self.configure(fg_color=C_BG)

        # ── State ────────────────────────────────────────────────────────
        self.config_data = load_config()
        self.store = ConversationStore(APP_DIR)
        self.store.migrate_legacy(CHAT_HISTORY_FILE)
        self.current_id: str | None = None
        self.chat_sessions: dict[str, genai.chats.Chat] = {}
        self.is_thinking = False
        self.thinking_conv: str | None = None
        self._ui_queue: queue.Queue = queue.Queue()   # thread → UI messages
        self._msg_row = 0
        self._last_sep_ts = 0
        self._conv_rows: dict[str, ctk.CTkFrame] = {}
        self._sync_error_shown = ""

        # ── Firebase sync (background worker) ───────────────────────────
        self.sync = fbsync.SyncManager(
            APP_DIR, self.config_data, save_config,
            on_status=lambda s, d: self._q("sync_status", s, d),
            on_remote=lambda remote: self._q("remote_pull", remote),
        )

        # ── Window setup ─────────────────────────────────────────────────
        self.title(APP_TITLE)
        self.geometry("1280x820")
        self.minsize(980, 650)

        # Apply workspace to tools
        tools.set_workspace(self.config_data.get("workspace", DEFAULT_WORKSPACE))

        # ── Build UI ─────────────────────────────────────────────────────
        self._build_layout()
        self._setup_universal_shortcuts()

        # ── Restore conversations ───────────────────────────────────────
        convs = self.store.list()
        if convs:
            self._select_conversation(convs[0]["id"])
        else:
            self._new_conversation()
        self._refresh_sidebar()

        # ── Start UI update loop + sync ─────────────────────────────────
        self.after(50, self._process_ui_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.sync.start()

        logger.info("Application started successfully")

    @property
    def chat_history(self) -> list[dict]:
        if not self.current_id:
            return []
        return self.store.get(self.current_id).get("messages", [])

    # ────────────────────────────────────────────────────────────────────
    # Universal Keyboard Shortcuts & Context Menus
    # ────────────────────────────────────────────────────────────────────

    def _setup_universal_shortcuts(self) -> None:
        """
        Global handler for Ctrl+C, Ctrl+V, Ctrl+A, Ctrl+X, Ctrl+Z that uses
        physical virtual key codes (event.keycode) so shortcuts work seamlessly
        regardless of whether keyboard layout is in English or Thai!
        """
        self.bind_all("<KeyPress>", self._on_universal_keypress, add="+")

    def _on_universal_keypress(self, event: tk.Event) -> str | None:
        if not (event.state & 4):
            return None

        code = event.keycode
        keysym = (event.keysym or "").lower()

        is_a = (code == 65) or (keysym == "a")
        is_c = (code == 67) or (keysym == "c")
        is_v = (code == 86) or (keysym == "v")
        is_x = (code == 88) or (keysym == "x")
        is_z = (code == 90) or (keysym == "z")

        if not (is_a or is_c or is_v or is_x or is_z):
            return None

        widget = event.widget
        if hasattr(widget, "_entry"):
            widget = widget._entry
        elif hasattr(widget, "_textbox"):
            widget = widget._textbox

        if isinstance(widget, tk.Entry):
            if is_a:
                widget.selection_range(0, tk.END)
                widget.icursor(tk.END)
                return "break"
            elif is_c:
                if widget.selection_present():
                    try:
                        text = widget.selection_get()
                        self.clipboard_clear()
                        self.clipboard_append(text)
                    except Exception:
                        pass
                return "break"
            elif is_v:
                try:
                    text = self.clipboard_get()
                    if text:
                        if widget.selection_present():
                            widget.delete("sel.first", "sel.last")
                        widget.insert(tk.INSERT, text)
                except Exception:
                    pass
                return "break"
            elif is_x:
                if widget.selection_present():
                    try:
                        text = widget.selection_get()
                        self.clipboard_clear()
                        self.clipboard_append(text)
                        widget.delete("sel.first", "sel.last")
                    except Exception:
                        pass
                return "break"

        elif isinstance(widget, tk.Text):
            if is_a:
                widget.tag_add("sel", "1.0", "end-1c")
                widget.mark_set("insert", "end-1c")
                return "break"
            elif is_c:
                if widget.tag_ranges("sel"):
                    try:
                        text = widget.get("sel.first", "sel.last")
                        self.clipboard_clear()
                        self.clipboard_append(text)
                    except Exception:
                        pass
                return "break"
            elif is_v:
                state = str(widget.cget("state"))
                if state != "disabled":
                    try:
                        text = self.clipboard_get()
                        if text:
                            if widget.tag_ranges("sel"):
                                widget.delete("sel.first", "sel.last")
                            widget.insert("insert", text)
                    except Exception:
                        pass
                return "break"
            elif is_x:
                state = str(widget.cget("state"))
                if state != "disabled" and widget.tag_ranges("sel"):
                    try:
                        text = widget.get("sel.first", "sel.last")
                        self.clipboard_clear()
                        self.clipboard_append(text)
                        widget.delete("sel.first", "sel.last")
                    except Exception:
                        pass
                return "break"
            elif is_z:
                try:
                    widget.edit_undo()
                except Exception:
                    pass
                return "break"

        return None

    def _attach_context_menu(self, widget: tk.Widget) -> None:
        """Attach a modern Right-Click Context Menu (Cut / Copy / Paste / Select All)."""
        target = widget
        if hasattr(widget, "_entry"):
            target = widget._entry
        elif hasattr(widget, "_textbox"):
            target = widget._textbox

        menu = tk.Menu(
            self,
            tearoff=0,
            bg=C_CARD,
            fg=C_TEXT,
            activebackground=C_ACCENT2,
            activeforeground="#ffffff",
            activeborderwidth=0,
            bd=1,
            font=(FONT_FAMILY, 10),
        )

        def do_cut():
            if isinstance(target, tk.Entry):
                if target.selection_present():
                    try:
                        text = target.selection_get()
                        self.clipboard_clear()
                        self.clipboard_append(text)
                        target.delete("sel.first", "sel.last")
                    except Exception:
                        pass
            elif isinstance(target, tk.Text):
                if target.tag_ranges("sel"):
                    try:
                        text = target.get("sel.first", "sel.last")
                        self.clipboard_clear()
                        self.clipboard_append(text)
                        if str(target.cget("state")) != "disabled":
                            target.delete("sel.first", "sel.last")
                    except Exception:
                        pass

        def do_copy():
            try:
                text = ""
                if isinstance(target, tk.Entry):
                    if target.selection_present():
                        text = target.selection_get()
                elif isinstance(target, tk.Text):
                    if target.tag_ranges("sel"):
                        text = target.get("sel.first", "sel.last")
                if text:
                    self.clipboard_clear()
                    self.clipboard_append(text)
            except Exception:
                pass

        def do_paste():
            try:
                text = self.clipboard_get()
                if not text:
                    return
                if isinstance(target, tk.Entry):
                    if target.selection_present():
                        target.delete("sel.first", "sel.last")
                    target.insert(tk.INSERT, text)
                elif isinstance(target, tk.Text):
                    if str(target.cget("state")) != "disabled":
                        if target.tag_ranges("sel"):
                            target.delete("sel.first", "sel.last")
                        target.insert("insert", text)
            except Exception:
                pass

        def do_select_all():
            if isinstance(target, tk.Entry):
                target.selection_range(0, tk.END)
                target.icursor(tk.END)
            elif isinstance(target, tk.Text):
                target.tag_add("sel", "1.0", "end-1c")

        menu.add_command(label="✂️  Cut (ตัด)", command=do_cut)
        menu.add_command(label="📋  Copy (คัดลอก)", command=do_copy)
        menu.add_command(label="📥  Paste (วาง)", command=do_paste)
        menu.add_separator()
        menu.add_command(label="🔲  Select All (เลือกทั้งหมด)", command=do_select_all)

        def popup(event):
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        target.bind("<Button-3>", popup, add="+")
        if target is not widget:
            widget.bind("<Button-3>", popup, add="+")

    # ────────────────────────────────────────────────────────────────────
    # Layout construction — Sidebar + Chat (Grok Bot desktop style)
    # ────────────────────────────────────────────────────────────────────

    def _font(self, size: int = 13, weight: str = "normal", code: bool = False) -> ctk.CTkFont:
        return ctk.CTkFont(family=FONT_CODE if code else FONT_FAMILY, size=size, weight=weight)

    def _build_layout(self) -> None:
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=0, minsize=self.SIDEBAR_W)
        self.grid_columnconfigure(1, weight=1)
        self._build_sidebar()
        self._build_main()

    # ── Sidebar ──────────────────────────────────────────────────────────

    def _build_sidebar(self) -> None:
        sb = ctk.CTkFrame(self, fg_color=C_SIDEBAR, corner_radius=0, width=self.SIDEBAR_W)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        sb.grid_columnconfigure(0, weight=1)
        sb.grid_rowconfigure(3, weight=1)

        # Top: round search + round new-chat buttons
        top = ctk.CTkFrame(sb, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 4))
        ctk.CTkButton(
            top, text="🔍", width=38, height=38, corner_radius=19,
            fg_color=C_CARD, hover_color=C_ACCENT2_HVR, text_color=C_TEXT,
            font=self._font(14), command=self._toggle_search,
        ).pack(side="left")
        ctk.CTkButton(
            top, text="+", width=38, height=38, corner_radius=19,
            fg_color=C_CARD, hover_color=C_ACCENT2_HVR, text_color=C_TEXT,
            font=self._font(20, "bold"), command=self._new_conversation,
        ).pack(side="right")

        # App avatar / logo + name
        brand = ctk.CTkFrame(sb, fg_color="transparent")
        brand.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self._avatar(brand, 76, C_ACCENT, "🤖", 32).pack(pady=(0, 6))
        ctk.CTkLabel(brand, text="Local AI Agent", text_color=C_TEXT, font=self._font(16, "bold")).pack()
        self.sidebar_model_lbl = ctk.CTkLabel(brand, text="", text_color=C_TEXT_DIM, font=self._font(11))
        self.sidebar_model_lbl.pack()

        # Search entry (hidden until 🔍 pressed)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._refresh_sidebar())
        self.search_entry = ctk.CTkEntry(
            sb, textvariable=self.search_var, placeholder_text="ค้นหาแชท...",
            fg_color=C_CARD, border_color=C_BORDER, text_color=C_TEXT,
            corner_radius=18, height=36, font=self._font(12),
        )
        self._attach_context_menu(self.search_entry)
        self._search_visible = False

        # Conversation list
        self.conv_list = ctk.CTkScrollableFrame(
            sb, fg_color=C_SIDEBAR, corner_radius=0,
            scrollbar_button_color=C_SIDEBAR, scrollbar_button_hover_color=C_BORDER,
        )
        self.conv_list.grid(row=3, column=0, sticky="nsew", padx=6, pady=(4, 4))
        self.conv_list.grid_columnconfigure(0, weight=1)

        # Bottom: settings
        ctk.CTkButton(
            sb, text="⚙️  ตั้งค่า (Settings)", height=40, corner_radius=20,
            fg_color=C_CARD, hover_color=C_ACCENT2_HVR, text_color=C_TEXT,
            font=self._font(12, "bold"), command=self._open_settings_popup,
        ).grid(row=4, column=0, sticky="ew", padx=14, pady=14)

    def _toggle_search(self) -> None:
        self._search_visible = not self._search_visible
        if self._search_visible:
            self.search_entry.grid(row=2, column=0, sticky="ew", padx=14, pady=(4, 4))
            self.search_entry.focus_set()
        else:
            self.search_var.set("")
            self.search_entry.grid_forget()

    def _refresh_sidebar(self) -> None:
        for w in self.conv_list.winfo_children():
            w.destroy()
        self._conv_rows.clear()
        query = self.search_var.get().strip().lower() if hasattr(self, "search_var") else ""
        row = 0
        for meta in self.store.list():
            title = meta.get("title") or "แชทใหม่"
            preview = meta.get("preview") or ""
            if query and query not in title.lower() and query not in preview.lower():
                continue
            self._build_conv_row(row, meta)
            row += 1
        if row == 0:
            ctk.CTkLabel(self.conv_list, text="ไม่พบแชท" if query else "ยังไม่มีแชท",
                         text_color=C_TEXT_DIM, font=self._font(12)).grid(row=0, column=0, pady=20)

    def _build_conv_row(self, row: int, meta: dict) -> None:
        cid = meta["id"]
        selected = cid == self.current_id
        frame = ctk.CTkFrame(self.conv_list, fg_color=C_SELECTED if selected else "transparent",
                             corner_radius=14, height=62)
        frame.grid(row=row, column=0, sticky="ew", padx=2, pady=2)
        frame.grid_columnconfigure(1, weight=1)
        title = meta.get("title") or "แชทใหม่"
        avatar = self._avatar(frame, 42, meta.get("avatarColor") or AVATAR_COLORS[0], self._initial(title), 16)
        avatar.grid(row=0, column=0, rowspan=2, padx=(10, 10), pady=10)
        t_lbl = ctk.CTkLabel(frame, text=self._truncate(title, 24), anchor="w", text_color=C_TEXT,
                             font=self._font(13, "bold"))
        t_lbl.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=(10, 0))
        p_lbl = ctk.CTkLabel(frame, text=self._truncate(meta.get("preview") or "ยังไม่มีข้อความ", 30),
                             anchor="w", text_color=C_TEXT_DIM, font=self._font(11))
        p_lbl.grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=(0, 10))

        def on_enter(_e=None):
            if cid != self.current_id:
                frame.configure(fg_color=C_HOVER)

        def on_leave(_e=None):
            if cid != self.current_id:
                frame.configure(fg_color="transparent")

        for w in (frame, avatar, avatar.label, t_lbl, p_lbl):
            w.bind("<Button-1>", lambda _e, c=cid: self._select_conversation(c))
            w.bind("<Button-3>", lambda e, c=cid: self._conv_context_menu(e, c))
            w.bind("<Enter>", on_enter, add="+")
            w.bind("<Leave>", on_leave, add="+")
        self._conv_rows[cid] = frame

    def _avatar(self, parent, size: int, color: str, text: str, font_size: int) -> ctk.CTkFrame:
        """Perfectly round avatar: fixed-size frame (no propagation) + centered label."""
        circle = ctk.CTkFrame(parent, width=size, height=size, corner_radius=size // 2,
                              fg_color=color, bg_color="transparent")
        circle.pack_propagate(False)
        circle.grid_propagate(False)
        lbl = ctk.CTkLabel(circle, text=text, fg_color="transparent", text_color="white",
                           font=self._font(font_size, "bold"))
        lbl.place(relx=0.5, rely=0.5, anchor="center")
        circle.label = lbl  # type: ignore[attr-defined]
        return circle

    @staticmethod
    def _initial(title: str) -> str:
        for ch in (title or "").strip():
            if ch in "เแโใไ" or not ch.isalnum():
                continue
            return ch.upper()
        return "?"

    @staticmethod
    def _truncate(text: str, n: int) -> str:
        text = " ".join(str(text).split())
        return text if len(text) <= n else text[: n - 1] + "…"

    def _conv_context_menu(self, event: tk.Event, conv_id: str) -> None:
        menu = tk.Menu(self, tearoff=0, bg=C_CARD, fg=C_TEXT, activebackground=C_ACCENT,
                       activeforeground="#ffffff", bd=1, font=(FONT_FAMILY, 10))
        menu.add_command(label="✏️  เปลี่ยนชื่อ (Rename)", command=lambda: self._rename_conversation(conv_id))
        menu.add_command(label="📄  ส่งออก Markdown", command=lambda: self._export_markdown(conv_id))
        menu.add_separator()
        menu.add_command(label="🗑  ลบแชท (Delete)", command=lambda: self._delete_conversation(conv_id))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ── Main area ────────────────────────────────────────────────────────

    def _build_main(self) -> None:
        main = ctk.CTkFrame(self, fg_color=C_BG, corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_rowconfigure(1, weight=1)
        main.grid_columnconfigure(0, weight=1)

        # Header: model badge (left) · pill with avatar+name (center) · sync + export (right)
        header = ctk.CTkFrame(main, fg_color=C_BG, corner_radius=0, height=64)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)

        self.model_badge = ctk.CTkLabel(header, text="", fg_color=C_CARD, corner_radius=12,
                                        text_color=C_TEXT_DIM, font=self._font(11, code=True), padx=10, pady=4)
        self.model_badge.place(x=16, rely=0.5, anchor="w")
        self.ws_badge = self.model_badge  # backwards compat for _update_topbar_badges

        pill = ctk.CTkFrame(header, fg_color=C_SELECTED, corner_radius=22, height=44)
        pill.place(relx=0.5, rely=0.5, anchor="center")
        self.header_avatar = self._avatar(pill, 30, AVATAR_COLORS[0], "", 13)
        self.header_avatar.pack(side="left", padx=(8, 8), pady=7)
        self.header_title = ctk.CTkLabel(pill, text="", text_color=C_TEXT, font=self._font(14, "bold"))
        self.header_title.pack(side="left", padx=(0, 16))

        right = ctk.CTkFrame(header, fg_color="transparent")
        right.place(relx=1.0, x=-16, rely=0.5, anchor="e")
        self.sync_lbl = ctk.CTkLabel(right, text="", text_color=C_TEXT_DIM, font=self._font(11))
        self.sync_lbl.pack(side="left", padx=(0, 10))
        self.sync_tip = Tooltip(self.sync_lbl, "")
        ctk.CTkButton(
            right, text="📄 ส่งออก Markdown", width=130, height=32, corner_radius=16,
            fg_color=C_CARD, hover_color=C_ACCENT2_HVR, text_color=C_TEXT,
            font=self._font(11, "bold"), command=self._export_markdown,
        ).pack(side="left")

        self._update_topbar_badges()

        # Messages
        self.messages_frame = ctk.CTkScrollableFrame(
            main, fg_color=C_BG, scrollbar_button_color=C_BG, scrollbar_button_hover_color=C_BORDER,
        )
        self.messages_frame.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        self.messages_frame.columnconfigure(0, weight=1)

        # Composer
        comp_wrap = ctk.CTkFrame(main, fg_color=C_BG, corner_radius=0)
        comp_wrap.grid(row=2, column=0, sticky="ew", padx=40, pady=(6, 4))
        comp_wrap.columnconfigure(0, weight=1)
        composer = ctk.CTkFrame(comp_wrap, fg_color=C_CARD, corner_radius=26,
                                border_width=1, border_color=C_BORDER)
        composer.grid(row=0, column=0, sticky="ew")
        composer.columnconfigure(1, weight=1)

        self.input_box = ctk.CTkTextbox(
            composer, height=64, fg_color=C_CARD, border_width=0, text_color=C_TEXT,
            font=self._font(13), wrap="word",
        )
        self.input_box.grid(row=0, column=0, columnspan=3, padx=18, pady=(12, 0), sticky="ew")
        self.input_box.bind("<Return>", self._on_enter_key)
        self.input_box.bind("<Shift-Return>", lambda e: None)
        self._attach_context_menu(self.input_box)

        self.plus_btn = ctk.CTkButton(
            composer, text="+", width=36, height=36, corner_radius=18,
            fg_color="transparent", border_width=1, border_color=C_BORDER,
            hover_color=C_ACCENT2_HVR, text_color=C_TEXT, font=self._font(18, "bold"),
            command=self._composer_plus_menu,
        )
        self.plus_btn.grid(row=1, column=0, padx=(12, 0), pady=(4, 12), sticky="w")

        self.send_btn = ctk.CTkButton(
            composer, text="↑", width=40, height=40, corner_radius=20,
            fg_color=C_ACCENT, hover_color=C_ACCENT_HVR, text_color="white",
            font=self._font(18, "bold"), command=self._on_send,
        )
        self.send_btn.grid(row=1, column=2, padx=(0, 12), pady=(4, 12), sticky="e")

        self.status_var = tk.StringVar(value="✅ Ready — พิมพ์ข้อความแล้วกด Enter ได้เลย (Shift+Enter ขึ้นบรรทัดใหม่)")
        ctk.CTkLabel(main, textvariable=self.status_var, text_color=C_TEXT_DIM,
                     font=self._font(11)).grid(row=3, column=0, pady=(0, 8))

    def _composer_plus_menu(self) -> None:
        menu = tk.Menu(self, tearoff=0, bg=C_CARD, fg=C_TEXT, activebackground=C_ACCENT,
                       activeforeground="#ffffff", bd=1, font=(FONT_FAMILY, 10))
        menu.add_command(label="💬  แชทใหม่", command=self._new_conversation)
        menu.add_command(label="📎  แทรกพาธไฟล์", command=self._insert_file_path)
        menu.add_command(label="📄  ส่งออก Markdown", command=self._export_markdown)
        x = self.plus_btn.winfo_rootx()
        y = self.plus_btn.winfo_rooty() - 90
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _insert_file_path(self) -> None:
        ws = self.config_data.get("workspace", DEFAULT_WORKSPACE)
        path = filedialog.askopenfilename(title="เลือกไฟล์", initialdir=ws)
        if path and not self.is_thinking:
            self.input_box.insert("insert", path)

    def _update_topbar_badges(self) -> None:
        model = self.config_data.get("model", DEFAULT_MODELS[0])
        ws = self.config_data.get("workspace", DEFAULT_WORKSPACE)
        short_ws = os.path.basename(ws) or ws
        self.model_badge.configure(text=f"🤖 {model} · 📁 {short_ws}")
        if hasattr(self, "sidebar_model_lbl"):
            self.sidebar_model_lbl.configure(text=model)

    def _update_header(self) -> None:
        conv = self.store.get(self.current_id) if self.current_id else {}
        title = conv.get("title") or "แชทใหม่"
        self.header_title.configure(text=self._truncate(title, 40))
        self.header_avatar.configure(fg_color=conv.get("avatarColor") or AVATAR_COLORS[0])
        self.header_avatar.label.configure(text=self._initial(title))

    def _open_settings_popup(self) -> None:
        SettingsDialog(self)

    # ────────────────────────────────────────────────────────────────────
    # Conversations
    # ────────────────────────────────────────────────────────────────────

    def _new_conversation(self) -> None:
        if self.current_id:
            cur = self.store.get(self.current_id)
            if not any(m.get("role") in ("user", "assistant") for m in cur.get("messages", [])):
                self.input_box.focus_set()
                return  # current chat is already empty → reuse it
        conv = self.store.create()
        self._select_conversation(conv["id"])
        self.input_box.focus_set()

    def _select_conversation(self, conv_id: str) -> None:
        self.current_id = conv_id
        self._render_conversation()
        self._update_header()
        self._refresh_sidebar()
        self._set_input_enabled(not self.is_thinking)

    def _render_conversation(self) -> None:
        for w in self.messages_frame.winfo_children():
            w.destroy()
        self._msg_row = 0
        self._last_sep_ts = 0
        msgs = self.chat_history
        if not any(m.get("role") in ("user", "assistant") for m in msgs):
            self._show_welcome_message()
        for msg in msgs:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            self._maybe_date_separator(msg.get("ts") or 0)
            if role in ("user", "assistant"):
                self._render_bubble_widget(role, content)
            elif role == "system":
                self._render_system_widget(content)
        self._scroll_to_bottom()

    def _rename_conversation(self, conv_id: str) -> None:
        conv = self.store.get(conv_id)
        dlg = ctk.CTkInputDialog(text=f"ชื่อใหม่ของแชท:\n(เดิม: {conv.get('title')})", title="เปลี่ยนชื่อแชท")
        new_title = dlg.get_input()
        if new_title and new_title.strip():
            self.store.rename(conv_id, new_title)
            self.sync.push_conversation(self.store.get(conv_id))
            self._refresh_sidebar()
            if conv_id == self.current_id:
                self._update_header()

    def _delete_conversation(self, conv_id: str) -> None:
        if self.is_thinking and self.thinking_conv == conv_id:
            messagebox.showinfo("กรุณารอ", "กรุณารอ AI ทำงานเสร็จก่อนลบแชทนี้ครับ")
            return
        title = self.store.get(conv_id).get("title")
        if not messagebox.askyesno("ยืนยันการลบ", f"ต้องการลบแชท \"{title}\" ใช่หรือไม่?\n(จะถูกลบจาก Firebase ด้วย)"):
            return
        msg_ids = self.store.delete(conv_id)
        self.chat_sessions.pop(conv_id, None)
        self.sync.delete_conversation(conv_id, msg_ids)
        if conv_id == self.current_id:
            self.current_id = None
            convs = self.store.list()
            if convs:
                self._select_conversation(convs[0]["id"])
            else:
                self._new_conversation()
        self._refresh_sidebar()

    # ────────────────────────────────────────────────────────────────────
    # Message rendering helpers
    # ────────────────────────────────────────────────────────────────────

    def _show_welcome_message(self) -> None:
        self._render_system_widget(
            "👋  ยินดีต้อนรับสู่ **Local AI Coding Agent**!\n\n"
            "• คลิก **⚙️ ตั้งค่า (Settings)** มุมซ้ายล่าง เพื่อใส่ Gemini API Key และเลือก Workspace\n"
            "• แต่ละแชทถูกบันทึกในเครื่อง (chats/) และซิงก์ขึ้น Firebase อัตโนมัติ\n"
            "• กด **+** มุมซ้ายบนเพื่อเริ่มแชทใหม่ · คลิกขวาที่แชทเพื่อเปลี่ยนชื่อ/ลบ\n"
            "• คลิก **📄 ส่งออก Markdown** เพื่อเซฟบทสนทนาเป็นไฟล์ `.md`\n\n"
            "ตัวอย่างคำสั่งที่สั่งได้:\n"
            "• `สร้างเว็บแอป Flask อย่างง่ายใน workspace`\n"
            "• `อ่านไฟล์ main.py แล้วอธิบายให้ฉันฟัง`\n"
            "• `รัน pip install requests แล้วแจ้งผลให้ทราบ`"
        )

    def _maybe_date_separator(self, ts: int) -> None:
        if not ts:
            return
        if self._last_sep_ts and ts - self._last_sep_ts < 30 * 60 * 1000:
            return
        self._last_sep_ts = ts
        ctk.CTkLabel(self.messages_frame, text=format_date_separator(ts), text_color=C_TEXT_DIM,
                     font=self._font(11)).grid(row=self._msg_row, column=0, pady=(14, 4))
        self._msg_row += 1

    def _add_message(self, conv_id: str, role: str, text: str) -> None:
        """Persist locally, queue Firestore write, render if visible."""
        if conv_id not in self.store.metas:
            return  # conversation deleted meanwhile
        msg = self.store.add_message(conv_id, role, text)
        meta = self.store.get(conv_id)
        self.sync.push_message(conv_id, msg)
        self.sync.push_conversation(meta, self.store.markdown(conv_id) if role == "assistant" else None)
        if conv_id == self.current_id:
            self._maybe_date_separator(msg["ts"])
            self._render_bubble_widget(role, text)
            self._scroll_to_bottom()
            self._update_header()
        self._refresh_sidebar()

    def _render_bubble_widget(self, role: str, text: str) -> None:
        is_user = role == "user"
        outer = ctk.CTkFrame(self.messages_frame, fg_color="transparent")
        outer.grid(row=self._msg_row, column=0, sticky="ew", padx=28, pady=(6, 6))
        outer.columnconfigure(0, weight=1)
        self._msg_row += 1

        bubble = ctk.CTkFrame(outer, fg_color=C_USER_BUBBLE if is_user else C_AI_BUBBLE, corner_radius=18)
        if is_user:
            bubble.grid(row=0, column=0, sticky="e", padx=(140, 0))
        else:
            bubble.grid(row=0, column=0, sticky="w", padx=(0, 140))
        bubble.columnconfigure(0, weight=1)
        self._render_message_content(bubble, text)

    def _render_message_content(self, parent: ctk.CTkFrame, text: str, wrap: int = 640) -> None:
        """Render text with code block detection."""
        parts = re.split(r"(```[\s\S]*?```)", text)
        row = 0
        for part in parts:
            if part.startswith("```") and part.endswith("```"):
                inner = part[3:-3]
                newline_idx = inner.find("\n")
                code_body = inner[newline_idx + 1:] if newline_idx != -1 else inner

                code_frame = ctk.CTkFrame(parent, fg_color=C_CODE_BG, corner_radius=10)
                code_frame.grid(row=row, column=0, sticky="ew", padx=10, pady=(6, 6))
                code_frame.columnconfigure(0, weight=1)

                code_label = ctk.CTkTextbox(
                    code_frame,
                    fg_color=C_CODE_BG,
                    text_color="#79c0ff",
                    font=self._font(12, code=True),
                    wrap="none",
                    activate_scrollbars=True,
                    border_width=0,
                    width=wrap,
                    height=min(max(code_body.count("\n") + 2, 3), 30) * 20,
                )
                code_label.grid(row=0, column=0, sticky="ew", padx=8, pady=6)
                code_label.insert("1.0", code_body.strip())
                code_label.configure(state="disabled")
                self._attach_context_menu(code_label)
            elif part.strip():
                ctk.CTkLabel(
                    parent,
                    text=part.strip(),
                    text_color=C_TEXT,
                    font=self._font(13),
                    wraplength=wrap,
                    justify="left",
                    anchor="w",
                ).grid(row=row, column=0, sticky="w", padx=16, pady=(8, 8))
            row += 1

    def _add_system_message(self, text: str, conv_id: str | None = None, persist: bool = True) -> None:
        conv_id = conv_id or self.current_id
        if persist and conv_id and conv_id in self.store.metas:
            self.store.add_message(conv_id, "system", text)  # local only, not synced
        if conv_id == self.current_id:
            self._render_system_widget(text)
            self._scroll_to_bottom()

    def _render_system_widget(self, text: str) -> None:
        frame = ctk.CTkFrame(self.messages_frame, fg_color=C_SELECTED, corner_radius=14)
        frame.grid(row=self._msg_row, column=0, sticky="ew", padx=80, pady=10)
        frame.columnconfigure(0, weight=1)
        self._msg_row += 1
        ctk.CTkLabel(frame, text=text.replace("**", ""), text_color=C_TEXT_DIM, font=self._font(12),
                     wraplength=700, justify="left", anchor="w").grid(row=0, column=0, sticky="ew", padx=16, pady=10)

    def _add_tool_indicator(self, conv_id: str, tool_name: str, detail: str = "") -> None:
        if conv_id != self.current_id:
            return
        icons = {"list_files": "📂", "read_file": "📄", "write_file": "✍️", "run_command": "⚡"}
        label_text = f"{icons.get(tool_name, '🔧')} Tool: {tool_name}"
        if detail:
            label_text += f"  →  {detail[:80]}"
        indicator = ctk.CTkFrame(self.messages_frame, fg_color="#232323", corner_radius=12)
        indicator.grid(row=self._msg_row, column=0, sticky="w", padx=40, pady=(2, 2))
        self._msg_row += 1
        ctk.CTkLabel(indicator, text=label_text, text_color=C_OK,
                     font=self._font(11, code=True)).grid(row=0, column=0, sticky="w", padx=12, pady=4)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:
        self.after(80, lambda: self.messages_frame._parent_canvas.yview_moveto(1.0))

    # ────────────────────────────────────────────────────────────────────
    # Markdown Export (manual)
    # ────────────────────────────────────────────────────────────────────

    def _export_markdown(self, conv_id: str | None = None) -> None:
        conv_id = conv_id or self.current_id
        conv = self.store.get(conv_id) if conv_id else {}
        history = conv.get("messages", [])
        if not history:
            messagebox.showinfo("ไม่มีข้อความ", "ยังไม่มีประวัติการสนทนาให้ส่งออกครับ")
            return
        workspace = self.config_data.get("workspace", DEFAULT_WORKSPACE)
        default_name = f"CHAT_HISTORY_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        target_file = filedialog.asksaveasfilename(
            title="บันทึกประวัติการแชทเป็น Markdown",
            initialdir=workspace,
            initialfile=default_name,
            defaultextension=".md",
            filetypes=[("Markdown files", "*.md"), ("All files", "*.*")],
        )
        if target_file:
            try:
                export_chat_to_markdown(history, target_file, conv.get("title"))
                self.status_var.set(f"📄 ส่งออก Markdown สำเร็จ: {os.path.basename(target_file)}")
                messagebox.showinfo("ส่งออกสำเร็จ", f"✅ ส่งออกประวัติการแชทเรียบร้อยแล้ว!\n\nไฟล์: {target_file}")
            except Exception as exc:
                messagebox.showerror("เกิดข้อผิดพลาด", f"ไม่สามารถบันทึกไฟล์ได้: {exc}")

    # ────────────────────────────────────────────────────────────────────
    # Firebase sync callbacks (run on UI thread via queue)
    # ────────────────────────────────────────────────────────────────────

    def _on_sync_status(self, state: str, detail: str) -> None:
        if state == fbsync.STATE_OK:
            self.sync_lbl.configure(text="✅ บันทึกขึ้น Firebase แล้ว", text_color=C_OK)
            self.sync_tip.text = f"Firestore: {self.config_data.get('firebase_project_id')}"
            self._sync_error_shown = ""
        elif state == fbsync.STATE_SYNCING:
            self.sync_lbl.configure(text="⏳ กำลังซิงก์...", text_color=C_TEXT_DIM)
        elif state == fbsync.STATE_ERROR:
            pending = self.sync.pending()
            self.sync_lbl.configure(text="⚠️ ซิงก์ไม่สำเร็จ", text_color=C_WARN)
            self.sync_tip.text = f"{detail}\n(ค้างในคิว {pending} รายการ — จะลองใหม่อัตโนมัติ)"
            if detail and detail != self._sync_error_shown:
                self._sync_error_shown = detail
                hint = ""
                if any(k in detail for k in ("OPERATION_NOT_ALLOWED", "ADMIN_ONLY", "CONFIGURATION_NOT_FOUND")):
                    hint = ("\n💡 ไปที่ Firebase Console > Authentication กด Get started "
                            "แล้วเปิด Sign-in method > Anonymous")
                self._add_system_message(f"⚠️ ซิงก์ Firebase ไม่สำเร็จ: {detail}{hint}\n"
                                         "ข้อมูลยังถูกเก็บในเครื่องและจะซิงก์ให้อัตโนมัติเมื่อเชื่อมต่อได้",
                                         persist=False)
        else:
            self.sync_lbl.configure(text="☁️ ปิดการซิงก์ Firebase", text_color=C_TEXT_DIM)
            self.sync_tip.text = "เปิดได้ใน ⚙️ ตั้งค่า"

    def _on_remote_pull(self, remote: list[dict]) -> None:
        try:
            changed, to_upload = self.store.merge_remote(remote)
        except Exception as exc:
            logger.warning("Merge remote failed: %s", exc)
            return
        for cid in to_upload:
            conv = self.store.get(cid)
            chat_msgs = [m for m in conv.get("messages", []) if m.get("role") in ("user", "assistant")]
            if not chat_msgs:
                continue
            for m in chat_msgs:
                if "id" in m:
                    self.sync.push_message(cid, m)
            self.sync.push_conversation(conv, self.store.markdown(cid))
        self._refresh_sidebar()
        if self.current_id in changed and not self.is_thinking:
            self._render_conversation()
            self._update_header()

    # ────────────────────────────────────────────────────────────────────
    # UI queue
    # ────────────────────────────────────────────────────────────────────

    def _process_ui_queue(self) -> None:
        try:
            while True:
                cmd, *args = self._ui_queue.get_nowait()
                try:
                    if cmd == "add_message":
                        self._add_message(*args)
                    elif cmd == "add_tool":
                        self._add_tool_indicator(*args)
                    elif cmd == "add_system":
                        self._add_system_message(args[1], conv_id=args[0])
                    elif cmd == "status":
                        self.status_var.set(args[0])
                    elif cmd == "set_thinking":
                        self._set_thinking_state(*args)
                    elif cmd == "sync_status":
                        self._on_sync_status(*args)
                    elif cmd == "remote_pull":
                        self._on_remote_pull(*args)
                except Exception:
                    logger.exception("UI queue command failed: %s", cmd)
        except queue.Empty:
            pass
        self.after(50, self._process_ui_queue)

    def _q(self, *args) -> None:
        self._ui_queue.put(args)

    # ────────────────────────────────────────────────────────────────────
    # Chat Input / Send
    # ────────────────────────────────────────────────────────────────────

    def _on_enter_key(self, event: tk.Event) -> str:
        if event.state & 0x1:
            return  # Allow Shift+Enter for newline
        self._on_send()
        return "break"

    def _on_send(self) -> None:
        if self.is_thinking:
            return
        user_text = self.input_box.get("1.0", "end").strip()
        if not user_text or not self.current_id:
            return
        self.input_box.delete("1.0", "end")
        conv_id = self.current_id
        prior = [m for m in self.store.get(conv_id).get("messages", [])]
        self._add_message(conv_id, "user", user_text)
        threading.Thread(target=self._agent_thread, args=(conv_id, user_text, prior), daemon=True).start()

    def _set_input_enabled(self, enabled: bool) -> None:
        self.send_btn.configure(state="normal" if enabled else "disabled",
                                fg_color=C_ACCENT if enabled else C_BORDER)
        self.input_box.configure(state="normal" if enabled else "disabled")

    def _set_thinking_state(self, thinking: bool, conv_id: str | None = None) -> None:
        self.is_thinking = thinking
        self.thinking_conv = conv_id if thinking else None
        self._set_input_enabled(not thinking)

    # ────────────────────────────────────────────────────────────────────
    # Agent background thread — Gemini API + Function Calling Loop
    # ────────────────────────────────────────────────────────────────────

    def _get_or_create_session(self, conv_id: str, prior: list[dict]) -> genai.chats.Chat:
        if conv_id in self.chat_sessions:
            return self.chat_sessions[conv_id]

        api_key = self.config_data.get("api_key", "").strip()
        if not api_key:
            raise ValueError(
                "ยังไม่ได้ตั้งค่า API Key! กรุณาคลิกปุ่ม '⚙️ ตั้งค่า (Settings)' มุมซ้ายล่างเพื่อระบุ Gemini API Key ครับ"
            )
        model_name = self.config_data.get("model", DEFAULT_MODELS[0]).strip()

        # Resume Gemini context from this conversation's previous messages
        history_contents: list[genai_types.Content] = []
        for msg in prior:
            role = msg.get("role")
            content = (msg.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                history_contents.append(genai_types.Content(
                    role="user" if role == "user" else "model",
                    parts=[genai_types.Part.from_text(text=content)],
                ))

        client = genai.Client(api_key=api_key)
        session = client.chats.create(
            model=model_name,
            history=history_contents if history_contents else None,
            config=genai_types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                tools=[tools.TOOL_DECLARATIONS],
                temperature=0.7,
                max_output_tokens=8192,
            ),
        )
        self.chat_sessions[conv_id] = session
        logger.info("New chat session for %s (model: %s, history turns: %d)", conv_id, model_name, len(history_contents))
        return session

    def _agent_thread(self, conv_id: str, user_message: str, prior: list[dict]) -> None:
        self._q("set_thinking", True, conv_id)
        self._q("status", "🤔 กำลังคิด...")

        try:
            session = self._get_or_create_session(conv_id, prior)
            response = session.send_message(user_message)

            while True:
                fn_calls = []
                text_parts = []
                for candidate in response.candidates or []:
                    if not candidate.content or not candidate.content.parts:
                        continue
                    for part in candidate.content.parts:
                        if part.function_call:
                            fn_calls.append(part.function_call)
                        elif part.text:
                            text_parts.append(part.text)

                if text_parts:
                    combined_text = "\n".join(text_parts).strip()
                    if combined_text:
                        self._q("add_message", conv_id, "assistant", combined_text)

                if not fn_calls:
                    break

                function_responses = []
                for fn_call in fn_calls:
                    fn_name = fn_call.name
                    fn_args = dict(fn_call.args) if fn_call.args else {}

                    self._q("status", f"🔧 กำลังเรียกใช้: {fn_name}...")
                    detail = next(iter(fn_args.values()), "") if fn_args else ""
                    self._q("add_tool", conv_id, fn_name, str(detail))

                    tool_fn = tools.TOOL_FUNCTION_MAP.get(fn_name)
                    if tool_fn:
                        try:
                            result_text = tool_fn(**fn_args)
                        except Exception as exc:
                            result_text = f"Error executing {fn_name}: {exc}"
                    else:
                        result_text = f"Unknown tool: {fn_name}"

                    logger.info("Tool %s result (first 200 chars): %s", fn_name, str(result_text)[:200])
                    function_responses.append(
                        genai_types.Part.from_function_response(name=fn_name, response={"result": result_text})
                    )

                self._q("status", "🤔 กำลังประมวลผลผลลัพธ์...")
                response = session.send_message(function_responses)

            self._q("status", "✅ เสร็จสิ้น — พร้อมรับคำสั่งถัดไป")

        except ValueError as exc:
            self._q("add_system", conv_id, f"⚠️  {exc}")
            self._q("status", "⚠️  กรุณาตั้งค่า API Key ก่อน")
            self.chat_sessions.pop(conv_id, None)

        except Exception as exc:
            logger.exception("Agent thread error")
            error_msg = str(exc)
            self._q("add_system", conv_id, f"❌  เกิดข้อผิดพลาด:\n{error_msg}")
            self._q("status", f"❌  เกิดข้อผิดพลาด — {error_msg[:80]}")
            self.chat_sessions.pop(conv_id, None)

        finally:
            self._q("set_thinking", False)

    # ────────────────────────────────────────────────────────────────────
    # Window close
    # ────────────────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        save_config(self.config_data)
        self.store.save_index()
        self.sync.stop()  # pending writes stay in sync_backlog.json for next start
        logger.info("Application closing")
        self.destroy()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
