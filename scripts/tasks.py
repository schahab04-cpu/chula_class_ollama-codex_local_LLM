"""Small cross-platform command runner for the project's Makefile."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import shutil
import venv
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
WINDOWS = os.name == "nt"
VENV_PYTHON = ROOT / ".venv" / ("Scripts/python.exe" if WINDOWS else "bin/python")
# Must match src/speech.py: Apple silicon uses MLX, everything else ONNX/CTranslate2 on the CPU.
MLX = sys.platform == "darwin" and platform.machine() == "arm64"
VOICE_MODELS = ((
    ("mlx-community/whisper-large-v3-turbo", "whisper-large-v3-turbo"),
    ("mlx-community/Kokoro-82M-bf16", "Kokoro-82M-bf16"),
) if MLX else (
    ("mobiuslabsgmbh/faster-whisper-large-v3-turbo", "faster-whisper-large-v3-turbo"),
))
KOKORO_ONNX_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
KOKORO_ONNX_FILES = ("kokoro-v1.0.onnx", "voices-v1.0.bin")
DOWNLOAD = "import sys; from huggingface_hub import snapshot_download; snapshot_download(sys.argv[1], local_dir=sys.argv[2])"


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
        run(["ollama", "pull", "qwen3.5:9b"])
        run(["ollama", "pull", "nomic-embed-text"])
    elif task == "voice-install":
        require_environment()
        env = os.environ.copy()
        for name in ("TMPDIR", "TEMP", "TMP"):
            env[name] = str(ROOT / ".tmp")
        subprocess.run(
            [str(VENV_PYTHON), "-m", "pip", "install", "--no-cache-dir", "-r", "requirements-voice.txt"],
            cwd=ROOT,
            env=env,
            check=True,
        )
    elif task == "voice-models":
        require_environment()
        env = os.environ.copy()
        env["HF_HOME"] = str(ROOT / ".models" / "hf-cache")
        for repo, folder in VOICE_MODELS:
            subprocess.run(
                [str(VENV_PYTHON), "-c", DOWNLOAD, repo, str(ROOT / ".models" / folder)],
                cwd=ROOT,
                env=env,
                check=True,
            )
        if not MLX:
            download_kokoro_onnx(ROOT / ".models" / "kokoro-onnx")
    else:
        raise SystemExit(f"Unknown target: {task}")


def create_environment() -> None:
    if not VENV_PYTHON.exists():
        venv.EnvBuilder(with_pip=True).create(ROOT / ".venv")
    (ROOT / ".tmp").mkdir(exist_ok=True)


def download_kokoro_onnx(folder: Path) -> None:
    """Fetch Kokoro's ONNX model and voices; a partial download never looks complete."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in KOKORO_ONNX_FILES:
        target = folder / name
        if target.exists():
            continue
        print(f"Downloading {name}...")
        partial = target.with_name(name + ".part")
        with urlopen(KOKORO_ONNX_URL + name) as response, open(partial, "wb") as output:
            shutil.copyfileobj(response, output)
        partial.replace(target)


def require_environment() -> None:
    if not VENV_PYTHON.exists():
        raise SystemExit("Run 'make setup' first to create the project environment.")


if __name__ == "__main__":
    main()
