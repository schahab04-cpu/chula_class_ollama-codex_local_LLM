# Repository Guidelines

## Scope and working directory

Work only inside `C:\Users\schah\codex-ollama` (`~/codex-ollama`). Run commands
from this root. Keep source, dependencies, logs, scratch files and test fixtures
inside this project. Use `.venv\Scripts\python.exe`; do not switch to Anaconda,
other Python environments, or another project directory. The user prefers small,
practical changes and quick verification over unnecessary tooling or refactoring.

## Current application

This is an implemented local Flask application with plain HTML/CSS/JavaScript and
general chat plus document-based RAG with generated explanations. Do not treat the workspace as an empty scaffold.

- `src/app.py`: Flask routes, upload validation, error handling and local startup.
- `app.py`: the single launcher importing `src.app.main`; start with
  `.\.venv\Scripts\python.exe app.py`.
- `GIT_GUIDE.md`: first-upload steps and a short Git explanation. `origin` points
  to `https://github.com/schahab04-cpu/chula_class_ollama-codex_local_LLM.git`.
- `src/rag.py`: document extraction, chunking, Ollama embeddings, hybrid SQLite retrieval,
  generated explanations with server-resolved citations.
- `src/diagnose.py`: read-only upload/index audits and optional live retrieval/evidence probes.
  Run with `.\.venv\Scripts\python.exe -B -m src.diagnose`.
- `src/templates/index.html`: voice-first page; the voice screen is the page and chat plus
  document manager sit side by side in the `#workspace` dialog ("Chat & documents").
- `src/static/chat.js`: chat requests, history and source download links.
- `src/static/files.js`: uploads, readiness status and manual indexing.
- `src/static/views.js`: legacy view-switching asset; the active interface keeps
  chat and document management side by side.
- `src/static/voice.js`: voice conversation state machine; shares `messages` and
  `appendMessage` with `chat.js`.
- `src/static/wisp.js`: canvas animation for the voice view; exposes only `wisp`. Each state has
  its own colours; speaking pulses outward with the voice, listening draws rings flowing inward
  (brighter with speech), transcribing draws two circling comets, reading is green, and
  loading ("Getting ready") spins with one stretching arc like a loading spinner.
- `src/quiz.py`: quiz request parsing and multiple-choice generation with validation.
- `src/static/quiz.js`: `renderQuiz(quiz)`, shared by the chat transcript and the voice
  screen's quiz panel; clicking an option reveals the result, explanation and source.
- `src/static/vendor/vad/`: pinned Silero VAD and ONNX runtime files; do not edit.
- `src/speech.py`: Whisper and Kokoro on one worker thread, sentence splitting, markup cleanup.
- `src/static/style.css`: responsive layout and view visibility.
- `tests/test_app.py`, `tests/test_files.py`, `tests/test_rag.py`: unittest coverage.
- `requirements.txt`: Flask, pypdf, python-docx and ddgs dependency ranges.
- `src/web_search.py`: fact-check triggers, Wikipedia search with DuckDuckGo fallback.
- `uploads/`: original documents and `knowledge.sqlite3` (ignored by Git).
- `.venv/`: project Python environment (ignored). On macOS use `.venv/bin/python`.
- `.models/`: voice mode's speech models (ignored).
- `requirements-voice.txt`: speech packages with platform markers (MLX on Apple silicon,
  faster-whisper and kokoro-onnx elsewhere), separate from `requirements.txt`.
- `src/ollama_service.py`: at launch, starts Ollama when it is off (desktop app first, then
  `ollama serve`, detached, log in `.tmp/ollama.log`) and logs missing models.
- `.tmp/`: upload scratch files, local installation scratch files and server logs
  when launched with output redirection (ignored).

## Runtime and commands

