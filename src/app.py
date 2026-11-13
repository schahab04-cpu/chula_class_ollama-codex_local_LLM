"""Local Flask interface for general and document chat through Ollama."""

import base64
import hashlib
import json
import mimetypes
import socket
import logging
import argparse
import tempfile
import threading
from contextlib import closing, contextmanager, suppress
import sqlite3
from http.client import HTTPException
from pathlib import Path
from uuid import uuid4
from urllib.error import URLError

from flask import Flask, Response, jsonify, render_template, request, send_from_directory, stream_with_context
from werkzeug.utils import secure_filename
try:
    from .rag import KnowledgeBase, DocumentError, SUPPORTED, answer
    from .answering import (NOT_FOUND, UPLOAD_MESSAGE, UNCONFIRMED_FIGURE, VOICE_KEEP_ALIVE, citations, general_answer,
                            identity_response, is_document_question, is_upload_request, library_response, mentioned_documents, mentions_document, strip_echo, route_with_summaries, select_evidence,
                            unsupported_numbers, voice_document_reply, voice_library_response,
                            voice_reply, warm_up_voice_model, web_answer)
    from . import ollama_service, speech, web_search
    from .quiz import (is_quiz_request, make_quiz, question_count, quiz_message, quiz_topic,
                       spoken_quiz_message)
except ImportError:
    from rag import KnowledgeBase, DocumentError, SUPPORTED, answer
    from answering import (NOT_FOUND, UPLOAD_MESSAGE, UNCONFIRMED_FIGURE, VOICE_KEEP_ALIVE, citations, general_answer,
                           identity_response, is_document_question, is_upload_request, library_response, mentioned_documents, mentions_document, strip_echo, route_with_summaries, select_evidence,
                           unsupported_numbers, voice_document_reply, voice_library_response,
                           voice_reply, warm_up_voice_model, web_answer)
    import ollama_service
    import speech
    import web_search
    from quiz import (is_quiz_request, make_quiz, question_count, quiz_message, quiz_topic,
                      spoken_quiz_message)


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
    failure = _index_failures.get(path.name)
    return {"id": path.name, "name": path.name.split("--", 1)[-1],
            "size": path.stat().st_size,
            "indexed": path.suffix.lower() in SUPPORTED and knowledge_base().ready(path),
            "error": failure[1] if failure else None}


# Files are processed automatically; nobody should have to press a button for it.
_index_lock = threading.Lock()
# While documents are indexed or summarized, Yapperton does not take questions.
_busy_lock = threading.Lock()
_busy = {"count": 0, "detail": ""}
BUSY_MESSAGE = "Yapperton is still reading your documents. Try again in a moment."


@contextmanager
def processing(detail):
    with _busy_lock:
        _busy["count"] += 1
        _busy["detail"] = detail
    try:
        yield
    finally:
        with _busy_lock:
            _busy["count"] -= 1
            if not _busy["count"]:
                _busy["detail"] = ""


def documents_busy():
    with _busy_lock:
        return _busy["count"] > 0, _busy["detail"]
# Unreadable files by ID: (fingerprint, reason). Skipped until their content changes.
_index_failures = {}


def refresh_index():
    """Index supported files whose search data is missing or stale (added by hand, changed,
    or from before a model change). Operational errors propagate; unreadable files are
    remembered so every question does not retry them."""
    kb = knowledge_base()
    with _index_lock:
        for path in upload_folder().iterdir():
            if not is_document(path) or path.suffix.lower() not in SUPPORTED:
                continue
            if kb.ready(path):
                _index_failures.pop(path.name, None)
                continue
            fingerprint = kb.fingerprint(path)
            failed = _index_failures.get(path.name)
            if failed and failed[0] == fingerprint:
                continue
            app.logger.info("Indexing %s", path.name)
            try:
                with processing(f"Reading {path.name.split('--', 1)[-1]}"):
                    kb.index(path, summary_model=MODEL)
                _index_failures.pop(path.name, None)
            except DocumentError as error:
                _index_failures[path.name] = (fingerprint, str(error))
                app.logger.warning("Cannot read %s: %s", path.name, error)


