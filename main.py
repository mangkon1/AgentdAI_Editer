"""
main.py
-------
Local AI Coding Agent — Desktop GUI powered by Google Gemini + customtkinter.

Features:
  - Modern dark-mode UI with sidebar (settings) + main chat area
  - Multi-turn AI conversation with automatic function calling
  - Agent tools: list_files, read_file, write_file, run_command
  - Persistent config (config.json) — API key, model, workspace
  - Threading so the UI never freezes while the AI is working
  - PyInstaller-compatible path resolution via sys._MEIPASS
"""

from __future__ import annotations

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
# PyInstaller resource-path helper
# ---------------------------------------------------------------------------

def resource_path(relative: str) -> str:
    """Return the absolute path to a bundled resource (works for dev & .exe)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.log")

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
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULT_MODELS = ["gemini-4-argon", "gemini-2.5-pro", "gemini-2.5-flash"]
DEFAULT_WORKSPACE = r"D:\For AI" if os.path.isdir(r"D:\For AI") else os.path.expanduser("~")

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
    except Exception as exc:
        logger.warning("Could not load config: %s", exc)
    return defaults


def save_config(cfg: dict) -> None:
    """Persist configuration to config.json."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2, ensure_ascii=False)
    except Exception as exc:
        logger.error("Could not save config: %s", exc)


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
        self.chat_session: genai.chats.Chat | None = None
        self.is_thinking = False
        self._ui_queue: queue.Queue = queue.Queue()   # thread → UI messages
        self.show_api_key = False

        # ── Window setup ─────────────────────────────────────────────────
        self.title(APP_TITLE)
        self.geometry("1280x800")
        self.minsize(960, 640)

        # Apply workspace to tools
        tools.set_workspace(self.config_data.get("workspace", DEFAULT_WORKSPACE))

        # ── Build UI ─────────────────────────────────────────────────────
        self._build_layout()
        self._load_ui_values()

        # ── Start UI update loop ─────────────────────────────────────────
        self.after(50, self._process_ui_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        logger.info("Application started")

    # ────────────────────────────────────────────────────────────────────
    # Layout construction
    # ────────────────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        """Create the two-column layout: sidebar | chat area."""
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=0)  # sidebar — fixed width
        self.grid_columnconfigure(1, weight=1)  # chat area — expands

        self._build_sidebar()
        self._build_chat_area()

    # ── Sidebar ──────────────────────────────────────────────────────────

    def _build_sidebar(self) -> None:
        sidebar = ctk.CTkFrame(self, fg_color=C_SIDEBAR, corner_radius=0, width=300)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(10, weight=1)  # spacer pushes footer down

        # Header
        hdr = ctk.CTkLabel(
            sidebar,
            text="⚙️  Settings",
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
            text_color=C_TEXT,
        )
        hdr.grid(row=0, column=0, columnspan=2, padx=20, pady=(20, 4), sticky="w")

        ctk.CTkFrame(sidebar, height=1, fg_color=C_BORDER).grid(
            row=1, column=0, columnspan=2, padx=16, pady=(0, 12), sticky="ew"
        )

        # ── API Key ──────────────────────────────────────────────────────
        ctk.CTkLabel(sidebar, text="Gemini API Key", text_color=C_TEXT_DIM,
                     font=ctk.CTkFont(size=12)).grid(
            row=2, column=0, columnspan=2, padx=20, pady=(0, 4), sticky="w"
        )

        key_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        key_frame.grid(row=3, column=0, columnspan=2, padx=16, pady=(0, 12), sticky="ew")
        key_frame.columnconfigure(0, weight=1)

        self.api_key_var = tk.StringVar()
        self.api_key_entry = ctk.CTkEntry(
            key_frame,
            textvariable=self.api_key_var,
            placeholder_text="AIza...",
            show="•",
            fg_color=C_CARD,
            border_color=C_BORDER,
            text_color=C_TEXT,
            font=ctk.CTkFont(family="Consolas", size=12),
        )
        self.api_key_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.eye_btn = ctk.CTkButton(
            key_frame, text="👁", width=36, fg_color=C_CARD,
            hover_color=C_BORDER, text_color=C_TEXT,
            command=self._toggle_api_key_visibility,
        )
        self.eye_btn.grid(row=0, column=1)

        ctk.CTkButton(
            sidebar, text="💾  Save API Key", fg_color=C_ACCENT,
            hover_color=C_ACCENT_HVR, text_color="white",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._save_api_key,
        ).grid(row=4, column=0, columnspan=2, padx=16, pady=(0, 16), sticky="ew")

        # ── Model Selector ───────────────────────────────────────────────
        ctk.CTkLabel(sidebar, text="Model", text_color=C_TEXT_DIM,
                     font=ctk.CTkFont(size=12)).grid(
            row=5, column=0, columnspan=2, padx=20, pady=(0, 4), sticky="w"
        )

        self.model_var = tk.StringVar()
        self.model_combo = ctk.CTkComboBox(
            sidebar,
            variable=self.model_var,
            values=DEFAULT_MODELS,
            fg_color=C_CARD,
            border_color=C_BORDER,
            text_color=C_TEXT,
            dropdown_fg_color=C_CARD,
            dropdown_text_color=C_TEXT,
            button_color=C_ACCENT2,
            button_hover_color=C_ACCENT2_HVR,
            font=ctk.CTkFont(family="Consolas", size=12),
            command=self._on_model_change,
        )
        self.model_combo.grid(row=6, column=0, columnspan=2, padx=16, pady=(0, 16), sticky="ew")

        # ── Workspace Folder ─────────────────────────────────────────────
        ctk.CTkLabel(sidebar, text="Workspace Folder", text_color=C_TEXT_DIM,
                     font=ctk.CTkFont(size=12)).grid(
            row=7, column=0, columnspan=2, padx=20, pady=(0, 4), sticky="w"
        )

        self.workspace_var = tk.StringVar()
        self.workspace_entry = ctk.CTkEntry(
            sidebar,
            textvariable=self.workspace_var,
            fg_color=C_CARD,
            border_color=C_BORDER,
            text_color=C_TEXT,
            font=ctk.CTkFont(family="Consolas", size=11),
        )
        self.workspace_entry.grid(row=8, column=0, columnspan=2, padx=16, pady=(0, 6), sticky="ew")

        ctk.CTkButton(
            sidebar, text="📂  Browse Folder", fg_color=C_ACCENT2,
            hover_color=C_ACCENT2_HVR, text_color="white",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._browse_workspace,
        ).grid(row=9, column=0, columnspan=2, padx=16, pady=(0, 20), sticky="ew")

        # ── Spacer ───────────────────────────────────────────────────────
        ctk.CTkFrame(sidebar, fg_color="transparent").grid(row=10, column=0, sticky="nsew")

        # ── Footer ───────────────────────────────────────────────────────
        ctk.CTkFrame(sidebar, height=1, fg_color=C_BORDER).grid(
            row=11, column=0, columnspan=2, padx=16, pady=(0, 8), sticky="ew"
        )
        ctk.CTkLabel(
            sidebar,
            text="Local AI Coding Agent  v1.0\nPowered by Google Gemini",
            text_color=C_TEXT_DIM,
            font=ctk.CTkFont(size=10),
            justify="center",
        ).grid(row=12, column=0, columnspan=2, padx=16, pady=(0, 12))

    # ── Chat Area ─────────────────────────────────────────────────────────

    def _build_chat_area(self) -> None:
        chat_frame = ctk.CTkFrame(self, fg_color=C_BG, corner_radius=0)
        chat_frame.grid(row=0, column=1, sticky="nsew", padx=(1, 0))
        chat_frame.grid_rowconfigure(1, weight=1)
        chat_frame.grid_columnconfigure(0, weight=1)

        # ── Top bar ──────────────────────────────────────────────────────
        topbar = ctk.CTkFrame(chat_frame, fg_color=C_SIDEBAR, corner_radius=0, height=52)
        topbar.grid(row=0, column=0, sticky="ew")
        topbar.grid_propagate(False)
        topbar.columnconfigure(0, weight=1)

        ctk.CTkLabel(
            topbar,
            text=APP_TITLE,
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            text_color=C_TEXT,
        ).grid(row=0, column=0, padx=20, pady=14, sticky="w")

        ctk.CTkButton(
            topbar, text="🗑  Clear Chat", width=120,
            fg_color=C_DANGER, hover_color=C_DANGER_HVR,
            text_color="white", font=ctk.CTkFont(size=12, weight="bold"),
            command=self._clear_chat,
        ).grid(row=0, column=1, padx=12, pady=10)

        # ── Messages scrollable area ──────────────────────────────────────
        self.messages_frame = ctk.CTkScrollableFrame(
            chat_frame,
            fg_color=C_BG,
            scrollbar_button_color=C_BORDER,
            scrollbar_button_hover_color=C_ACCENT2,
        )
        self.messages_frame.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        self.messages_frame.columnconfigure(0, weight=1)
        self._msg_row = 0

        # ── Status bar ────────────────────────────────────────────────────
        self.status_var = tk.StringVar(value="✅ Ready — type a message and press Enter or click Send")
        status_bar = ctk.CTkFrame(chat_frame, fg_color=C_SIDEBAR, corner_radius=0, height=28)
        status_bar.grid(row=2, column=0, sticky="ew")
        status_bar.grid_propagate(False)
        ctk.CTkLabel(
            status_bar, textvariable=self.status_var,
            text_color=C_TEXT_DIM, font=ctk.CTkFont(size=11),
        ).grid(row=0, column=0, padx=12, pady=4, sticky="w")

        # ── Input area ────────────────────────────────────────────────────
        input_frame = ctk.CTkFrame(chat_frame, fg_color=C_SIDEBAR, corner_radius=0)
        input_frame.grid(row=3, column=0, sticky="ew", padx=0, pady=0)
        input_frame.columnconfigure(0, weight=1)

        self.input_box = ctk.CTkTextbox(
            input_frame,
            height=80,
            fg_color=C_CARD,
            border_color=C_BORDER,
            border_width=1,
            text_color=C_TEXT,
            font=ctk.CTkFont(family="Segoe UI", size=13),
            wrap="word",
        )
        self.input_box.grid(row=0, column=0, padx=(16, 8), pady=12, sticky="ew")
        self.input_box.bind("<Return>", self._on_enter_key)
        self.input_box.bind("<Shift-Return>", lambda e: None)  # allow newlines with Shift+Enter

        self.send_btn = ctk.CTkButton(
            input_frame,
            text="Send\n▶",
            width=80, height=80,
            fg_color=C_ACCENT,
            hover_color=C_ACCENT_HVR,
            text_color="white",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._on_send,
        )
        self.send_btn.grid(row=0, column=1, padx=(0, 16), pady=12)

        # ── Welcome message ───────────────────────────────────────────────
        self._add_system_message(
            "👋  ยินดีต้อนรับ!  ตั้งค่า **API Key** และ **Workspace Folder** ในแถบซ้าย แล้วเริ่มพูดคุยกับ AI Agent ได้เลย\n\n"
            "ตัวอย่างคำสั่ง:\n"
            "• `สร้างเว็บแอป Flask อย่างง่ายใน workspace`\n"
            "• `อ่านไฟล์ main.py แล้วอธิบายให้ฉันฟัง`\n"
            "• `รัน pip install requests แล้วแจ้งผลให้ฉันทราบ`"
        )

    # ────────────────────────────────────────────────────────────────────
    # UI value loading
    # ────────────────────────────────────────────────────────────────────

    def _load_ui_values(self) -> None:
        """Populate UI controls from the loaded config."""
        self.api_key_var.set(self.config_data.get("api_key", ""))
        model = self.config_data.get("model", DEFAULT_MODELS[0])
        self.model_var.set(model)
        if model not in DEFAULT_MODELS:
            self.model_combo.configure(values=DEFAULT_MODELS + [model])
        ws = self.config_data.get("workspace", DEFAULT_WORKSPACE)
        self.workspace_var.set(ws)

    # ────────────────────────────────────────────────────────────────────
    # Message rendering helpers
    # ────────────────────────────────────────────────────────────────────

    def _add_message_bubble(self, role: str, text: str) -> None:
        """Render a chat message bubble in the scrollable area."""
        is_user = role == "user"
        bubble_color = C_USER_BUBBLE if is_user else C_AI_BUBBLE
        label_text  = "You" if is_user else "🤖 Agent"
        label_color = C_ACCENT2 if is_user else C_ACCENT

        outer = ctk.CTkFrame(
            self.messages_frame, fg_color="transparent",
        )
        outer.grid(row=self._msg_row, column=0, sticky="ew", padx=16, pady=(8, 0))
        outer.columnconfigure(0, weight=1)
        self._msg_row += 1

        # Role label
        ctk.CTkLabel(
            outer, text=label_text,
            text_color=label_color,
            font=ctk.CTkFont(size=11, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=4)

        # Bubble
        bubble = ctk.CTkFrame(outer, fg_color=bubble_color, corner_radius=10)
        bubble.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        bubble.columnconfigure(0, weight=1)

        self._render_message_content(bubble, text)

        # Separator
        ctk.CTkFrame(
            self.messages_frame, height=1, fg_color=C_BORDER,
        ).grid(row=self._msg_row, column=0, sticky="ew", padx=24, pady=(8, 0))
        self._msg_row += 1

        self._scroll_to_bottom()

    def _render_message_content(self, parent: ctk.CTkFrame, text: str) -> None:
        """
        Render markdown-ish text with code block detection.
        Code blocks (```...```) are rendered with a monospace font on a dark background.
        """
        # Split on triple-backtick code fences
        parts = re.split(r"(```[\s\S]*?```)", text)
        row = 0
        for part in parts:
            if part.startswith("```") and part.endswith("```"):
                # Extract optional language tag and code body
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
                    font=ctk.CTkFont(family="Consolas", size=12),
                    wrap="none",
                    activate_scrollbars=True,
                    border_width=0,
                    height=min(max(code_body.count("\n") + 2, 3), 30) * 20,
                )
                code_label.grid(row=0, column=0, sticky="ew", padx=8, pady=6)
                code_label.insert("1.0", code_body.strip())
                code_label.configure(state="disabled")
            else:
                if part.strip():
                    txt_label = ctk.CTkLabel(
                        parent,
                        text=part.strip(),
                        text_color=C_TEXT,
                        font=ctk.CTkFont(family="Segoe UI", size=13),
                        wraplength=720,
                        justify="left",
                        anchor="w",
                    )
                    txt_label.grid(row=row, column=0, sticky="ew", padx=12, pady=(6, 4))
            row += 1

    def _add_system_message(self, text: str) -> None:
        """Render a centred system/info message (not a user/AI bubble)."""
        frame = ctk.CTkFrame(self.messages_frame, fg_color=C_CARD, corner_radius=8)
        frame.grid(row=self._msg_row, column=0, sticky="ew", padx=40, pady=12)
        frame.columnconfigure(0, weight=1)
        self._msg_row += 1

        ctk.CTkLabel(
            frame,
            text=text,
            text_color=C_TEXT_DIM,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            wraplength=700,
            justify="left",
        ).grid(row=0, column=0, sticky="ew", padx=16, pady=12)

        self._scroll_to_bottom()

    def _add_tool_indicator(self, tool_name: str, detail: str = "") -> None:
        """Show a small inline tool-call indicator in the chat."""
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
        indicator.grid(row=self._msg_row, column=0, sticky="ew", padx=32, pady=(2, 2))
        self._msg_row += 1

        ctk.CTkLabel(
            indicator,
            text=label_text,
            text_color="#3fb950",
            font=ctk.CTkFont(family="Consolas", size=11),
        ).grid(row=0, column=0, sticky="w", padx=10, pady=4)

        self._scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:
        """Scroll the messages area to the latest message."""
        self.after(80, lambda: self.messages_frame._parent_canvas.yview_moveto(1.0))

    # ────────────────────────────────────────────────────────────────────
    # UI queue — bridge between background threads and the Tk main loop
    # ────────────────────────────────────────────────────────────────────

    def _process_ui_queue(self) -> None:
        """Drain the UI queue and process pending update commands."""
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
        """Thread-safe helper to post a command to the UI queue."""
        self._ui_queue.put(args)

    # ────────────────────────────────────────────────────────────────────
    # Settings handlers
    # ────────────────────────────────────────────────────────────────────

    def _toggle_api_key_visibility(self) -> None:
        self.show_api_key = not self.show_api_key
        self.api_key_entry.configure(show="" if self.show_api_key else "•")

    def _save_api_key(self) -> None:
        key = self.api_key_var.get().strip()
        if not key:
            messagebox.showwarning("No API Key", "Please enter your Gemini API Key.")
            return
        self.config_data["api_key"] = key
        self.config_data["model"] = self.model_var.get().strip() or DEFAULT_MODELS[0]
        self.config_data["workspace"] = self.workspace_var.get().strip() or DEFAULT_WORKSPACE
        save_config(self.config_data)
        tools.set_workspace(self.config_data["workspace"])
        # Reset chat session so new key/model is picked up
        self.chat_session = None
        self.status_var.set("✅ API Key saved. Chat session reset — ready.")
        self._add_system_message("✅ API Key saved successfully. New chat session started.")
        logger.info("API key saved and chat session reset.")

    def _on_model_change(self, choice: str) -> None:
        self.config_data["model"] = choice
        self.chat_session = None
        self.status_var.set(f"Model changed to {choice} — chat session reset.")

    def _browse_workspace(self) -> None:
        current = self.workspace_var.get() or DEFAULT_WORKSPACE
        folder = filedialog.askdirectory(title="Select Workspace Folder", initialdir=current)
        if folder:
            self.workspace_var.set(folder)
            self.config_data["workspace"] = folder
            tools.set_workspace(folder)
            save_config(self.config_data)
            self.status_var.set(f"Workspace set to: {folder}")
            self._add_system_message(f"📁 Workspace folder set to:\n`{folder}`")

    # ────────────────────────────────────────────────────────────────────
    # Chat input / send
    # ────────────────────────────────────────────────────────────────────

    def _on_enter_key(self, event: tk.Event) -> str:
        """Send message on Enter; allow Shift+Enter for newline."""
        if event.state & 0x1:  # Shift is held
            return  # let Tkinter insert a newline
        self._on_send()
        return "break"  # prevent default newline insertion

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
            messagebox.showinfo("Busy", "Please wait for the AI to finish before clearing.")
            return
        # Destroy all message widgets
        for widget in self.messages_frame.winfo_children():
            widget.destroy()
        self._msg_row = 0
        self.chat_session = None
        self._add_system_message("🗑  Chat cleared. New session started.")
        self.status_var.set("✅ Chat cleared — ready.")

    # ────────────────────────────────────────────────────────────────────
    # UI state helpers
    # ────────────────────────────────────────────────────────────────────

    def _set_thinking_state(self, thinking: bool) -> None:
        self.is_thinking = thinking
        self.send_btn.configure(
            state="disabled" if thinking else "normal",
            fg_color=C_BORDER if thinking else C_ACCENT,
        )
        self.input_box.configure(state="disabled" if thinking else "normal")

    # ────────────────────────────────────────────────────────────────────
    # Agent background thread — Gemini API + function calling loop
    # ────────────────────────────────────────────────────────────────────

    def _get_or_create_session(self) -> genai.chats.Chat:
        """Return the existing chat session or create a new one."""
        if self.chat_session is not None:
            return self.chat_session

        api_key = self.config_data.get("api_key", "").strip()
        if not api_key:
            raise ValueError(
                "API Key not configured. Please enter your Gemini API Key in the sidebar and click 'Save API Key'."
            )

        model_name = self.config_data.get("model", DEFAULT_MODELS[0]).strip()

        client = genai.Client(api_key=api_key)
        self.chat_session = client.chats.create(
            model=model_name,
            config=genai_types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                tools=[tools.TOOL_DECLARATIONS],
                temperature=0.7,
                max_output_tokens=8192,
            ),
        )
        logger.info("New chat session created for model: %s", model_name)
        return self.chat_session

    def _agent_thread(self, user_message: str) -> None:
        """
        Background thread: send user message → handle function calls → display reply.
        This loop runs until the model returns a final text response with no more tool calls.
        """
        self._q("set_thinking", True)
        self._q("status", "🤔 กำลังคิด...")

        try:
            session = self._get_or_create_session()
            response = session.send_message(user_message)

            # ── Agentic loop — handle automatic function calling ──────────
            while True:
                # Check if the response contains function call parts
                fn_calls = []
                text_parts = []

                for candidate in response.candidates:
                    for part in candidate.content.parts:
                        if part.function_call:
                            fn_calls.append(part.function_call)
                        elif part.text:
                            text_parts.append(part.text)

                # Display any intermediate text from the model
                if text_parts:
                    combined_text = "\n".join(text_parts).strip()
                    if combined_text:
                        self._q("add_message", "assistant", combined_text)

                # No more tool calls — we are done
                if not fn_calls:
                    break

                # Execute all tool calls and collect results
                function_responses = []
                for fn_call in fn_calls:
                    fn_name = fn_call.name
                    fn_args = dict(fn_call.args) if fn_call.args else {}

                    # Update status and show tool indicator
                    self._q("status", f"🔧 กำลังเรียกใช้: {fn_name}...")
                    detail = next(iter(fn_args.values()), "") if fn_args else ""
                    self._q("add_tool", fn_name, str(detail))

                    # Dispatch to the correct tool function
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

                # Send tool results back to the model
                self._q("status", "🤔 กำลังประมวลผลผลลัพธ์...")
                response = session.send_message(function_responses)

            self._q("status", "✅ เสร็จสิ้น — พร้อมรับคำสั่งถัดไป")

        except ValueError as exc:
            # Configuration errors (no API key, etc.)
            self._q("add_system", f"⚠️  {exc}")
            self._q("status", "⚠️  กรุณาตั้งค่า API Key ก่อน")
            self.chat_session = None  # force session reset on next send

        except Exception as exc:
            logger.exception("Agent thread error")
            error_msg = str(exc)
            self._q("add_system", f"❌  เกิดข้อผิดพลาด:\n{error_msg}")
            self._q("status", f"❌  เกิดข้อผิดพลาด — {error_msg[:80]}")
            self.chat_session = None  # reset session after error

        finally:
            self._q("set_thinking", False)

    # ────────────────────────────────────────────────────────────────────
    # Window close
    # ────────────────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        """Save config on close and exit cleanly."""
        save_config(self.config_data)
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