Python 3.10+ is required. Ollama serves locally at `http://localhost:11434`.
Use `qwen3.5:9b` for answers (switched from qwen3:1.7b at the user's request; it fits a 24 GB Mac beside voice mode) and **`nomic-embed-text:latest` for embeddings**.
The user explicitly requested these models; preserve that choice unless asked to
change it. Models are managed by the existing Ollama installation; do not relocate
its storage.

Run from the repository root in PowerShell:

```powershell
# Create only if the project environment is missing.
python -m venv .venv

# Keep installation scratch files inside the project.
New-Item -ItemType Directory -Force .tmp | Out-Null
$env:TEMP = Join-Path (Get-Location) '.tmp'
$env:TMP = $env:TEMP

# Needed only if pip is missing.
.\.venv\Scripts\python.exe -m ensurepip
.\.venv\Scripts\python.exe -m pip install --no-cache-dir -r requirements.txt

# Pull only when a required model is absent.
ollama list
ollama pull qwen3.5:9b
ollama pull nomic-embed-text

# Start the application; it starts Ollama if it is not running.
.\.venv\Scripts\python.exe app.py

# Automated verification; no running Ollama required.
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

Open only `http://127.0.0.1:5050`. Port 5050 is fixed (macOS AirPlay Receiver
occupies 5000); do not add alternate ports
or additional launchers. Stop this project's previous server before restarting.
Flask binds to localhost, with debug and automatic
reload disabled. Restart this project's server after Python changes; reload the
browser after frontend changes. Do not stop unrelated processes to free a port.
No environment variables configure the application; the TEMP/TMP settings above
only control installation scratch files. No build, formatter, lint command or
coverage threshold is configured. If Node is available, `node --check` can check
the JavaScript files without installing frontend packages.

## RAG behavior and invariants

- Accept PDF, DOCX, TXT and MD. TXT/MD require UTF-8 (optional BOM).
- Upload requests, including multipart overhead, are limited to 20 MiB. Other
  requests are limited to 1 MiB; the latest chat question is at most 4,000 characters.
- Extract PDF page text, DOCX body paragraphs/tables and TXT/MD paragraphs.
  Reject encrypted PDFs, unreadable or empty files and binary text. Scanned PDFs
  need OCR before upload; OCR is not implemented.
- Limits: 500 PDF pages, two million extracted characters, 1,000 chunks per file,
  and 50 MiB expanded DOCX archive size.
- Normalize whitespace; split each location into chunks of up to 1,000 characters,
  preferring sentence/word boundaries with a target 150-character overlap.
  Keep page/block/paragraph references. Existing chunks remain compatible.
- Embed in batches of 16 using `search_document: ` and `search_query: ` prefixes,
  with truncation disabled. Validate and normalize vectors.
- Store original filenames, SHA-256 fingerprints, model tags, passages, locations
  and vectors in SQLite under `uploads/`. Publish an index entry only after all
  passages have been embedded. Database connections must close explicitly.
- Hash each upload with SHA-256 and save it beside the file as `<file id>.sha256`.
  An upload matching an existing document's hash does nothing, even under another
  name. Documents missing a hash get one during the next upload check. Deleting a
  document deletes its hash; failed uploads leave none.
- Uploads index synchronously; failed uploads are removed. There is no Index documents
  button: `refresh_index` (src/app.py) indexes missing or stale files at startup (background)
  and before retrieval, quizzes and voice answers. Unreadable files are remembered by
  fingerprint in `_index_failures`, shown in the file list as "Could not be read", and not
  retried until they change. Retrieval and sampling skip files without current data instead
  of raising; deleted files are excluded. `POST /api/files/index` remains a forced reindex.
- While indexing or summarizing (`processing()` context, `GET /api/documents/status`),
  `/api/chat` and `/api/voice/reply` return 409 `{busy: true}`. files.js polls the status and
  dispatches `documents-busy`; chat disables input and voice pauses the mic in a `reading`
  state (the user asked that Yapperton cannot be used meanwhile).
- Upload requests (`is_upload_request`, checked after identity and before library/quiz) return
  `mode: "upload"` in chat and an `upload` event in voice; both open `#upload-dialog`, which uses
  the same upload code as the Documents panel (`openUploadDialog` in files.js).
- Retrieve up to eight passages with hybrid cosine/normalized keyword rankings,
  reserving four candidates per ranking and ordering by reciprocal rank fusion.
  Search scans vectors in Python and is intended for small local collections.
