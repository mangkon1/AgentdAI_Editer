"""
main.py
-------
Local AI Coding Agent — Desktop GUI powered by Google Gemini + customtkinter.

Features:
  - Full-width modern dark-mode chat interface
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

# Colour palette
C_BG          = "#0d1117"
C_SIDEBAR     = "#161b22"
C_CARD        = "#1c2128"
C_ACCENT      = "#238636"
C_ACCENT_HVR  = "#2ea043"
C_ACCENT2     = "#1f6feb"
C_ACCENT2_HVR = "#388bfd"
C_DANGER      = "#da3633"
C_DANGER_HVR  = "#f85149"
C_TEXT        = "#e6edf3"
C_TEXT_DIM    = "#8b949e"
C_BORDER      = "#30363d"
C_USER_BUBBLE = "#1f3a5f"
C_AI_BUBBLE   = "#1c2128"
C_CODE_BG     = "#0d1117"

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


def export_chat_to_markdown(history: list[dict], target_path: str) -> None:
    """Export the chat history into a beautifully formatted Markdown file."""
    lines = [
        "# 🤖 Local AI Coding Agent — Chat History\n",
        f"*Exported on: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n",
        "---\n",
    ]
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

    with open(target_path, "w", encoding="utf-8") as fh:
        fh.writelines(lines)
    logger.info("Exported chat history to: %s", target_path)


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
        self.geometry("540x520")
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
        h = 520
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
        ws_box.pack(fill="x", padx=20, pady=(0, 20))
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

        # Persist config to config.json
        save_config(self.parent_app.config_data)

        # Apply workspace to tool runner
        tools.set_workspace(workspace)

        # Reset chat session with updated credentials
        self.parent_app.chat_session = None

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
    """Main application window — dark-mode AI Coding Agent."""

    def __init__(self) -> None:
        super().__init__()

        # ── Appearance ───────────────────────────────────────────────────
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        self.configure(fg_color=C_BG)

        # ── State ────────────────────────────────────────────────────────
        self.config_data = load_config()
        self.chat_history: list[dict] = load_chat_history()
        self.chat_session: genai.chats.Chat | None = None
        self.is_thinking = False
        self._ui_queue: queue.Queue = queue.Queue()   # thread → UI messages
        self._msg_row = 0

        # ── Window setup ─────────────────────────────────────────────────
        self.title(APP_TITLE)
        self.geometry("1280x820")
        self.minsize(980, 650)

        # Apply workspace to tools
        tools.set_workspace(self.config_data.get("workspace", DEFAULT_WORKSPACE))

        # ── Build UI ─────────────────────────────────────────────────────
        self._build_layout()
        self._setup_universal_shortcuts()

        # ── Restore previous chat history or show welcome ────────────────
        self._restore_chat_history()

        # ── Start UI update loop ─────────────────────────────────────────
        self.after(50, self._process_ui_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        logger.info("Application started successfully")

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
    # Layout construction — Full-Width Chat with Top Navigation
    # ────────────────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        """Create full-width chat interface with modern top control bar."""
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_topbar()
        self._build_chat_area()

    def _build_topbar(self) -> None:
        """Header bar containing branding, status chips, and action buttons."""
        topbar = ctk.CTkFrame(self, fg_color=C_SIDEBAR, corner_radius=0, height=56)
        topbar.grid(row=0, column=0, sticky="ew")
        topbar.grid_propagate(False)
        topbar.columnconfigure(1, weight=1)

        # ── Left: App Title ───────────────────────────────────────────────
        title_box = ctk.CTkFrame(topbar, fg_color="transparent")
        title_box.grid(row=0, column=0, padx=(20, 16), pady=10, sticky="w")

        ctk.CTkLabel(
            title_box,
            text=APP_TITLE,
            font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
            text_color=C_TEXT,
        ).pack(side="left")

        # ── Middle: Info Badges ───────────────────────────────────────────
        self.badges_frame = ctk.CTkFrame(topbar, fg_color="transparent")
        self.badges_frame.grid(row=0, column=1, padx=8, pady=10, sticky="w")

        self.model_badge = ctk.CTkLabel(
            self.badges_frame,
            text="",
            fg_color=C_CARD,
            corner_radius=6,
            font=ctk.CTkFont(family=FONT_CODE, size=11),
            text_color=C_TEXT,
            padx=10,
            pady=4,
        )
        self.model_badge.pack(side="left", padx=(0, 8))

        self.ws_badge = ctk.CTkLabel(
            self.badges_frame,
            text="",
            fg_color=C_CARD,
            corner_radius=6,
            font=ctk.CTkFont(family=FONT_CODE, size=11),
            text_color=C_TEXT_DIM,
            padx=10,
            pady=4,
        )
        self.ws_badge.pack(side="left")

        self._update_topbar_badges()

        # ── Right: Action Buttons ─────────────────────────────────────────
        actions_frame = ctk.CTkFrame(topbar, fg_color="transparent")
        actions_frame.grid(row=0, column=2, padx=(0, 20), pady=10, sticky="e")

        # Export Markdown
        export_btn = ctk.CTkButton(
            actions_frame,
            text="📄 ส่งออก Markdown",
            width=130,
            height=34,
            fg_color=C_CARD,
            hover_color=C_BORDER,
            text_color=C_TEXT,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
            command=self._export_markdown,
        )
        export_btn.pack(side="left", padx=(0, 8))

        # Clear Chat
        clear_btn = ctk.CTkButton(
            actions_frame,
            text="🗑 ล้างแชท",
            width=90,
            height=34,
            fg_color=C_DANGER,
            hover_color=C_DANGER_HVR,
            text_color="white",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
            command=self._clear_chat,
        )
        clear_btn.pack(side="left", padx=(0, 8))

        # Settings Popup Button
        settings_btn = ctk.CTkButton(
            actions_frame,
            text="⚙️ ตั้งค่า (Settings)",
            width=135,
            height=34,
            fg_color=C_ACCENT2,
            hover_color=C_ACCENT2_HVR,
            text_color="white",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            command=self._open_settings_popup,
        )
        settings_btn.pack(side="left")

    def _update_topbar_badges(self) -> None:
        model = self.config_data.get("model", DEFAULT_MODELS[0])
        self.model_badge.configure(text=f"🤖 {model}")

        ws = self.config_data.get("workspace", DEFAULT_WORKSPACE)
        short_ws = os.path.basename(ws) or ws
        self.ws_badge.configure(text=f"📁 {short_ws}")

    def _open_settings_popup(self) -> None:
        """Open modal settings dialog."""
        SettingsDialog(self)

    # ── Main Chat Area ───────────────────────────────────────────────────

    def _build_chat_area(self) -> None:
        chat_frame = ctk.CTkFrame(self, fg_color=C_BG, corner_radius=0)
        chat_frame.grid(row=1, column=0, sticky="nsew")
        chat_frame.grid_rowconfigure(0, weight=1)
        chat_frame.grid_columnconfigure(0, weight=1)

        # ── Messages scrollable area ──────────────────────────────────────
        self.messages_frame = ctk.CTkScrollableFrame(
            chat_frame,
            fg_color=C_BG,
            scrollbar_button_color=C_BORDER,
            scrollbar_button_hover_color=C_ACCENT2,
        )
        self.messages_frame.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        self.messages_frame.columnconfigure(0, weight=1)

        # ── Status bar ────────────────────────────────────────────────────
        self.status_var = tk.StringVar(value="✅ Ready — พิมพ์ข้อความแล้วกด Enter หรือ Send ได้เลย")
        status_bar = ctk.CTkFrame(chat_frame, fg_color=C_SIDEBAR, corner_radius=0, height=28)
        status_bar.grid(row=1, column=0, sticky="ew")
        status_bar.grid_propagate(False)
        ctk.CTkLabel(
            status_bar,
            textvariable=self.status_var,
            text_color=C_TEXT_DIM,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
        ).grid(row=0, column=0, padx=16, pady=4, sticky="w")

        # ── Input area ────────────────────────────────────────────────────
        input_frame = ctk.CTkFrame(chat_frame, fg_color=C_SIDEBAR, corner_radius=0)
        input_frame.grid(row=2, column=0, sticky="ew")
        input_frame.columnconfigure(0, weight=1)

        self.input_box = ctk.CTkTextbox(
            input_frame,
            height=85,
            fg_color=C_CARD,
            border_color=C_BORDER,
            border_width=1,
            text_color=C_TEXT,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
            wrap="word",
        )
        self.input_box.grid(row=0, column=0, padx=(20, 10), pady=12, sticky="ew")
        self.input_box.bind("<Return>", self._on_enter_key)
        self.input_box.bind("<Shift-Return>", lambda e: None)
        self._attach_context_menu(self.input_box)

        self.send_btn = ctk.CTkButton(
            input_frame,
            text="Send\n▶",
            width=85,
            height=85,
            fg_color=C_ACCENT,
            hover_color=C_ACCENT_HVR,
            text_color="white",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            command=self._on_send,
        )
        self.send_btn.grid(row=0, column=1, padx=(0, 20), pady=12)

    # ────────────────────────────────────────────────────────────────────
    # History restoration
    # ────────────────────────────────────────────────────────────────────

    def _restore_chat_history(self) -> None:
        """Render previous chat session messages or show welcome guide."""
        if self.chat_history:
            self._add_system_message(
                f"📜 **โหลดประวัติการสนทนาเดิม ({len(self.chat_history)} ข้อความ)**\n"
                f"คุณสามารถสนทนาและสั่งงานต่อจากเดิมได้ทันที หรือกด '🗑 ล้างแชท' หากต้องการเริ่มใหม่"
            )
            for msg in self.chat_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role in ("user", "assistant"):
                    self._render_bubble_widget(role, content)
                elif role == "system":
                    self._render_system_widget(content)
            self._scroll_to_bottom()
        else:
            self._show_welcome_message()

    def _show_welcome_message(self) -> None:
        self._add_system_message(
            "👋  ยินดีต้อนรับสู่ **Local AI Coding Agent**!\n\n"
            "• คลิก **⚙️ ตั้งค่า (Settings)** ด้านขวาบน เพื่อใส่ Gemini API Key และเลือก Workspace\n"
            "• ประวัติการแชทจะถูกบันทึกอัตโนมัติ เปิดโปรแกรมรอบหน้าทำงานต่อได้ทันที\n"
            "• คลิก **📄 ส่งออก Markdown** เพื่อเซฟบทสนทนาเป็นไฟล์ `.md` สำหรับลง GitHub ได้เลย\n\n"
            "ตัวอย่างคำสั่งที่สั่งได้:\n"
            "• `สร้างเว็บแอป Flask อย่างง่ายใน workspace`\n"
            "• `อ่านไฟล์ main.py แล้วอธิบายให้ฉันฟัง`\n"
            "• `รัน pip install requests แล้วแจ้งผลให้ทราบ`"
        )

    # ────────────────────────────────────────────────────────────────────
    # Message rendering helpers
    # ────────────────────────────────────────────────────────────────────

    def _add_message_bubble(self, role: str, text: str) -> None:
        """Add message to UI and save to persistent history."""
        now_str = datetime.datetime.now().strftime("%H:%M")
        self.chat_history.append({
            "role": role,
            "content": text,
            "time": now_str,
        })
        save_chat_history(self.chat_history)
        self._render_bubble_widget(role, text)
        self._scroll_to_bottom()

    def _render_bubble_widget(self, role: str, text: str) -> None:
        is_user = role == "user"
        bubble_color = C_USER_BUBBLE if is_user else C_AI_BUBBLE
        label_text  = "👤 You" if is_user else "🤖 Agent"
        label_color = C_ACCENT2 if is_user else C_ACCENT

        outer = ctk.CTkFrame(self.messages_frame, fg_color="transparent")
        outer.grid(row=self._msg_row, column=0, sticky="ew", padx=20, pady=(8, 0))
        outer.columnconfigure(0, weight=1)
        self._msg_row += 1

        ctk.CTkLabel(
            outer,
            text=label_text,
            text_color=label_color,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=4)

        bubble = ctk.CTkFrame(outer, fg_color=bubble_color, corner_radius=10)
        bubble.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        bubble.columnconfigure(0, weight=1)

        self._render_message_content(bubble, text)

        # Separator
        ctk.CTkFrame(
            self.messages_frame, height=1, fg_color=C_BORDER,
        ).grid(row=self._msg_row, column=0, sticky="ew", padx=28, pady=(8, 0))
        self._msg_row += 1

    def _render_message_content(self, parent: ctk.CTkFrame, text: str) -> None:
        """Render text with code block detection."""
        parts = re.split(r"(```[\s\S]*?```)", text)
        row = 0
        for part in parts:
            if part.startswith("```") and part.endswith("```"):
                inner = part[3:-3]
                newline_idx = inner.find("\n")
                if newline_idx != -1:
                    code_body = inner[newline_idx + 1:]
                else:
                    code_body = inner

                code_frame = ctk.CTkFrame(parent, fg_color=C_CODE_BG, corner_radius=6)
                code_frame.grid(row=row, column=0, sticky="ew", padx=10, pady=(4, 4))
                code_frame.columnconfigure(0, weight=1)

                code_label = ctk.CTkTextbox(
                    code_frame,
                    fg_color=C_CODE_BG,
                    text_color="#79c0ff",
                    font=ctk.CTkFont(family=FONT_CODE, size=12),
                    wrap="none",
                    activate_scrollbars=True,
                    border_width=0,
                    height=min(max(code_body.count("\n") + 2, 3), 30) * 20,
                )
                code_label.grid(row=0, column=0, sticky="ew", padx=8, pady=6)
                code_label.insert("1.0", code_body.strip())
                code_label.configure(state="disabled")
                self._attach_context_menu(code_label)
            else:
                if part.strip():
                    txt_label = ctk.CTkLabel(
                        parent,
                        text=part.strip(),
                        text_color=C_TEXT,
                        font=ctk.CTkFont(family=FONT_FAMILY, size=13),
                        wraplength=880,
                        justify="left",
                        anchor="w",
                    )
                    txt_label.grid(row=row, column=0, sticky="ew", padx=14, pady=(6, 4))
            row += 1

    def _add_system_message(self, text: str) -> None:
        """Add system note and save to history."""
        self.chat_history.append({
            "role": "system",
            "content": text,
            "time": datetime.datetime.now().strftime("%H:%M"),
        })
        save_chat_history(self.chat_history)
        self._render_system_widget(text)
        self._scroll_to_bottom()

    def _render_system_widget(self, text: str) -> None:
        frame = ctk.CTkFrame(self.messages_frame, fg_color=C_CARD, corner_radius=8)
        frame.grid(row=self._msg_row, column=0, sticky="ew", padx=40, pady=10)
        frame.columnconfigure(0, weight=1)
        self._msg_row += 1

        ctk.CTkLabel(
            frame,
            text=text,
            text_color=C_TEXT_DIM,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            wraplength=840,
            justify="left",
        ).grid(row=0, column=0, sticky="ew", padx=16, pady=10)

    def _add_tool_indicator(self, tool_name: str, detail: str = "") -> None:
        icons = {
            "list_files": "📂",
            "read_file": "📄",
            "write_file": "✍️",
            "run_command": "⚡",
        }
        icon = icons.get(tool_name, "🔧")
        label_text = f"{icon} Tool: {tool_name}"
        if detail:
            label_text += f"  →  {detail[:80]}"

        indicator = ctk.CTkFrame(self.messages_frame, fg_color=C_CARD, corner_radius=6)
        indicator.grid(row=self._msg_row, column=0, sticky="ew", padx=36, pady=(2, 2))
        self._msg_row += 1

        ctk.CTkLabel(
            indicator,
            text=label_text,
            text_color="#3fb950",
            font=ctk.CTkFont(family=FONT_CODE, size=11),
        ).grid(row=0, column=0, sticky="w", padx=10, pady=4)

        self._scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:
        self.after(80, lambda: self.messages_frame._parent_canvas.yview_moveto(1.0))

    # ────────────────────────────────────────────────────────────────────
    # Markdown Export
    # ────────────────────────────────────────────────────────────────────

    def _export_markdown(self) -> None:
        """Export current chat history to a Markdown file."""
        if not self.chat_history:
            messagebox.showinfo("ไม่มีข้อความ", "ยังไม่มีประวัติการสนทนาให้ส่งออกครับ")
            return

        workspace = self.config_data.get("workspace", DEFAULT_WORKSPACE)
        default_name = f"CHAT_HISTORY_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        default_path = os.path.join(workspace, default_name)

        target_file = filedialog.asksaveasfilename(
            title="บันทึกประวัติการแชทเป็น Markdown",
            initialdir=workspace,
            initialfile=default_name,
            defaultextension=".md",
            filetypes=[("Markdown files", "*.md"), ("All files", "*.*")],
        )

        if target_file:
            try:
                export_chat_to_markdown(self.chat_history, target_file)
                self.status_var.set(f"📄 ส่งออก Markdown สำเร็จ: {os.path.basename(target_file)}")
                messagebox.showinfo(
                    "ส่งออกสำเร็จ",
                    f"✅ ส่งออกประวัติการแชทเรียบร้อยแล้ว!\n\nไฟล์: {target_file}\n"
                    "คุณสามารถนำไฟล์นี้ไปใส่ใน GitHub Repo เพื่อบันทึกงานได้ทันทีครับ"
                )
            except Exception as exc:
                messagebox.showerror("เกิดข้อผิดพลาด", f"ไม่สามารถบันทึกไฟล์ได้: {exc}")

    # ────────────────────────────────────────────────────────────────────
    # UI queue
    # ────────────────────────────────────────────────────────────────────

    def _process_ui_queue(self) -> None:
        try:
            while True:
                cmd, *args = self._ui_queue.get_nowait()
                if cmd == "add_message":
                    self._add_message_bubble(*args)
                elif cmd == "add_tool":
                    self._add_tool_indicator(*args)
                elif cmd == "add_system":
                    self._add_system_message(*args)
                elif cmd == "status":
                    self.status_var.set(args[0])
                elif cmd == "set_thinking":
                    self._set_thinking_state(args[0])
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
        if not user_text:
            return
        self.input_box.delete("1.0", "end")
        self._add_message_bubble("user", user_text)
        threading.Thread(
            target=self._agent_thread, args=(user_text,), daemon=True
        ).start()

    def _clear_chat(self) -> None:
        if self.is_thinking:
            messagebox.showinfo("กรุณารอ", "กรุณารอ AI ทำงานเสร็จก่อนล้างแชทครับ")
            return
        if messagebox.askyesno("ยืนยัน", "ต้องการล้างประวัติการแชททั้งหมดใช่หรือไม่?"):
            for widget in self.messages_frame.winfo_children():
                widget.destroy()
            self._msg_row = 0
            self.chat_history.clear()
            save_chat_history(self.chat_history)
            self.chat_session = None
            self._add_system_message("🗑  ล้างบทสนทนาเรียบร้อย เริ่มต้นเซสชันใหม่")
            self.status_var.set("✅ ล้างบทสนทนาเรียบร้อย — พร้อมรับคำสั่ง")

    def _set_thinking_state(self, thinking: bool) -> None:
        self.is_thinking = thinking
        self.send_btn.configure(
            state="disabled" if thinking else "normal",
            fg_color=C_BORDER if thinking else C_ACCENT,
        )
        self.input_box.configure(state="disabled" if thinking else "normal")

    # ────────────────────────────────────────────────────────────────────
    # Agent background thread — Gemini API + Function Calling Loop
    # ────────────────────────────────────────────────────────────────────

    def _get_or_create_session(self) -> genai.chats.Chat:
        if self.chat_session is not None:
            return self.chat_session

        api_key = self.config_data.get("api_key", "").strip()
        if not api_key:
            raise ValueError(
                "ยังไม่ได้ตั้งค่า API Key! กรุณาคลิกปุ่ม '⚙️ ตั้งค่า (Settings)' ด้านขวาบนเพื่อระบุ Gemini API Key ครับ"
            )

        model_name = self.config_data.get("model", DEFAULT_MODELS[0]).strip()

        # Build initial history contents from past messages so the agent has continuous memory
        history_contents: list[genai_types.Content] = []
        for msg in self.chat_history:
            role = msg.get("role")
            content = msg.get("content", "").strip()
            if role in ("user", "assistant") and content:
                gemini_role = "user" if role == "user" else "model"
                history_contents.append(
                    genai_types.Content(
                        role=gemini_role,
                        parts=[genai_types.Part.from_text(text=content)],
                    )
                )

        client = genai.Client(api_key=api_key)
        self.chat_session = client.chats.create(
            model=model_name,
            history=history_contents if history_contents else None,
            config=genai_types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                tools=[tools.TOOL_DECLARATIONS],
                temperature=0.7,
                max_output_tokens=8192,
            ),
        )
        logger.info("New chat session created (model: %s, history turns: %d)", model_name, len(history_contents))
        return self.chat_session

    def _agent_thread(self, user_message: str) -> None:
        self._q("set_thinking", True)
        self._q("status", "🤔 กำลังคิด...")

        try:
            session = self._get_or_create_session()
            response = session.send_message(user_message)

            while True:
                fn_calls = []
                text_parts = []

                for candidate in response.candidates:
                    for part in candidate.content.parts:
                        if part.function_call:
                            fn_calls.append(part.function_call)
                        elif part.text:
                            text_parts.append(part.text)

                if text_parts:
                    combined_text = "\n".join(text_parts).strip()
                    if combined_text:
                        self._q("add_message", "assistant", combined_text)

                if not fn_calls:
                    break

                function_responses = []
                for fn_call in fn_calls:
                    fn_name = fn_call.name
                    fn_args = dict(fn_call.args) if fn_call.args else {}

                    self._q("status", f"🔧 กำลังเรียกใช้: {fn_name}...")
                    detail = next(iter(fn_args.values()), "") if fn_args else ""
                    self._q("add_tool", fn_name, str(detail))

                    tool_fn = tools.TOOL_FUNCTION_MAP.get(fn_name)
                    if tool_fn:
                        try:
                            result_text = tool_fn(**fn_args)
                        except Exception as exc:
                            result_text = f"Error executing {fn_name}: {exc}"
                    else:
                        result_text = f"Unknown tool: {fn_name}"

                    logger.info("Tool %s result (first 200 chars): %s", fn_name, result_text[:200])

                    function_responses.append(
                        genai_types.Part.from_function_response(
                            name=fn_name,
                            response={"result": result_text},
                        )
                    )

                self._q("status", "🤔 กำลังประมวลผลผลลัพธ์...")
                response = session.send_message(function_responses)

            self._q("status", "✅ เสร็จสิ้น — พร้อมรับคำสั่งถัดไป")

        except ValueError as exc:
            self._q("add_system", f"⚠️  {exc}")
            self._q("status", "⚠️  กรุณาตั้งค่า API Key ก่อน")
            self.chat_session = None

        except Exception as exc:
            logger.exception("Agent thread error")
            error_msg = str(exc)
            self._q("add_system", f"❌  เกิดข้อผิดพลาด:\n{error_msg}")
            self._q("status", f"❌  เกิดข้อผิดพลาด — {error_msg[:80]}")
            self.chat_session = None

        finally:
            self._q("set_thinking", False)

    # ────────────────────────────────────────────────────────────────────
    # Window close
    # ────────────────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        save_config(self.config_data)
        save_chat_history(self.chat_history)
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
