# Local Ollama document chat

A local Flask app with separate clickable **Chat** and **Filemanager** views.
Chat opens by default; switching views preserves the current conversation.

Start from the project root with **`python3 app.py`** once your active Python
environment has the dependencies installed and Ollama is running. On Windows,
use **`.\.venv\Scripts\python.exe app.py`** to select this project's environment
explicitly. The launcher also accepts `--port 5001`.

## Setup and run

Use Python 3.10+ and Ollama. Keep all project work inside
`C:\Users\schah\codex-ollama` and use its own `.venv`.
Run these commands from the repository root in PowerShell:

```powershell
New-Item -ItemType Directory -Force .tmp | Out-Null
$env:TEMP = Join-Path (Get-Location) '.tmp'
$env:TMP = $env:TEMP
.\.venv\Scripts\python.exe -m pip install --no-cache-dir -r requirements.txt
ollama pull gemma3:1b
ollama pull nomic-embed-text
.\.venv\Scripts\python.exe app.py
```

If creating a new environment: `python -m venv .venv`.
If pip is missing: `.\.venv\Scripts\python.exe -m ensurepip`.
Keep the Ollama desktop app running, or run `ollama serve` in another terminal.
Open http://127.0.0.1:5000. Restart Flask and reload the page after code changes.
The app binds to localhost with debug disabled. No environment variables are required.
If port 5000 is occupied, choose another localhost port explicitly:
`.\.venv\Scripts\python.exe app.py --port 5001`, then open
http://127.0.0.1:5001. The default remains 5000.
Dependencies live in `.venv`; application upload scratch files live in `.tmp`.

On Linux or macOS, create and activate a local environment before installing:

```sh
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
ollama pull gemma3:1b
ollama pull nomic-embed-text
python3 app.py
```

## Project layout and GitHub

```text
app.py             Root startup command
src/app.py         Flask routes and server startup
src/rag.py         Extraction, embeddings, retrieval and quote validation
src/diagnose.py    Read-only document/index diagnostics
src/templates/    HTML interface
src/static/       JavaScript and CSS
tests/            Automated tests using mock Ollama responses
requirements.txt  Python dependencies
uploads/          Local documents and SQLite index (ignored)
.tmp/             Local scratch files and logs (ignored)
.venv/            Local Python environment (ignored)
```

