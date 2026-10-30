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


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> None:
    task = sys.argv[1] if len(sys.argv) > 1 else "help"
    if task == "help":
        print("Targets: setup install run test diagnose models")
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
    else:
        raise SystemExit(f"Unknown target: {task}")


def create_environment() -> None:
    if not VENV_PYTHON.exists():
        venv.EnvBuilder(with_pip=True).create(ROOT / ".venv")
    (ROOT / ".tmp").mkdir(exist_ok=True)


def require_environment() -> None:
    if not VENV_PYTHON.exists():
        raise SystemExit("Run 'make setup' first to create the project environment.")


if __name__ == "__main__":
    main()