def prepare_documents():
    """Startup work in the background: index stale files, then fill in missing summaries."""
    try:
        refresh_index()
        kb = knowledge_base()
        if kb.missing_summaries():
            with processing("Summarizing your documents"):
                kb.fill_missing_summaries(MODEL)
    except Exception:  # Startup must not fail; questions retry indexing anyway.
        app.logger.exception("Background document preparation failed")


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
        with processing(f"Reading {name}"):
            knowledge_base().index(destination, summary_model=MODEL)
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
        knowledge_base().forget(file_id)
        return "", 204
    except (OSError, sqlite3.Error):
        app.logger.exception("Could not remove uploaded document %s", file_id)
        return jsonify(error="Could not remove this document. Check file and index permissions."), 500

MODEL = "qwen3.5:9b"


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


def document_names():
    return sorted((path.name.split("--", 1)[-1] for path in upload_folder().iterdir()
                   if is_document(path)), key=str.lower)


def clearly_documents(question, sources):
    """Routing decided in code: a strong passage match, a document reference or a filename."""
    return bool(sources) and (is_document_question(question, sources)
                              or mentions_document(question, document_names()))


def needs_documents(question, sources):
    """Hybrid routing: code handles the clear cases; the model reads document summaries for the
    rest. This split is a first version and may change."""
    if not sources:
        return False
    if clearly_documents(question, sources):
        return True
    summaries = knowledge_base().summaries()
    return bool(summaries) and route_with_summaries(question, summaries, MODEL)


def follow_up_context(messages):
    """Text that resolves "it" in a follow-up: the file list after a library answer, or the
    previous question after a document answer; empty otherwise."""
    previous = next((m for m in reversed(messages[:-1]) if m["role"] == "assistant"), {})
    if previous.get("mode") == "library":
        return previous["content"].strip()
    if previous.get("mode") == "documents":
        return next((m["content"].strip() for m in reversed(messages[:-1]) if m["role"] == "user"), "")
    return ""


def route_documents(messages, sources, keep_alive=None):
    """Return (question, sources) to answer from the documents, or None for a general answer."""
    question = messages[-1]["content"].strip()
    if clearly_documents(question, sources):
        return question, sources
    context = follow_up_context(messages)
    if context:
        merged = f"{context}\n{question}"
        merged_sources = knowledge_base().retrieve(merged, keep_alive=keep_alive)
        if clearly_documents(merged, merged_sources):
            return merged, merged_sources
    if needs_documents(question, sources):
        return question, sources
    return None