GitHub repository: [chula_class_ollama-codex_local_LLM](https://github.com/schahab04-cpu/chula_class_ollama-codex_local_LLM).
See [GIT_GUIDE.md](GIT_GUIDE.md) for first-upload commands and a short explanation
of staging, commits, pushing and ignored files. `.gitattributes` keeps source
line endings consistent across operating systems. Documents, model weights,
embeddings and local secrets are excluded from Git.

## Documents and questions

1. Open **Filemanager** and upload PDF, DOCX, TXT or MD files (under 20 MiB).
2. Wait for extraction and embedding to finish. Ready files show **Ready for questions**.
3. For older uploads, click **Index documents**. Failures identify the affected file.
4. Open **Chat** and ask a specific question about the documents.
5. Answers contain verified quotations and numbered filename/location download links.

All indexed documents in this local workspace are searched. There is no per-user
separation or authentication; this is a single-user local application. Files and
embeddings stay local and are sent only to Ollama on localhost:11434.
History exists in browser memory and clears on reload or **New chat**. Each question
is retrieved independently; include the topic explicitly in follow-up questions.

## Retrieval and evidence behavior

`src/rag.py` extracts PDF pages, DOCX paragraphs/tables in document order, and
UTF-8 TXT/MD paragraphs. Scans require OCR before upload. Password-protected PDFs,
empty/broken files, and binary text are rejected. Limits: 500 PDF pages, two million
extracted characters, 1,000 passages per file and 50 MiB expanded DOCX size.
PDF images and DOCX headers, footers and text boxes are not indexed.

Overlapping passages of up to 1,000 characters prefer sentence/word boundaries and are embedded in batches with
`nomic-embed-text:latest`, using search_document/search_query prefixes. SQLite at
`uploads/knowledge.sqlite3` persists the vectors, text, locations and SHA-256 file
fingerprints. Chunks target 150 characters of overlap and are embedded in batches of 16.
Hybrid search combines cosine and normalized keyword rankings using reciprocal
ranks, reserving four candidates from each ranking and returning up to eight
passages. There is no hard cosine cutoff: low-scoring exact terminology can still
reach the quote selector. Ranking is not a confidence score. Search scans vectors in
Python, suitable for a small local collection. Large collections need a dedicated
vector index. Reindex after replacing an embedding model, including a changed
model behind the same tag. Modified files must be reindexed; missing files are
excluded from retrieval.

Gemma selects exact quotations, including slide bullets/fragments, with structured JSON at temperature zero.
Each request constrains the model to the retrieved passages or their exact sentences,
paired with the corresponding source IDs. Definition questions explicitly request
an explanation of the concept instead of a heading or a component name. The
server validates source IDs and exact quote membership before displaying anything.
Short answers such as names, acronyms and single-digit numbers are accepted when
they are exact nonempty quotations and pass the same source-passage checks.
A conservative relevance gate also requires all non-stopword question terms
(with basic suffix normalization) to occur in the source passages containing the
selected quotations, rather than in the quotations themselves. This allows short
answers such as a date while still checking the surrounding topic. This can
reject valid paraphrases; use wording from your documents if a question abstains.
If Gemma returns a valid empty evidence array, a literal-match fallback may quote
one entire retrieved passage only when at least two normalized question terms
exist and every term occurs in that passage. This keeps exact, specific matches
usable when the small selector abstains. It never repairs fabricated quotations,
invalid references or malformed model JSON. Literal term coverage does not prove
that the passage answers the question; check the cited context.
No generated factual prose is displayed. Missing evidence, invalid references,
fabricated quotations or malformed selection JSON produce:
**I couldn't find that information in the uploaded documents.**

This is deliberately extractive RAG. It does not synthesize or calculate new facts.
Quote validation prevents invented answer text but cannot prove that a selected
quote answers the question or that the document itself is correct. Retrieval can
miss relevant information, and the small 1B model can select irrelevant evidence.
Use the citations to inspect context. There is no guarantee of perfect relevance.
Ollama/network/index failures appear as errors instead of false not-found answers.
If any supported document is unindexed or has changed, chat asks you to index it
before answering; it does not silently omit that document.
Uploads that fail extraction or embedding are removed so users can retry.

## Troubleshooting

- **Cannot reach Ollama:** start the Ollama desktop app or `ollama serve` and check
  that both models appear in `ollama list`.
- **Upload is slow:** extraction and embedding finish before the upload succeeds.
  Each Ollama call can take up to 120 seconds; large files need multiple calls.
- **Some documents are not indexed:** open Filemanager, click **Index documents**,
  and check for per-file failures. Reindex after changing the embedding model.
- **Not found despite relevant content:** run the diagnostics below to distinguish
  missing extraction, stale storage, retrieval ranking and evidence rejection.
  The lexical gate and small model can still miss valid paraphrases. Include the
  topic in each follow-up question.
- **Scanned PDF:** run OCR before uploading. OCR is not included in this app.
- **Changes do not appear:** restart Flask for Python changes and reload the page
  for frontend changes. Automatic reload is disabled.
- **Port 5000 is occupied:** check whether this project's server is already running;
  do not stop unrelated applications. You can also start with `--port 5001`.
- **Background server logs:** when started with the local output redirection used
  during setup, check `.tmp/server.log` and `.tmp/server-error.log`. A normal
  foreground launch prints logs to its terminal.

## API and checks

- `GET /api/files`: list uploaded files and indexing readiness.
- `POST /api/files`: multipart `file`, extract and index before returning 201.
- `GET /api/files/<id>`: download an original document.
- `POST /api/files/index`: reindex supported uploads, report each result.
- `POST /api/chat`: `{ "messages": [{ "role": "user", "content": "question" }] }`.
  Returns `message` and `sources`; latest user question is limited to 4,000 characters.

Run tests with the project's own Python:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

Tests mock Ollama, and create temporary documents/indexes inside `tests/`.
`app.py` starts the server; `src/app.py` handles HTTP, `src/rag.py` retrieval, `src/templates/` HTML and
`src/static/` plain JavaScript/CSS. Four-space Python and two-space frontend indentation.
No build or lint step is configured. Uploads, `.tmp`, `.venv` and credentials are ignored.
The updated automated run passed 28 tests, including short-answer validation, low-cosine lexical retrieval,
sentence boundaries, failed-index atomicity, read-only auditing and evidence guards.
Temporary multipart handles still emitted ResourceWarnings. Live checks verified
a lecture answer with a page-5 citation through the running server, plus real
Ollama upload/extraction/embedding/storage, file listing/download, a supported
date question and an unsupported budget question in an isolated temporary
collection. The literal-match fallback recovered the date when Gemma abstained.
Browser automation was unavailable, so visual browser testing was not performed.
The latest selector fix was also verified through the running server with the
reported question **what is RAG**, returning the lecture's page-5 explanation.
An isolated live upload/index/list/download check, supported date question and
unsupported budget question passed with the updated selector. Existing user
documents were audited without reindexing or modification.

## Diagnose extraction and retrieval

From the project root (no document modifications or reindexing):

```powershell
.\.venv\Scripts\python.exe -B -m src.diagnose
.\.venv\Scripts\python.exe -B -m src.diagnose --question "What is non-parametric memory?"
.\.venv\Scripts\python.exe -B -m src.diagnose --question "What is non-parametric memory?" --answer
```

The first command audits every supported upload using a read-only SQLite connection.
It reports chunk counts, locations, fingerprints, model tags, dimensions, norms,
and whether fresh extraction matches stored passages. Character totals count chunk
text, including overlap; PDF per-page counts show the underlying extraction.
PDF image and sparse-page warnings flag possible omissions. Extraction success
cannot prove completeness: diagrams/images are not interpreted or OCRed.
`--question` embeds a query against the existing index and reports ranking scores,
full retrieved context and missing question terms; `--answer` also calls Gemma.
These reports contain document text: keep them under ignored `.tmp/` if saved.
Server/diagnostic INFO logs distinguish no candidates, empty model selections,
invalid quotations and lexical rejection without logging document text.
New boundary-aware chunks take effect on the next upload or manual reindex;
existing indexes remain searchable without modifying the user's documents.

Contributor and agent instructions are in [AGENTS.md](AGENTS.md).

Ollama references: [embeddings](https://docs.ollama.com/api/embed),
[structured output](https://docs.ollama.com/capabilities/structured-outputs),
[Nomic prefixes](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5).
