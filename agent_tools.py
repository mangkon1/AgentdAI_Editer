"""
agent_tools.py
--------------
Tool functions that the Gemini AI Agent can call automatically via Function Calling.
All file operations are sandboxed to the configured workspace directory.
"""

import os
import subprocess
import logging

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Active workspace (set by main.py at runtime)
# ---------------------------------------------------------------------------
_workspace_root: str = ""


def set_workspace(path: str) -> None:
    """Set the active workspace directory for all tool operations."""
    global _workspace_root
    _workspace_root = os.path.normpath(path)
    logger.info("Workspace set to: %s", _workspace_root)


def get_workspace() -> str:
    """Return the currently configured workspace root."""
    return _workspace_root


def _resolve_path(path: str) -> str:
    """
    Resolve a path relative to the workspace root.
    Raises ValueError if the resolved path escapes the workspace (path traversal guard).
    """
    if not _workspace_root:
        raise RuntimeError("Workspace root is not configured. Please select a workspace folder first.")

    # If the caller passed an absolute path inside the workspace, use it directly.
    if os.path.isabs(path):
        resolved = os.path.normpath(path)
    else:
        resolved = os.path.normpath(os.path.join(_workspace_root, path))

    # Security guard: prevent path traversal outside the workspace
    if not resolved.startswith(_workspace_root):
        raise ValueError(
            f"Access denied: '{path}' resolves outside the workspace root '{_workspace_root}'."
        )
    return resolved


# ---------------------------------------------------------------------------
# Tool: list_files
# ---------------------------------------------------------------------------
def list_files(directory: str = "") -> str:
    """
    List all files and sub-directories inside the given directory.
    If 'directory' is empty or '.', the workspace root is used.

    Args:
        directory: Relative or absolute path to list. Defaults to workspace root.

    Returns:
        A formatted string listing files and directories.
    """
    try:
        target = _resolve_path(directory) if directory.strip() else _workspace_root

        if not os.path.isdir(target):
            return f"Error: '{target}' is not a valid directory."

        result_lines = [f"📁 Contents of: {target}", ""]
        for root, dirs, files in os.walk(target):
            # Skip hidden directories (e.g., .git, __pycache__)
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
            level = root.replace(target, "").count(os.sep)
            indent = "    " * level
            folder_name = os.path.basename(root) or os.path.basename(target)
            result_lines.append(f"{indent}📂 {folder_name}/")
            sub_indent = "    " * (level + 1)
            for f in files:
                full_path = os.path.join(root, f)
                size = os.path.getsize(full_path)
                result_lines.append(f"{sub_indent}📄 {f}  ({_human_size(size)})")

        if len(result_lines) <= 2:
            result_lines.append("  (empty directory)")

        return "\n".join(result_lines)
    except Exception as exc:
        logger.exception("list_files failed")
        return f"Error listing files: {exc}"


