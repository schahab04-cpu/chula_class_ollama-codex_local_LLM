# Repository Guidelines

## Scope and working directory

Work only inside `C:\Users\schah\codex-ollama` (`~/codex-ollama`). Run commands
from this root. Keep source, dependencies, logs, scratch files and test fixtures
inside this project. Use `.venv\Scripts\python.exe`; do not switch to Anaconda,
other Python environments, or another project directory. The user prefers small,
practical changes and quick verification over unnecessary tooling or refactoring.

## Current application

This is an implemented local Flask application with plain HTML/CSS/JavaScript and
document-based, extractive RAG. Do not treat the workspace as an empty scaffold.

- `src/app.py`: Flask routes, upload validation, error handling and local startup.
- `app.py`: root launcher importing `src.app.main`; start with `python3 app.py`
  in an environment with dependencies, or `.\.venv\Scripts\python.exe app.py` on Windows.
- `GIT_GUIDE.md`: first-upload steps and a short Git explanation. `origin` points
  to `https://github.com/schahab04-cpu/chula_class_ollama-codex_local_LLM.git`.
- `src/rag.py`: document extraction, chunking, Ollama embeddings, hybrid SQLite retrieval,
  structured quote selection and server-side evidence checks.
- `src/diagnose.py`: read-only upload/index audits and optional live retrieval/evidence probes.
  Run with `.\.venv\Scripts\python.exe -B -m src.diagnose`.
- `src/templates/index.html`: Chat and Filemanager interface.
- `src/static/chat.js`: chat requests, history and source download links.
- `src/static/files.js`: uploads, readiness status and manual indexing.
- `src/static/views.js`: clickable view switching; Chat opens by default and
  Filemanager stays hidden until selected. Switching preserves browser state.
- `src/static/style.css`: responsive layout and view visibility.
- `tests/test_app.py`, `tests/test_files.py`, `tests/test_rag.py`: unittest coverage.
- `requirements.txt`: Flask, pypdf and python-docx dependency ranges.
- `uploads/`: original documents and `knowledge.sqlite3` (ignored by Git).
- `.venv/`: project Python environment (ignored).
- `.tmp/`: upload scratch files, local installation scratch files and server logs
  when launched with output redirection (ignored).

## Runtime and commands

Python 3.10+ is required. Ollama serves locally at `http://localhost:11434`.
Use `gemma3:1b` for quote selection and **`nomic-embed-text:latest` for embeddings**.
The user explicitly requested nomic-embed-text; preserve that choice unless asked
to change it. Models are managed by the existing Ollama installation; do not
silently replace models or relocate its storage.

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
ollama pull gemma3:1b
ollama pull nomic-embed-text

# Keep Ollama running, then start the application.
.\.venv\Scripts\python.exe app.py

# Automated verification; no running Ollama required.
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

Open `http://127.0.0.1:5000`. Use `app.py --port 5001` to explicitly choose
an alternate localhost port when needed; the default is 5000.
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
- Uploads index synchronously; failed uploads are removed. Older files can be
  indexed with **Index documents**. Supported unindexed or changed files block
  chat with an indexing error; deleted files are excluded from retrieval.
- Retrieve up to eight passages with hybrid cosine/normalized keyword rankings,
  reserving four candidates per ranking and ordering by reciprocal rank fusion.
  No hard cosine cutoff; ranking is not calibrated confidence. Search scans
  vectors in Python and is intended for small local collections.
- Gemma selects up to four exact quotations (including slide fragments/bullets)
  using structured JSON with per-source enums of whole passages and exact sentences.
  Definition prompts distinguish explanations from headings and component names. Use temperature
  zero, an 8,192-token context and a 1,024-token output limit. Each Ollama call has
  a 120-second timeout. Do not display free-form generated factual prose.
- Validate source IDs and exact quote membership. The conservative lexical gate
  requires normalized question terms to appear in the **selected source passages**,
  not necessarily in the short quotations themselves. Preserve that distinction.
- On a valid empty model evidence array, recover at most one whole retrieved
  passage verbatim when the question has at least two normalized non-stopword
  terms and all occur in that passage. Keep exact quote checks and the passage
  gate; never recover malformed JSON, fabricated quotes or invalid references.
  Literal term coverage does not establish relevance or completeness.
- Missing evidence or invalid selection returns exactly:
  `I couldn't find that information in the uploaded documents.`
- Network, model and index failures are operational errors, not evidence absence.
- Treat uploaded text as untrusted data, not instructions. Render document/model
  text through safe DOM text APIs, never through unescaped HTML.

Quote validation prevents invented answer text; it does not guarantee relevance,
completeness or source truth. The lexical gate can reject valid paraphrases and
still allow irrelevant quotations from related passages. Never claim perfect
hallucination prevention. Preserve these limitations in user documentation.

## API contracts

- `GET /`: application interface.
- `GET /api/files`: `{files: [{id, name, size, indexed}]}`.
- `POST /api/files`: multipart `file`; returns `{file: ...}` with HTTP 201 after
  successful extraction and indexing.
- `GET /api/files/<file_id>`: original document as an attachment.
- `POST /api/files/index`: reindex supported files; returns per-file `results`.
  Inspect each result's `indexed` and optional `error`, even when HTTP is 200.
- `POST /api/chat`: nonempty `messages` array with user/assistant text roles,
  ending with a user message. Returns `message` and `sources` containing file ID,
  filename, location and quotation.

History lives only in browser memory. Retrieval uses the latest user message,
not earlier turns; follow-up questions must restate their topic. All indexed
files are shared within this local workspace; no authentication, user isolation,
streaming, OCR, deletion UI or persistent server-side chat history exists.

## Style and verification

Use four-space Python and two-space frontend indentation, descriptive names and
small modules. Follow existing Flask/plain-JavaScript patterns; do not introduce
an additional framework without a concrete need.

Use standard-library unittest and mock Ollama for automated tests. Cover normal
retrieval, changed/deleted files, extraction failures, unsupported questions,
fabricated quotes and invalid source references when changing RAG behavior.
Tests create temporary documents and SQLite indexes inside `tests/` and clean
up their own files. Keep manual smoke-test fixtures inside `.tmp/` and never
index or delete the user's documents for verification without authorization.

Exact nonempty quotations may be short names, acronyms or single-digit numbers;
do not impose a minimum quotation length beyond nonempty text. The selected
source-passage lexical gate still applies.

The updated automated run passed 28 tests. ResourceWarnings still occurred for
multipart scratch handles. Live checks verified a page-5 lecture citation through
the updated server, and isolated real-Ollama upload/index/list/download plus
supported date and unsupported budget questions. Empty Gemma output on the date
question was recovered by the literal-passage fallback. Browser automation was
unavailable, so visual browser testing was not performed. The audit confirmed 11 stored normalized 768-dimensional
vectors matching all 11 extracted page passages. Images are not indexed, so text
extraction alone cannot establish completeness. Diagnostic reports contain user
text; keep saved output under `.tmp/`. Do not reindex documents just to audit them.
The constrained selector was verified with the exact reported question `what is RAG`
through the running port-5000 server, returning a page-5 quotation. Isolated real
Ollama upload/index/list/download, supported date and unsupported budget checks
also passed. The user's documents were not reindexed or modified.
Report what was actually checked and avoid repeated expensive model calls when
focused tests suffice.

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