- Route each question after retrieval: use RAG when the best cosine is at least
  `MIN_DOCUMENT_COSINE` (0.65, calibrated on a small sample for nomic-embed-text), the
  question refers to the documents, or it matches `_USER_CONTEXT` ("the final project",
  "the instructor"), or it names an uploaded file (`mentions_document`, any case, with or
  without extension). These code rules decide first (`clearly_documents` in `src/app.py`).
- Hybrid routing (first version; the user may change the split): when the code rules do not
  route to documents and summaries exist, `route_with_summaries` asks Qwen once, with every
  document's title and summary, whether the question needs the documents (JSON boolean,
  temperature 0). Malformed decisions are operational errors. Without documents or summaries
  the answer is general. Earlier probes without summaries misrouted 10-16 of 35-38 questions;
  with summaries the decision has context. The `mode` response field reports the route.
- Summaries: on upload and on every (re)index, `KnowledgeBase.index(path, summary_model)`
  stores a title and three-to-five-sentence summary in the `summaries` table, keyed by file ID
  and fingerprint (stale ones are ignored). Long documents are summarized in up to eight evenly
  spaced 24,000-character parts, then combined. A failed summary is logged and leaves the
  document indexed; reindexing retries it. Deleting a document deletes its summary. At startup a
  background thread runs `fill_missing_summaries`, summarizing indexed documents that lack a current
  summary from their stored passages (no re-embedding).
- Follow-ups (`route_documents`, text and voice): when the question does not route to documents in
  code, retrieval retries with context prepended: the file list after a `library` answer, or the
  previous user question after a `documents` answer. Assistant history messages carry `mode`.
  Only then does the summary router run on the question alone.
- General replies (`general_answer`, `VOICE_PROMPT`) include `NO_DOCUMENTS`, telling Qwen it cannot
  see document contents and must not guess them.
- Fact checks (`mode: web`): a whole-message doubt ("is that right?", "that's wrong") or a
  near-repeat of an earlier user question (content-word Jaccard >= 0.6) searches online for
  that question, unless it routes to the documents. Wikipedia goes first, using keywords and
  keeping only articles with an on-topic title. DuckDuckGo (`ddgs`) is the fallback. Only the
  question leaves the machine. Both services failing is an operational error (503); no results
  gives a plain "found nothing" answer without a model call. Web sources carry `url`, `name`,
  `location` and `quote`, and no `file_id`. Voice mode does not search.
- Qwen first selects passages likely to answer the question, then writes
  plain-language answers using them as untrusted reference material. It may summarize,
  explain, handle spelling
  mistakes and answer the available part of a question while stating what is missing.
  The user explicitly requested this simpler, less restrictive architecture.
  Do not restore the old exact-quote selector, all-keyword gate or literal fallback.
- `src/documents.py` handles extraction/chunking; `src/ollama_client.py` handles
  local calls/embeddings; `src/rag.py` handles indexing/retrieval;
  `src/answering.py` handles generated answers. Existing indexes stay compatible.
- Use temperature zero, a 16,384-token context and a 2,048-token output limit for
  both evidence selection and answer generation. Ollama calls wait without a
  fixed timeout. Validate JSON shape and resolve answer citations from passage overlap;
  malformed output is an operational error, never a not-found answer.
- Resolve file IDs, locations and source text on the server. The source `quote`
  field now contains the retrieved passage, not a model-selected quotation.
- An empty library gets a general answer. Document-routed topics the passages do not
  cover can receive an explanation with no citations; no exact not-found wording is required.
- The assistant persona is Yapperton (`answering.PERSONA`), prefixed to every answer-writing
  prompt (not the passage selector). Name and model-identity questions are answered without a
  model call and state the configured model name.
  Requests for abilities the app lacks (reminders, alarms, calendar, email, file management)
  are declined in code by `identity_response`: the small model ignores prompt-only refusals.
  Questions about what is uploaded are answered from the real file list (`mode: library`).
  If evidence selection returns no passages, answer with `NOT_FOUND`; do not fall
  back to the nearest unrelated passage.
- Generated prose is not quote-validated. Valid citations do not prove that every
  claim is supported; the small model can invent, misunderstand or omit facts.
  Keep source excerpts inspectable and do not claim hallucination prevention.