def _human_size(num_bytes: int) -> str:
    """Convert bytes to a human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes //= 1024
    return f"{num_bytes:.1f} TB"


# ---------------------------------------------------------------------------
# Tool: read_file
# ---------------------------------------------------------------------------
def read_file(filepath: str) -> str:
    """
    Read and return the full text content of a file.

    Args:
        filepath: Relative or absolute path to the file.

    Returns:
        The file's text content, or an error message.
    """
    try:
        resolved = _resolve_path(filepath)
        if not os.path.isfile(resolved):
            return f"Error: File not found: '{resolved}'"

        # Limit to 500 KB to avoid overwhelming the context window
        max_bytes = 500 * 1024
        with open(resolved, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read(max_bytes)

        truncated = os.path.getsize(resolved) > max_bytes
        suffix = "\n\n⚠️  [File truncated — only first 500 KB shown]" if truncated else ""
        logger.info("read_file: %s (%d chars)", resolved, len(content))
        return f"📄 File: {resolved}\n\n{content}{suffix}"
    except Exception as exc:
        logger.exception("read_file failed")
        return f"Error reading file: {exc}"


# ---------------------------------------------------------------------------
# Tool: write_file
# ---------------------------------------------------------------------------
def write_file(filepath: str, content: str) -> str:
    """
    Write (create or overwrite) a file with the provided content.
    Parent directories are created automatically.

    Args:
        filepath: Relative or absolute path to write.
        content:  Text content to write into the file.

    Returns:
        A success or error message.
    """
    try:
        resolved = _resolve_path(filepath)
        parent_dir = os.path.dirname(resolved)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        with open(resolved, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)

        size = os.path.getsize(resolved)
        logger.info("write_file: %s (%d bytes)", resolved, size)
        return f"✅ File written successfully: {resolved}  ({_human_size(size)})"
    except Exception as exc:
        logger.exception("write_file failed")
        return f"Error writing file: {exc}"


# ---------------------------------------------------------------------------
# Tool: run_command
# ---------------------------------------------------------------------------
def run_command(command: str) -> str:
    """
    Execute a shell/PowerShell command inside the workspace directory and
    return its stdout + stderr output.

    For safety, interactive commands are disallowed.

    Args:
        command: The shell command to run.

    Returns:
        Combined stdout and stderr output as a string.
    """
    if not _workspace_root:
        return "Error: Workspace root is not configured."

    # Basic safety checks — block inherently dangerous standalone commands
    _BLOCKED = {"rm -rf /", "format c:", "del /s /q c:\\", "rmdir /s /q c:\\"}
    if command.strip().lower() in _BLOCKED:
        return f"Error: Command blocked for safety: '{command}'"

    try:
        logger.info("run_command: %s  (cwd=%s)", command, _workspace_root)
        result = subprocess.run(
            command,
            shell=True,
            cwd=_workspace_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,  # 60-second hard limit
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        output_parts = []
        if stdout:
            output_parts.append(f"STDOUT:\n{stdout}")
        if stderr:
            output_parts.append(f"STDERR:\n{stderr}")
        output_parts.append(f"Return code: {result.returncode}")

        return "\n\n".join(output_parts) if output_parts else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Command timed out after 60 seconds."
    except Exception as exc:
        logger.exception("run_command failed")
        return f"Error running command: {exc}"


# ---------------------------------------------------------------------------
# Gemini Function Declarations (google-genai SDK format)
# ---------------------------------------------------------------------------
from google.genai import types as genai_types  # noqa: E402  (imported late to avoid circular)

TOOL_DECLARATIONS = genai_types.Tool(
    function_declarations=[
        genai_types.FunctionDeclaration(
            name="list_files",
            description=(
                "List all files and sub-directories inside a directory within the workspace. "
                "Use this to explore the project structure before reading or writing files."
            ),
            parameters=genai_types.Schema(
                type=genai_types.Type.OBJECT,
                properties={
                    "directory": genai_types.Schema(
                        type=genai_types.Type.STRING,
                        description=(
                            "The directory path to list (relative to workspace root or absolute). "
                            "Pass an empty string or '.' to list the workspace root."
                        ),
                    )
                },
                required=[],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="read_file",
            description=(
                "Read the full text content of a file in the workspace. "
                "Use this to inspect source code, configuration files, or any text file before making changes."
            ),
            parameters=genai_types.Schema(
                type=genai_types.Type.OBJECT,
                properties={
                    "filepath": genai_types.Schema(
                        type=genai_types.Type.STRING,
                        description="Path to the file (relative to workspace root or absolute).",
                    )
                },
                required=["filepath"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="write_file",
            description=(
                "Create a new file or overwrite an existing file in the workspace with the provided content. "
                "Use this to save code changes, create new scripts, or write configuration files. "
                "Parent directories are created automatically."
            ),
            parameters=genai_types.Schema(
                type=genai_types.Type.OBJECT,
                properties={
                    "filepath": genai_types.Schema(
                        type=genai_types.Type.STRING,
                        description="Path to the file to write (relative to workspace root or absolute).",
                    ),
                    "content": genai_types.Schema(
                        type=genai_types.Type.STRING,
                        description="The complete text content to write into the file.",
                    ),
                },
                required=["filepath", "content"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="run_command",
            description=(
                "Execute a shell or PowerShell command in the workspace directory and return its output. "
                "Use this to run scripts, install packages (pip install), check git status, "
                "run tests, or perform any command-line operation needed for the task."
            ),
            parameters=genai_types.Schema(
                type=genai_types.Type.OBJECT,
                properties={
                    "command": genai_types.Schema(
                        type=genai_types.Type.STRING,
                        description="The shell command to execute (e.g., 'pip install flask', 'python main.py', 'git status').",
                    )
                },
                required=["command"],
            ),
        ),
    ]
)

# Map function names to their Python implementations
TOOL_FUNCTION_MAP: dict = {
    "list_files": list_files,
    "read_file": read_file,
    "write_file": write_file,
    "run_command": run_command,
}
