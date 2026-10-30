"""Local Flask interface for general and document chat through Ollama."""

import base64
import hashlib
import json
import mimetypes
import socket
import logging
import argparse
import tempfile
from contextlib import closing, suppress
import sqlite3
from http.client import HTTPException
from pathlib import Path
from uuid import uuid4
from urllib.error import URLError

from flask import Flask, Response, jsonify, render_template, request, send_from_directory, stream_with_context
from werkzeug.utils import secure_filename
try:
    from .rag import KnowledgeBase, DocumentError, SUPPORTED, answer
    from .answering import (general_answer, identity_response, is_document_question, library_response,
                            voice_reply, warm_up_voice_model)
    from . import speech
except ImportError:
    from rag import KnowledgeBase, DocumentError, SUPPORTED, answer
    from answering import (general_answer, identity_response, is_document_question, library_response,
                           voice_reply, warm_up_voice_model)
    import speech


def knowledge_base():
    return KnowledgeBase(app.config["UPLOAD_FOLDER"])


# Browsers refuse the voice-activity modules unless they have these types.
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("application/wasm", ".wasm")

# Keep multipart upload scratch files within this workspace too.
TEMP_FOLDER = Path(__file__).resolve().parent.parent / ".tmp"
TEMP_FOLDER.mkdir(exist_ok=True)
tempfile.tempdir = str(TEMP_FOLDER)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024
app.config["UPLOAD_FOLDER"] = Path(__file__).resolve().parent.parent / "uploads"
UPLOAD_LIMIT = 20 * 1024 * 1024
# About two minutes of 16 kHz, 16-bit mono speech.
VOICE_LIMIT = 4 * 1024 * 1024
HASH_SUFFIX = ".sha256"


def upload_folder():
    folder = Path(app.config["UPLOAD_FOLDER"])
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def is_document(path):
    return (path.is_file() and not path.is_symlink() and "--" in path.name
            and path.suffix != HASH_SUFFIX)


def hash_path(path):
    return path.with_name(path.name + HASH_SUFFIX)


def find_duplicate(digest):
    """Return the uploaded document with this hash, recording any missing hashes."""
    for path in upload_folder().iterdir():
        if not is_document(path):
            continue
        stored = hash_path(path)
        if not stored.exists():
            stored.write_text(knowledge_base().fingerprint(path))
        if stored.read_text().strip() == digest:
            return path
    return None


def file_info(path):
    return {"id": path.name, "name": path.name.split("--", 1)[-1],
            "size": path.stat().st_size,
            "indexed": path.suffix.lower() in SUPPORTED and knowledge_base().ready(path)}


@app.get("/api/files")
def list_files():
    try:
        files = [file_info(path) for path in upload_folder().iterdir() if is_document(path)]
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
        digest = hashlib.sha256(uploaded.read()).hexdigest()
        uploaded.seek(0)
        duplicate = find_duplicate(digest)
        if duplicate is not None:
            return jsonify(file=file_info(duplicate), duplicate=True), 200
        destination = upload_folder() / f"{uuid4().hex}--{name[:180]}"
        uploaded.save(destination)
        knowledge_base().index(destination)
        # Written last so a failed upload can be retried.
        hash_path(destination).write_text(digest)
        return jsonify(file=file_info(destination)), 201
    except (DocumentError, ValueError, URLError, TimeoutError, OSError, HTTPException, sqlite3.Error) as error:
        if destination is not None:
            with suppress(OSError):
                destination.unlink(missing_ok=True)
                hash_path(destination).unlink(missing_ok=True)
        if isinstance(error, DocumentError):
            return jsonify(error=str(error)), 400
        return jsonify(error="Upload could not be indexed. Check Ollama, nomic-embed-text and disk permissions; then retry."), 503
    finally:
        uploaded.close()


@app.get("/api/files/<file_id>")
def download_file(file_id):
    folder = upload_folder()
    path = folder / file_id
    if path.is_symlink() or "--" not in file_id or path.suffix == HASH_SUFFIX:
        return jsonify(error="File not found."), 404
    return send_from_directory(folder, file_id, as_attachment=True,
                               download_name=file_id.split("--", 1)[-1])


@app.get("/api/files/<file_id>/preview")
def preview_file(file_id):
    folder = upload_folder()
    path = folder / file_id
    if Path(file_id).name != file_id or not is_document(path) or path.suffix.lower() != ".pdf":
        return jsonify(error="File not found."), 404
    response = send_from_directory(folder, file_id, mimetype="application/pdf")
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.delete("/api/files/<file_id>")
def delete_file(file_id):
    folder = upload_folder()
    if Path(file_id).name != file_id or "--" not in file_id:
        return jsonify(error="File not found."), 404
    path = folder / file_id
    if not is_document(path):
        return jsonify(error="File not found."), 404
    try:
        path.unlink()
        hash_path(path).unlink(missing_ok=True)
        with knowledge_base().connect() as db:
            db.execute("DELETE FROM documents WHERE id=?", (file_id,))
        return "", 204
    except (OSError, sqlite3.Error):
        app.logger.exception("Could not remove uploaded document %s", file_id)
        return jsonify(error="Could not remove this document. Check file and index permissions."), 500

MODEL = "qwen3:1.7b"


