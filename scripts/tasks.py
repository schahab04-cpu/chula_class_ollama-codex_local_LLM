"""Small cross-platform command runner for the project's Makefile."""

from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WINDOWS = os.name == "nt"
VENV_PYTHON = ROOT / ".venv" / ("Scripts/python.exe" if WINDOWS else "bin/python")
VOICE_MODELS = (
    ("mlx-community/whisper-large-v3-turbo", "whisper-large-v3-turbo"),
    ("mlx-community/Kokoro-82M-bf16", "Kokoro-82M-bf16"),
)


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> None:
    task = sys.argv[1] if len(sys.argv) > 1 else "help"
    if task == "help":
        print("Targets: setup install run test diagnose models voice-install voice-models")
    elif task == "setup":
        if not VENV_PYTHON.exists():
            venv.EnvBuilder(with_pip=True).create(ROOT / ".venv")
        (ROOT / ".tmp").mkdir(exist_ok=True)
        print(f"Created project environment at {ROOT / '.venv'}")
    elif task == "install":
        if not VENV_PYTHON.exists():
            create_environment()
        env = os.environ.copy()
        env["TEMP"] = str(ROOT / ".tmp")
        env["TMP"] = str(ROOT / ".tmp")
        subprocess.run(
            [str(VENV_PYTHON), "-m", "pip", "install", "--no-cache-dir", "-r", "requirements.txt"],
            cwd=ROOT,
            env=env,
            check=True,
        )
    elif task == "run":
        require_environment()
        run([str(VENV_PYTHON), "app.py"])
    elif task == "test":
        require_environment()
        run([str(VENV_PYTHON), "-B", "-m", "unittest", "discover", "-s", "tests", "-v"])
    elif task == "diagnose":
        require_environment()
        run([str(VENV_PYTHON), "-B", "-m", "src.diagnose"])
    elif task == "models":
        run(["ollama", "pull", "qwen3:1.7b"])
        run(["ollama", "pull", "nomic-embed-text"])
    elif task == "voice-install":
        require_voice_platform()
        require_environment()
        env = os.environ.copy()
        env["TMPDIR"] = str(ROOT / ".tmp")
        subprocess.run(
            [str(VENV_PYTHON), "-m", "pip", "install", "--no-cache-dir", "-r", "requirements-voice.txt"],
            cwd=ROOT,
            env=env,
            check=True,
        )
    elif task == "voice-models":
        require_voice_platform()
        require_environment()
        env = os.environ.copy()
        env["HF_HOME"] = str(ROOT / ".models" / "hf-cache")
        for repo, folder in VOICE_MODELS:
            subprocess.run(
                [str(VENV_PYTHON.with_name("hf")), "download", repo, "--local-dir", str(ROOT / ".models" / folder)],
                cwd=ROOT,
                env=env,
                check=True,
            )
    else:
        raise SystemExit(f"Unknown target: {task}")


def create_environment() -> None:
    if not VENV_PYTHON.exists():
        venv.EnvBuilder(with_pip=True).create(ROOT / ".venv")
    (ROOT / ".tmp").mkdir(exist_ok=True)


def require_voice_platform() -> None:
    if sys.platform != "darwin":
        raise SystemExit("Voice mode runs only on macOS.")


def require_environment() -> None:
    if not VENV_PYTHON.exists():
        raise SystemExit("Run 'make setup' first to create the project environment.")


if __name__ == "__main__":
    main()