def build_quiz(question, keep_alive=None):
    """Return (quiz, None) for a quiz request, or (None, reason) when no quiz can be made."""
    names = document_names()
    if not names:
        return None, "Upload a document first, then ask me to quiz you on it."
    topic, count = quiz_topic(question), question_count(question)
    named = mentioned_documents(topic, names) if topic else []
    limit = min(12, max(8, count))
    if named or not topic:
        # A whole document or the whole library: sample passages from beginning to end.
        sources = knowledge_base().passages(names=named or None, limit=limit)
    else:
        sources = knowledge_base().retrieve(topic, keep_alive=keep_alive)
        if not needs_documents(topic, sources):
            return None, (f"Your documents don't seem to cover {topic}. Ask for a quiz on a topic "
                          "from them, or just say quiz me.")
    if not sources:
        return None, "Your documents have no text I can make questions from."
    covered = named or (names if not topic else [])
    title = " and ".join(name.rsplit(".", 1)[0].replace("_", " ") for name in covered[:3]) if covered else ""
    return make_quiz(topic, sources, MODEL, count, title=title), None


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

    busy, _ = documents_busy()
    if busy:
        return jsonify(error=BUSY_MESSAGE, busy=True), 409
    question = messages[-1]["content"].strip()
    identity = identity_response(question, MODEL)
    if identity:
        return jsonify(message={"role": "assistant", "content": identity}, sources=[], mode="general")
    if is_upload_request(question):
        return jsonify(message={"role": "assistant", "content": UPLOAD_MESSAGE}, sources=[], mode="upload")
    try:
        library = library_response(question, document_names())
        if library:
            return jsonify(message={"role": "assistant", "content": library}, sources=[], mode="library")
        refresh_index()
        if is_quiz_request(question):
            quiz, reason = build_quiz(question)
            return jsonify(message={"role": "assistant", "content": quiz_message(quiz) if quiz else reason},
                           sources=[], mode="quiz", quiz=quiz)
        sources = knowledge_base().retrieve(question)
        query = web_search.search_query(messages)
        # Fact checks of document answers stay with the documents.
        if query and not is_document_question(query, sources if query == question
                                                else knowledge_base().retrieve(query)):
            content, results = web_answer(messages, query, web_search.search(query), MODEL)
            return jsonify(message={"role": "assistant", "content": content}, sources=results, mode="web")
        routed = route_documents(messages, sources)
        if routed is None:
            content = general_answer(messages, MODEL)
            return jsonify(message={"role": "assistant", "content": content}, sources=[], mode="general")
        content, citations = answer(*routed, MODEL)
        return jsonify(message={"role": "assistant", "content": content}, sources=citations, mode="documents")
    except DocumentError as error:
        return jsonify(error=str(error)), 409
    except web_search.SearchError as error:
        return jsonify(error=str(error)), 503
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
            with processing(f"Reading {path.name.split('--', 1)[-1]}"):
                knowledge_base().index(path, summary_model=MODEL)
            results.append({"name": file_info(path)["name"], "indexed": True})
        except (ValueError, OSError, URLError, HTTPException, sqlite3.Error) as error:
            detail = str(error) if isinstance(error, DocumentError) else "Indexing failed. Check Ollama and the embedding model."
            results.append({"name": path.name.split("--", 1)[-1], "indexed": False, "error": detail})
    return jsonify(results=results)


@app.get("/api/documents/status")
def documents_status():
    busy, detail = documents_busy()
    return jsonify(busy=busy, detail=detail)


@app.get("/api/voice/status")
def voice_status():
    available = speech.available()
    return jsonify(available=available, reason=None if available else speech.UNAVAILABLE)


@app.post("/api/voice/warmup")
def warm_up_voice():
    try:
        speech.warm_up()
        warm_up_voice_model(MODEL)
        knowledge_base().warm_up(VOICE_KEEP_ALIVE)
        return "", 204
    except speech.SpeechError as error:
        return jsonify(error=str(error)), 503
    except (URLError, ConnectionError, HTTPException, TimeoutError, ValueError):
        return jsonify(error=f"Cannot load {MODEL}. Check that Ollama is running."), 503


@app.get("/api/voice/fillers")
def voice_fillers():
    try:
        rendered = speech.fillers()
    except speech.SpeechError as error:
        return jsonify(error=str(error)), 503
    return jsonify(fillers=[{"text": text, "audio": base64.b64encode(audio).decode("ascii")}
                            for text, audio in rendered])


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


QUIZ_WAIT = ("Okay, writing your quiz now. I think through and check every question, "
             "so this takes a few minutes. It will appear on screen when it's ready.")


def spoken_once(text):
    yield text


def voice_route(messages):
    """Route a spoken turn like text chat, without web search; returns (mode, chunks, evidence)."""
    question = messages[-1]["content"].strip()
    if identity_response(question, MODEL):
        return "general", voice_reply(messages, MODEL), []
    library = voice_library_response(question, document_names())
    if library:
        return "library", spoken_once(library), []
    refresh_index()
    sources = knowledge_base().retrieve(question, keep_alive=VOICE_KEEP_ALIVE)
    routed = route_documents(messages, sources, keep_alive=VOICE_KEEP_ALIVE)
    if routed is None:
        return "general", voice_reply(messages, MODEL), []
    question, sources = routed
    evidence = select_evidence(question, sources, MODEL)
    if not evidence:
        return "documents", spoken_once(NOT_FOUND), []
    return "documents", voice_document_reply(question, evidence, MODEL), evidence


