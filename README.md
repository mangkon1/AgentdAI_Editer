# 🤖 Local AI Coding Agent

A modern Windows desktop application powered by **Google Gemini** (`google-genai` SDK) that acts as an autonomous local AI coding agent — capable of reading, writing, and executing code directly inside your workspace.

![Dark Mode UI](https://img.shields.io/badge/UI-Dark%20Mode-0d1117?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python)
![Gemini](https://img.shields.io/badge/Google-Gemini-4285F4?style=for-the-badge&logo=google)
![Windows](https://img.shields.io/badge/Windows-EXE-0078D4?style=for-the-badge&logo=windows)
![GitHub](https://img.shields.io/badge/GitHub-Repository-181717?style=for-the-badge&logo=github)

---

## ✨ Features

| Feature | Description |
|---|---|
| 🎨 **Full-Width Modern UI** | `customtkinter` dark-mode interface with maximized code viewing area |
| ⚙️ **Settings Modal Popup** | Dedicated popup dialog (`CTkToplevel`) for API Key, Model & Workspace |
| 📜 **Persistent Chat History** | Conversations auto-saved to `chat_history.json` — resume work across restarts |
| 📄 **Export to Markdown** | One-click export to `CHAT_HISTORY.md` to commit and track progress on GitHub |
| ⌨️ **Universal Keyboard Shortcuts** | Hardware keycode-based `Ctrl+C`, `Ctrl+V`, `Ctrl+A`, `Ctrl+X`, `Ctrl+Z` that work in both Thai and English |
| 🖱️ **Right-Click Context Menu** | Cut, Copy, Paste, and Select All context menu on all fields |
| 🤖 **Gemini AI Agent** | Multi-turn conversation with automatic function calling (tools) |
| 📂 **Workspace File Tools** | Agent can autonomously list, read, and write files in your workspace |
| ⚡ **Shell Execution** | Agent can run PowerShell/shell commands and verify output |
| 💾 **Reliable Config** | Persistent `config.json` next to `.exe` (works with PyInstaller bundling) |
| 🧵 **Non-blocking UI** | All API calls run on background threads — UI never freezes |
| 🇹🇭 **Thai & English Support** | Crystal-clear typography using Windows `Leelawadee UI` font |

---

## 🚀 Quick Start

### Option A — Run from Source

```bash
# 1. Clone the repo
git clone https://github.com/mangkon1/AgentdAI_Editer.git
cd AgentdAI_Editer

# 2. Create a virtual environment
python -m venv venv
venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the app
python main.py
```

### Option B — Run Standalone EXE

1. Go to the project folder `dist/` or download from [GitHub Releases](../../releases)
2. Double-click **`GeminiAgentApp.exe`**
3. Click **⚙️ ตั้งค่า (Settings)** at the top right
4. Enter your Gemini API Key and select your Workspace folder
5. Click **💾 บันทึกการตั้งค่า (Save Settings)** and start coding!

### Option C — Build EXE Locally

```batch
build_exe.bat
```
Output: `dist\GeminiAgentApp.exe`

---

## ⚙️ Configuration & Persistence

The application maintains two persistent JSON files in the same folder as the `.exe`:

1. **`config.json`**:
   ```json
   {
     "api_key": "YOUR_GEMINI_API_KEY",
     "model": "gemini-4-argon",
     "workspace": "D:\\For AI"
   }
   ```
   *(Excluded from Git via `.gitignore` to protect your secret key)*

2. **`chat_history.json`**:
   Automatically records your multi-turn conversation so that closing and reopening the app restores your work session seamlessly.

Get a free Gemini API key at [Google AI Studio](https://aistudio.google.com/app/apikey).

---

## 📄 Chat History & Markdown Export for GitHub

You can export the entire conversation history into GitHub Flavored Markdown at any time:
1. Click the **📄 ส่งออก Markdown** button on the top navigation bar.
2. Select your workspace directory.
3. The exported file (`CHAT_HISTORY.md`) contains all prompts, code blocks, tool executions, and responses formatted cleanly.
4. You can commit this file directly to your GitHub repository to document project evolution!

---

## 🛠️ Agent Tools

The AI agent can autonomously call these tools:

| Tool | Description |
|---|---|
| `list_files(directory)` | Explore workspace directory structure |
| `read_file(filepath)` | Read source code or text files |
| `write_file(filepath, content)` | Create or overwrite files directly |
| `run_command(command)` | Execute shell/PowerShell commands in the workspace |

---

## 🏗️ Project Structure

```
AIAgentdEditer/
├── main.py                          # Main GUI application & Settings popup
├── agent_tools.py                   # Gemini tool declarations and execution
├── requirements.txt                 # Dependencies (customtkinter, google-genai, pyinstaller)
├── build_exe.bat                    # Local PyInstaller build script
├── .gitignore                       # Ignores secrets & build artifacts
├── README.md                        # Documentation & guides
└── .github/
    └── workflows/
        └── build_exe.yml            # Automated GitHub Actions CI/CD
```

---

## 📬 Contact & Author

- **GitHub Repository:** [https://github.com/mangkon1/AgentdAI_Editer](https://github.com/mangkon1/AgentdAI_Editer)
- **Maintainer:** [mangkon1](https://github.com/mangkon1)
- **License:** MIT License
