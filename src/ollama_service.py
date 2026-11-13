"""Start the local Ollama server when it is off, on macOS and Windows."""
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

BASE_URL = "http://localhost:11434/api/"
WINDOWS = os.name == "nt"
LOG_PATH = Path(__file__).resolve().parent.parent / ".tmp" / "ollama.log"
logger = logging.getLogger(__name__)


def running():
    try:
        with urlopen(BASE_URL + "version", timeout=2) as response:
            return response.status == 200
    except (OSError, ValueError):
        return False


def _windows_folder():
    local = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    return Path(local) / "Programs" / "Ollama"


def launch_commands():
    """Commands that start Ollama, the desktop app first because it keeps the user's own settings."""
    commands = []
    if sys.platform == "darwin":
        if any(path.is_dir() for path in (Path("/Applications/Ollama.app"),
                                          Path.home() / "Applications" / "Ollama.app")):
            commands.append(["open", "-g", "-a", "Ollama"])
    elif WINDOWS:
        desktop = _windows_folder() / "ollama app.exe"
        if desktop.is_file():
            commands.append([str(desktop)])
    executable = shutil.which("ollama")
    if not executable and WINDOWS and (_windows_folder() / "ollama.exe").is_file():
        executable = str(_windows_folder() / "ollama.exe")
    if executable:
        commands.append([executable, "serve"])
    return commands


def _start(command):
    """Start detached so Ollama keeps running after this app stops, like the desktop app."""
    LOG_PATH.parent.mkdir(exist_ok=True)
    with open(LOG_PATH, "ab") as log:
        options = {"stdin": subprocess.DEVNULL, "stdout": log, "stderr": log}
        if WINDOWS:
            options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        else:
            options["start_new_session"] = True
        subprocess.Popen(command, **options)


def ensure_running(wait_seconds=30):
    """Return True when Ollama answers, starting it first if needed."""
    if running():
        return True
    commands = launch_commands()
    if not commands:
        logger.warning("Ollama is not running and is not installed. Install it from https://ollama.com.")
        return False
    for command in commands:
        logger.info("Ollama is not running; starting it with: %s", " ".join(command))
        try:
            _start(command)
        except OSError as error:
            logger.warning("Could not start Ollama with %s: %s", command[0], error)
            continue
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            if running():
                logger.info("Ollama is running.")
                return True
            time.sleep(0.5)
    logger.warning("Ollama did not start. Start it yourself; the app keeps running meanwhile.")
    return False


def missing_models(names):
    """Required model tags that are not installed; an empty list if Ollama cannot be asked."""
    try:
        with urlopen(BASE_URL + "tags", timeout=5) as response:
            installed = {model.get("name") for model in json.load(response).get("models", [])}
    except (OSError, ValueError, AttributeError):
        return []
    return [name for name in names if name not in installed]
