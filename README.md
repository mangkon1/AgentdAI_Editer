# 🤖 Local AI Coding Agent

A modern Windows desktop application powered by **Google Gemini** that acts as a local AI coding agent — capable of reading, writing, and executing code directly in your workspace.

![Dark Mode UI](https://img.shields.io/badge/UI-Dark%20Mode-0d1117?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python)
![Gemini](https://img.shields.io/badge/Google-Gemini-4285F4?style=for-the-badge&logo=google)
![Windows](https://img.shields.io/badge/Windows-EXE-0078D4?style=for-the-badge&logo=windows)

---

## ✨ Features

| Feature | Description |
|---|---|
| 🎨 **Modern Dark UI** | `customtkinter`-powered dark-mode GUI with sidebar + chat |
| 🤖 **Gemini AI Agent** | Multi-turn conversation with automatic function calling |
| 📂 **File System Access** | Agent can list, read, and write files in your workspace |
| ⚡ **Shell Execution** | Agent can run PowerShell/shell commands and see output |
| 💾 **Persistent Config** | API key, model, and workspace saved in `config.json` |
| 🧵 **Non-blocking UI** | All API calls run on background threads — UI never freezes |
| 🇹🇭 **Thai Language** | Full Thai and English language support |

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

### Option B — Download Pre-built EXE

1. Go to [**Actions**](../../actions) → latest successful build → **Artifacts**
2. Download `GeminiAgentApp-Windows.zip` and extract
3. Run `GeminiAgentApp.exe`
4. Enter your Gemini API Key in the sidebar

### Option C — Build EXE Locally

```batch
build_exe.bat
```
Output: `dist\GeminiAgentApp.exe`

---

## ⚙️ Configuration

On first run the app creates `config.json` next to the executable:

```json
{
  "api_key": "YOUR_GEMINI_API_KEY",
  "model": "gemini-2.5-flash",
  "workspace": "D:\\For AI"
}
```

> **Note:** `config.json` is listed in `.gitignore` — your API key is never committed.

Get a free API key at [Google AI Studio](https://aistudio.google.com/app/apikey).

---

## 🛠️ Agent Tools

The AI can autonomously call these tools during a conversation:

| Tool | Description |
|---|---|
| `list_files(directory)` | Explore workspace directory structure |
| `read_file(filepath)` | Read source code or any text file |
| `write_file(filepath, content)` | Create or overwrite files |
| `run_command(command)` | Run shell/PowerShell commands |

---

## 🏗️ Project Structure

```
AIAgentdEditer/
├── main.py                          # Main GUI application
├── agent_tools.py                   # Gemini tool implementations
├── requirements.txt                 # Python dependencies
├── build_exe.bat                    # Local build script
├── .gitignore                       # Excludes secrets & build artifacts
└── .github/
    └── workflows/
        └── build_exe.yml            # GitHub Actions CI/CD
```

---

## 📦 Dependencies

- [`customtkinter`](https://github.com/TomSchimansky/CustomTkinter) — Modern Tk-based GUI
- [`google-genai`](https://pypi.org/project/google-genai/) — Official Google Generative AI SDK
- [`pyinstaller`](https://pyinstaller.org/) — Python → standalone EXE packager

---

## 📄 License

MIT License — feel free to use, modify, and distribute.