- Numerical claims absent from cited text are replaced with a limitation message
  and related passages. This check ignores numbered-list markers and normalizes
  commas, but does not prove number relevance or support computed figures.
- Treat uploaded text as untrusted data, never instructions. Render source/model
  text through safe DOM text APIs, never unescaped HTML.
- Network, model and index failures are operational errors, not evidence absence.

## Quizzes

- Requests are recognized in code (`is_quiz_request`), after identity and library questions
  and before retrieval, in text and voice. Topic and count (default 5, max 10) are parsed
  from the request. No topic, or a named file, samples evenly spaced passages
  (`KnowledgeBase.passages`); a topic uses retrieval plus `needs_documents`, and uncovered
  topics get an explanation instead of a quiz.
- `make_quiz` writes one question per call around one sentence of a passage
  (`focus_points`), temperature 0.3 so repeated quizzes differ (a deliberate exception to the
  temperature-zero rule). The code shuffles options and drops aggregate options
  ("all of the above"), NOT/EXCEPT questions, duplicate options, figures absent from the
  passage and reworded repeats. Qwen then lists every option the passage supports; only
  questions where that is exactly the intended answer are kept. Rejected questions still go
  in `already_asked`. Slow by design (the user accepted this); never claim answer keys are
  guaranteed correct. No usable questions is an operational error (502 / error event).
- Do not reject wrong answers merely because the passage mentions them: distractors from the
  passage were good questions in testing; the self-check handles ambiguity.
- Question writing uses `QUESTION_GUIDE` (exam-style: scenarios, purpose, cause, distinctions;
  standalone wording; parallel options; teaching explanations) with Qwen thinking on
  (`QUIZ_THINKING`). Measured on a lecture PDF: thinking kept 5 of 5 in ~11 minutes; without it
  1 of 15 in ~3.5 minutes, and that one copied the prompt's example. Code also drops questions
  that mention the source text (`_META`), whose answer words are already in the question
  (`_gives_away`, 5-letter stems), whose correct answer is much longer than the distractors,
  or that copy `EXAMPLE_QUESTION`. The input keys are `study_material` and `key_idea` so the
  model has no "passage"/"focus" vocabulary to leak.
- Voice speaks `QUIZ_WAIT` first, then sends the `quiz` event and announces it. Answering by
  voice is not implemented yet; options are clicked.

## Voice mode

- Voice is the main interface. Optional setup on macOS and Windows: `make voice-install` and
  `make voice-models` (or `scripts/tasks.py`). Imports stay lazy, so the app and tests run
  without speech packages; when `/api/voice/status` reports unavailable, the voice screen shows
  the reason and Chat & documents still works. Opening Chat & documents ends a voice session.
- Silero (browser), `whisper-large-v3-turbo`, Qwen, then Kokoro (`speech.VOICE`). `speech.MLX`
  (Apple silicon) uses mlx-whisper/mlx-audio; otherwise faster-whisper (CPU, int8) and
  kokoro-onnx (`kokoro-v1.0.onnx`, `voices-v1.0.bin`) in `.models/`. `scripts/tasks.py` uses the
  same platform check. Fully local after setup; Hugging Face offline at runtime. Audio is never saved.
- All speech work must run on the single `speech.py` worker thread: MLX streams are per-thread.
- Voice routes like text chat (identity, library, retrieval, `is_document_question`, then
  `select_evidence`), without web search. Document answers stream as plain text from the
  selected passages (`voice_document_reply`, temperature 0); each sentence is checked with
  `unsupported_numbers` and replaced by `UNCONFIRMED_FIGURE` when needed. A `sources` event
  precedes `done`, which carries `mode`. Follow-up routing is shared with text chat (`route_documents`). Library answers are spoken as one sentence. Warmup and voice retrieval keep the
  embedding model loaded with `VOICE_KEEP_ALIVE`.
- Deliberate exceptions to the text chat rules: voice streams by sentence; general replies use
  temperature 0.7; all voice replies have a 256-token limit. `num_ctx` stays 16,384
  so Ollama does not reload the model when switching between text and voice.