def voice_events(messages):
    """Yield one event per spoken sentence; errors are events because HTTP 200 is already sent."""
    spoken = []

    def say(text):
        audio = base64.b64encode(speech.synthesize(text)).decode("ascii")
        spoken.append(text)
        return voice_event(type="sentence", text=text, audio=audio)

    try:
        question = messages[-1]["content"].strip()
        if is_upload_request(question) and not identity_response(question, MODEL):
            # The page opens its upload box; uploads go through the same /api/files route.
            yield voice_event(type="upload")
            yield say(UPLOAD_MESSAGE)
            yield voice_event(type="done", mode="upload")
            return
        if is_quiz_request(question) and not identity_response(question, MODEL):
            # Quizzes take a minute, so say so before writing it.
            yield say(QUIZ_WAIT)
            refresh_index()
            quiz, reason = build_quiz(question, keep_alive=VOICE_KEEP_ALIVE)
            if quiz:
                yield voice_event(type="quiz", quiz=quiz)
            yield say(spoken_quiz_message(quiz) if quiz else reason)
            yield voice_event(type="done", mode="quiz")
            return
        mode, chunks, evidence = voice_route(messages)
        cited_text = " ".join(f'{s["text"]} {s["name"]} {s["location"]}' for s in evidence)
        with closing(chunks):
            for sentence in speech.split_sentences(chunks):
                # Only the opening sentence can be an echoed question.
                text = speech.clean_for_speech(sentence if spoken else strip_echo(sentence, question))
                # Streaming leaves no finished answer to check, so check figures sentence by sentence.
                if text and evidence and unsupported_numbers(text, cited_text):
                    app.logger.info("Voice answer: replaced a sentence with unsupported figures")
                    text = "" if spoken and spoken[-1] == UNCONFIRMED_FIGURE else UNCONFIRMED_FIGURE
                if text:
                    yield say(text)
        if not spoken:
            raise ValueError("Ollama returned an empty answer.")
        if evidence:
            yield voice_event(type="sources", sources=citations(" ".join(spoken), evidence))
        yield voice_event(type="done", mode=mode)
    except speech.SpeechError as error:
        yield voice_event(type="error", message=str(error))
    except DocumentError as error:
        yield voice_event(type="error", message=str(error))
    except (TimeoutError, socket.timeout, URLError, ConnectionError, HTTPException):
        yield voice_event(type="error", message=f"Cannot reach {MODEL}. Check that Ollama is running.")
    except ValueError as error:
        app.logger.warning("Voice answer failed: %s", error)
        yield voice_event(type="error", message="Ollama returned an invalid response. Please try again.")
    except (UnicodeError, OSError, sqlite3.Error):
        yield voice_event(type="error", message="Could not read the knowledge index. Check the files and reindex documents.")


@app.post("/api/voice/reply")
def voice_reply_stream():
    payload = request.get_json(silent=True)
    messages = payload.get("messages") if isinstance(payload, dict) else None
    invalid = messages_error(messages)
    if invalid:
        return jsonify(error=invalid), 400
    if documents_busy()[0]:
        return jsonify(error=BUSY_MESSAGE, busy=True), 409
    return Response(stream_with_context(voice_events(messages)), mimetype="application/x-ndjson")


def main():
    parser = argparse.ArgumentParser(description="Run local Ollama document chat.")
    parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if ollama_service.ensure_running():
        # Documents indexed before summaries existed get one now, without blocking startup.
        threading.Thread(target=prepare_documents, daemon=True).start()
        missing = ollama_service.missing_models([MODEL, KnowledgeBase(upload_folder()).model])
        if missing:
            app.logger.warning("Missing Ollama models: %s. Pull them with: %s", ", ".join(missing),
                               " && ".join(f"ollama pull {name}" for name in missing))
    app.logger.info("Open http://127.0.0.1:5050 to talk.")
    app.run(host="127.0.0.1", port=5050, debug=False)
