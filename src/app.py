"""Local Flask interface for Ollama chat."""

import socket
import logging
import argparse
import tempfile
from contextlib import suppress
import sqlite3
from http.client import HTTPException
from pathlib import Path
from uuid import uuid4
from urllib.error import URLError

from flask import Flask, jsonify, render_template, request, send_from_directory
from werkzeug.utils import secure_filename
try:
    from .rag import KnowledgeBase, DocumentError, SUPPORTED, answer
except ImportError:
    from rag import KnowledgeBase, DocumentError, SUPPORTED, answer


def knowledge_base():
    return KnowledgeBase(app.config["UPLOAD_FOLDER"])


# Keep multipart upload scratch files within this workspace too.
TEMP_FOLDER = Path(__file__).resolve().parent.parent / ".tmp"
TEMP_FOLDER.mkdir(exist_ok=True)
tempfile.tempdir = str(TEMP_FOLDER)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024
app.config["UPLOAD_FOLDER"] = Path(__file__).resolve().parent.parent / "uploads"
UPLOAD_LIMIT = 20 * 1024 * 1024


def upload_folder():
    folder = Path(app.config["UPLOAD_FOLDER"])
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def file_info(path):
    return {"id": path.name, "name": path.name.split("--", 1)[-1],
            "size": path.stat().st_size,
            "indexed": path.suffix.lower() in SUPPORTED and knowledge_base().ready(path)}


@app.get("/api/files")
def list_files():
    try:
        files = [file_info(path) for path in upload_folder().iterdir()
                 if path.is_file() and not path.is_symlink() and "--" in path.name]
        return jsonify(files=sorted(files, key=lambda item: item["name"].lower()))
    except (OSError, sqlite3.Error):
        return jsonify(error="Cannot read the uploaded files folder."), 500


@app.post("/api/files")
def upload_file():
    request.max_content_length = UPLOAD_LIMIT
    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        return jsonify(error="Choose a file to upload."), 400
    name = secure_filename(uploaded.filename)
    if not name:
        return jsonify(error="Please use a filename containing letters or numbers."), 400
    if Path(name).suffix.lower() not in SUPPORTED:
        return jsonify(error="Supported file types: PDF, DOCX, TXT and MD."), 400
    destination = None
    try:
        destination = upload_folder() / f"{uuid4().hex}--{name[:180]}"
        uploaded.save(destination)
        knowledge_base().index(destination)
        return jsonify(file=file_info(destination)), 201
    except (DocumentError, ValueError, URLError, TimeoutError, OSError, HTTPException, sqlite3.Error) as error:
        if destination is not None:
            with suppress(OSError):
                destination.unlink(missing_ok=True)
        if isinstance(error, DocumentError):
            return jsonify(error=str(error)), 400
        return jsonify(error="Upload could not be indexed. Check Ollama, nomic-embed-text and disk permissions; then retry."), 503
    finally:
        uploaded.close()


@app.get("/api/files/<file_id>")
def download_file(file_id):
    folder = upload_folder()
    path = folder / file_id
    if path.is_symlink() or "--" not in file_id:
        return jsonify(error="File not found."), 404
    return send_from_directory(folder, file_id, as_attachment=True,
                               download_name=file_id.split("--", 1)[-1])

MODEL = "gemma3:1b"


@app.get("/")
def index():
    return render_template("index.html")


@app.errorhandler(413)
def too_large(error):
    if request.endpoint == "upload_file":
        return jsonify(error="Upload is too large. Choose a file smaller than 20 MiB."), 413
    return jsonify(error="Conversation is too large. Start a new chat."), 413


@app.post("/api/chat")
def chat():
    payload = request.get_json(silent=True)
    messages = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(messages, list) or not messages:
        return jsonify(error="Provide a non-empty messages array."), 400
    for message in messages:
        if (
            not isinstance(message, dict)
            or message.get("role") not in ("user", "assistant")
            or not isinstance(message.get("content"), str)
            or not message["content"].strip()
        ):
            return jsonify(error="Each message needs a user or assistant role and text content."), 400
    if messages[-1]["role"] != "user":
        return jsonify(error="The last message must be from the user."), 400

    question = messages[-1]["content"].strip()
    if len(question) > 4000:
        return jsonify(error="Keep questions under 4000 characters."), 400
    try:
        sources = knowledge_base().retrieve(question)
        content, citations = answer(question, sources, MODEL)
        return jsonify(message={"role": "assistant", "content": content}, sources=citations)
    except DocumentError as error:
        return jsonify(error=str(error)), 409
    except (TimeoutError, socket.timeout):
        return jsonify(error="Ollama took too long. Please retry."), 504
    except (URLError, ConnectionError, HTTPException):
        return jsonify(error="Cannot complete retrieval. Check that Ollama and both models are available."), 503
    except (ValueError, UnicodeError, OSError, sqlite3.Error):
        return jsonify(error="Could not read the knowledge index or Ollama response. Reindex documents and retry."), 502


@app.post("/api/files/index")
def index_files():
    results = []
    for path in upload_folder().iterdir():
        if not path.is_file() or path.is_symlink() or "--" not in path.name:
            continue
        if path.suffix.lower() not in SUPPORTED:
            continue
        try:
            knowledge_base().index(path)
            results.append({"name": file_info(path)["name"], "indexed": True})
        except (ValueError, OSError, URLError, HTTPException, sqlite3.Error) as error:
            detail = str(error) if isinstance(error, DocumentError) else "Indexing failed. Check Ollama and the embedding model."
            results.append({"name": path.name.split("--", 1)[-1], "indexed": False, "error": detail})
    return jsonify(results=results)


def main():
    parser = argparse.ArgumentParser(description="Run local Ollama document chat.")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    logging.basicConfig(level=logging.INFO)
    app.run(host="127.0.0.1", port=args.port, debug=False)


if __name__ == "__main__":
    main()