- If no sentence is playing 1.2 s after transcription (`FILLER_DELAY_MS`), a random filler from `speech.FILLERS` plays (rendered once at warmup);
  a second one plays 4 s later (`SECOND_FILLER_MS`) if no sentence has arrived.
  Fillers are never captioned or added to history. The user can mute the mic (button or M);
  a muted session stays in the `muted` state until unmuted.
- The mic is off while replying (no barge-in). End of speech is a 1 s pause. Skip keeps only
  the sentences already heard in history; if none were heard the user turn is dropped.

## API contracts

- `GET /`: application interface.
- `GET /api/files`: `{files: [{id, name, size, indexed}]}`.
- `POST /api/files`: multipart `file`; returns `{file: ...}` with HTTP 201 after
  successful extraction and indexing, or HTTP 200 with the existing document and
  `duplicate: true` when the content hash matches.
- `GET /api/files/<file_id>`: original document as an attachment.
- `GET /api/files/<file_id>/preview`: PDF served inline for the preview modal; other
  file types return 404.
- `DELETE /api/files/<file_id>`: removes the original document and its SQLite index entry.
- `POST /api/files/index`: reindex supported files; returns per-file `results`.
  Inspect each result's `indexed` and optional `error`, even when HTTP is 200.
- `POST /api/chat`: nonempty `messages` array with user/assistant text roles,
  ending with a user message. Returns `message`, `mode` (`documents`, `general`, `library`, `web`
  or `quiz`) and `sources` containing file ID, filename, location and source passage. Quiz
  requests add `quiz` (`{title, questions: [{question, options, answer, explanation, source}]}`
  or `null` with the reason in `message`).

- `GET /api/voice/status`: `{available, reason}`. `POST /api/voice/warmup`: 204 when ready.
- `GET /api/voice/fillers`: `{fillers: [{text, audio}]}` with base64 WAV; 503 when speech is unavailable.
- `POST /api/voice/transcribe`: 16 kHz, 16-bit mono WAV, 4 MiB limit; returns `{text}`, empty for noise.
- `POST /api/voice/reply`: `{messages}`; NDJSON events `sentence` (`text`, base64 WAV `audio`),
  `sources` (document answers), `quiz` (quiz requests), `done` (`mode`) or `error` (`message`). Failures are events
  because HTTP 200 is already sent.

History lives only in browser memory. General answers use it; retrieval uses the
latest user message, plus follow-up context after file-list and document answers. All indexed
files are shared within this local workspace; no authentication, user isolation,
text chat streaming, OCR or persistent server-side chat history exists.

## Style and verification

Use four-space Python and two-space frontend indentation, descriptive names and
small modules. Follow existing Flask/plain-JavaScript patterns; do not introduce
an additional framework without a concrete need.

Use standard-library unittest and mock Ollama for automated tests. Cover normal
retrieval, changed/deleted files, extraction failures, unsupported questions,
malformed answers and invalid source references when changing RAG behavior.
Tests create temporary documents and SQLite indexes inside `tests/` and clean
up their own files. Keep manual smoke-test fixtures inside `.tmp/` and never
index or delete the user's documents for verification without authorization.

The answer tests cover paraphrased and partial answers, malformed output and invalid
source IDs. Extraction, changed/deleted-file and index-atomicity tests remain.
Diagnostics are read-only; saved reports contain user text and belong under `.tmp/`.
Do not reindex or delete user documents for verification without authorization.
Report actual checks and avoid repeated expensive model calls when focused checks suffice.

## Security, documentation and change delivery

Keep credentials, `.env` files, uploads, embeddings, `.venv` and `.tmp` out of
version control. `.env.example` may contain placeholders only. Do not expose this
single-user development server beyond localhost without an explicit task.

Keep README.md synchronized with actual models, commands, endpoints, storage and
RAG limitations. Update this file when architecture or working conventions change.
Use concise imperative commit subjects. Git is initialized locally on `main`;
check the remote history before the first push and never overwrite it by force.
PRs should explain
behavior changes, validation and limitations, with screenshots for visible UI
changes when a PR is requested.