@app.get("/")
def index():
    return render_template("index.html")


@app.errorhandler(413)
def too_large(error):
    if request.endpoint == "upload_file":
        return jsonify(error="Upload is too large. Choose a file smaller than 20 MiB."), 413
    if request.endpoint == "transcribe_voice":
        return jsonify(error="That was too long to transcribe. Please say it in shorter parts."), 413
    return jsonify(error="Conversation is too large. Start a new chat."), 413


def messages_error(messages):
    """Return why a chat history is invalid, or None when it is usable."""
    if not isinstance(messages, list) or not messages:
        return "Provide a non-empty messages array."
    for message in messages:
        if (
            not isinstance(message, dict)
            or message.get("role") not in ("user", "assistant")
            or not isinstance(message.get("content"), str)
            or not message["content"].strip()
        ):
            return "Each message needs a user or assistant role and text content."
    if messages[-1]["role"] != "user":
        return "The last message must be from the user."
    if len(messages[-1]["content"].strip()) > 4000:
        return "Keep questions under 4000 characters."
    return None


@app.post("/api/chat")
def chat():
    payload = request.get_json(silent=True)
    messages = payload.get("messages") if isinstance(payload, dict) else None
    invalid = messages_error(messages)
    if invalid:
        return jsonify(error=invalid), 400

    question = messages[-1]["content"].strip()
    identity = identity_response(question, MODEL)
    if identity:
        return jsonify(message={"role": "assistant", "content": identity}, sources=[], mode="general")
    try:
        names = sorted((path.name.split("--", 1)[-1] for path in upload_folder().iterdir()
                        if is_document(path)), key=str.lower)
        library = library_response(question, names)
        if library:
            return jsonify(message={"role": "assistant", "content": library}, sources=[], mode="library")
        sources = knowledge_base().retrieve(question)
        if not is_document_question(question, sources):
            content = general_answer(messages, MODEL)
            return jsonify(message={"role": "assistant", "content": content}, sources=[], mode="general")
        content, citations = answer(question, sources, MODEL)
        return jsonify(message={"role": "assistant", "content": content}, sources=citations, mode="documents")
    except DocumentError as error:
        return jsonify(error=str(error)), 409
    except (TimeoutError, socket.timeout):
        return jsonify(error="Ollama took too long. Please retry."), 504
    except (URLError, ConnectionError, HTTPException):
        return jsonify(error="Cannot complete retrieval. Check that Ollama and both models are available."), 503
    except ValueError as error:
        app.logger.warning("Answer failed: %s", error)
        return jsonify(error="Ollama returned an invalid response. Please retry; check the server log if it continues."), 502
    except (UnicodeError, OSError, sqlite3.Error):
        return jsonify(error="Could not read the knowledge index. Check the files and reindex documents."), 502


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


@app.get("/api/voice/status")
def voice_status():
    available = speech.available()
    return jsonify(available=available, reason=None if available else speech.UNAVAILABLE)


@app.post("/api/voice/warmup")
def warm_up_voice():
    try:
        speech.warm_up()
        warm_up_voice_model(MODEL)
        return "", 204
    except speech.SpeechError as error:
        return jsonify(error=str(error)), 503
    except (URLError, ConnectionError, HTTPException, TimeoutError, ValueError):
        return jsonify(error=f"Cannot load {MODEL}. Check that Ollama is running."), 503


@app.post("/api/voice/transcribe")
def transcribe_voice():
    request.max_content_length = VOICE_LIMIT
    try:
        return jsonify(text=speech.transcribe(request.get_data()))
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except speech.SpeechError as error:
        return jsonify(error=str(error)), 503


def voice_event(**fields):
    return json.dumps(fields) + "\n"


def voice_events(messages):
    """Yield one event per spoken sentence; errors are events because HTTP 200 is already sent."""
    spoken = False
    try:
        with closing(voice_reply(messages, MODEL)) as chunks:
            for sentence in speech.split_sentences(chunks):
                text = speech.clean_for_speech(sentence)
                if text:
                    audio = base64.b64encode(speech.synthesize(text)).decode("ascii")
                    spoken = True
                    yield voice_event(type="sentence", text=text, audio=audio)
        if not spoken:
            raise ValueError("Ollama returned an empty answer.")
        yield voice_event(type="done")
    except speech.SpeechError as error:
        yield voice_event(type="error", message=str(error))
    except (TimeoutError, socket.timeout, URLError, ConnectionError, HTTPException):
        yield voice_event(type="error", message=f"Cannot reach {MODEL}. Check that Ollama is running.")
    except ValueError as error:
        app.logger.warning("Voice answer failed: %s", error)
        yield voice_event(type="error", message="Ollama returned an invalid response. Please try again.")


@app.post("/api/voice/reply")
def voice_reply_stream():
    payload = request.get_json(silent=True)
    messages = payload.get("messages") if isinstance(payload, dict) else None
    invalid = messages_error(messages)
    if invalid:
        return jsonify(error=invalid), 400
    return Response(stream_with_context(voice_events(messages)), mimetype="application/x-ndjson")


def main():
    parser = argparse.ArgumentParser(description="Run local Ollama document chat.")
    parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    app.run(host="127.0.0.1", port=5050, debug=False)
