# Local Ollama chat with documents

Ask anything for a normal answer, or upload your notes and ask about them to get
plain-language answers with file/page references. Runs locally with Flask, **qwen3:1.7b** and **nomic-embed-text:latest**.

## Run with Make (macOS and Windows)

The Makefile provides the same project commands on macOS and Windows. On
Windows, install GNU Make (for example, through Git Bash or Chocolatey) and
ensure `py -3` is available. On macOS, use the system `python3` and Make.
Run commands from the repository root:

```sh
make setup     # create .venv and .tmp
make install   # install requirements into .venv
make models    # pull both models using the existing Ollama installation
make run       # start the app at http://127.0.0.1:5050
make test      # run the unittest suite
make diagnose  # run read-only diagnostics
```

Start Ollama before `make run`. `make models` is optional when both models are
already installed. Targets can be run individually; run `make setup` before
install, run, test or diagnose.

## Run directly on Windows

The existing PowerShell workflow remains available. From the project folder,
with Ollama running:

```powershell
# Only if the project environment is missing:
python -m venv .venv

# First setup or dependency changes:
New-Item -ItemType Directory -Force .tmp | Out-Null
$env:TEMP = Join-Path (Get-Location) '.tmp'
$env:TMP = $env:TEMP
.\.venv\Scripts\python.exe -m pip install --no-cache-dir -r requirements.txt

# Pull only if absent from `ollama list`:
ollama pull qwen3:1.7b
ollama pull nomic-embed-text

.\.venv\Scripts\python.exe app.py
```

Always open http://127.0.0.1:5050. The app uses this fixed address only.
Start it with `.\.venv\Scripts\python.exe app.py` from this project folder.
Restart Flask after Python changes and reload the browser after UI changes.
Python 3.10+ required.
No app environment variables are required; TEMP/TMP only control scratch files.

## Use

1. Drop or choose one or more PDF, DOCX, TXT or MD files in the panel beside chat.
   Uploads are indexed before they show **Ready for questions**. Use × beside a
   document to remove its original file and index entry. Uploading a file with the
   same content as an existing document does nothing, even under another name.
2. Ask in the chat panel. Questions that match your documents get a document answer
   with sources. Other questions get a general answer, labelled as not from your
   documents. Everyday wording and spelling mistakes are allowed; answers have no
   exact-keyword acceptance gate.
3. Expand **View source text** to inspect cited passages. Click a PDF's name in the
   Documents panel to preview it in a modal; other files download when clicked, as do
   source links in chat.

Questions asking which model powers the app are answered from its configured model
name, and questions like "What files do you have access to?" from the uploaded file list. When evidence selection finds no passage for a document question, the app says
it could not find that information instead of using the nearest unrelated passage.

Answers can explain, summarize, and cover the available part of a broader question,
stating what is missing. The old exact-quotation selector, all-keywords gate and
literal-match fallback have been removed. Existing files/indexes stay compatible;
you do not need to upload or reindex them to use the new answering behavior.
Use **Index documents** for changed/unindexed files and inspect per-file failures.

## Structure

- `src/documents.py`: PDF pages, DOCX body paragraphs/tables, UTF-8 TXT/MD extraction.
  Whitespace normalization and passages up to 1,000 characters with roughly
  150-character overlap; page/block/paragraph references are preserved.
- `src/ollama_client.py`: local Ollama transport and normalized Nomic embeddings,
  batches of 16 with search_document/search_query prefixes and truncation disabled.
- `src/rag.py`: fingerprints, model tags, passages and vectors persisted in
  `uploads/knowledge.sqlite3`. Hybrid cosine/keyword reciprocal-rank search returns
  up to eight passages, reserving four from each ranking.
- `src/answering.py`: Routes to documents when the best passage's cosine is at least
  0.65, the question refers to the documents (for example "the slides" or "session 8"),
  or it depends on the user's own context (for example "the final project" or "the
  instructor"); otherwise answers generally. For document answers, Qwen first filters retrieved passages for direct evidence,
  then writes an explanation from the selected passages. The server chooses citations
  by matching answer terms to those passages; this reduces mismatched references but
  does not prove every claim is supported.
- `src/app.py`: Flask routes and localhost startup; root `app.py` launches it.
- `src/templates/`, `src/static/`: plain HTML/CSS/JavaScript interface.
- `src/diagnose.py`: read-only extraction/index audits and optional live queries.

## Limits

Routing uses a threshold and fixed phrases tuned on a small sample of questions, so
questions outside them can take the wrong route: "And what about Germany?" scored 0.651 against the
lecture index and got a document answer. Answers are generated prose after a separate local evidence-selection pass. Citations
are selected by answer-to-passage word overlap, which can still miss paraphrased
evidence and does **not** validate every generated claim. The small model can
misunderstand, omit information or invent facts. Inspect citations. Ranking is not confidence;
retrieval is a Python vector scan intended for small local collections.
Numerical claims absent from the cited text are replaced with a limitation message
and related passages. This also means calculated figures are not supported; this
basic check cannot validate non-numerical claims or prove that a number is relevant.

PDF images/diagrams and DOCX headers, footers and text boxes are not indexed.
Scans need OCR before upload. Encrypted, empty, unreadable and binary files are
rejected. Limits: 500 PDF pages, two million extracted characters, 1,000 passages
per file, 50 MiB expanded DOCX, 20 MiB upload requests including multipart overhead.

All indexed files are shared locally. History is browser memory only and clears on
reload. General answers use the conversation history, but each document search uses
only the latest question: restate the topic in follow-ups.
No authentication, OCR, streaming or persistent chat history.
Keep the server on localhost. Documents are sent only to local Ollama on port 11434.

## Troubleshooting and verification

- Connection/model errors: start Ollama and check both models with `ollama list`.
- Missing information: expand cited text. The answer may be in an image or absent
  from retrieved passages. Ask with an explicit topic.
- Changed/unindexed files: use **Index documents** and check each result.
- Slow requests: chat shows a spinner and waits for Ollama without a fixed timeout.
  Large models, long PDFs and slower hardware can make answers take several minutes.
- Invalid model JSON: retry; this is an operational error, not evidence absence.
- Port occupied: check whether this app is already open at http://127.0.0.1:5050.
  Stop the previous instance before starting an updated version. There is no
  alternate port; do not stop unrelated processes.

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -B -m src.diagnose
.\.venv\Scripts\python.exe -B -m src.diagnose --question "Explain prompt engineering" --answer
```

Tests mock Ollama and clean up temporary collections inside `tests/`. Diagnostics
do not reindex. Saved reports contain document text: keep them under ignored `.tmp/`.
If Node is installed, `node --check src/static/chat.js` checks syntax without packages.

## API and Git

- `GET /`: interface.
- `GET /api/files`: `{files: [{id, name, size, indexed}]}`.
- `POST /api/files`: multipart `file`; extraction/indexing before HTTP 201. A file
  whose SHA-256 matches an existing document returns HTTP 200 with that document and
  `duplicate: true`, and nothing is saved or indexed.
- `GET /api/files/<id>`: original attachment.
- `GET /api/files/<id>/preview`: PDF served inline for the preview modal; 404 for other files.
- `DELETE /api/files/<id>`: remove the original file and its index entry.
- `POST /api/files/index`: per-file results; HTTP 200 may contain indexing failures.
- `POST /api/chat`: `{messages: [{role: "user", content: "question"}]}`;
  returns `message`, `mode` (`documents`, `general` or `library`) and `sources` with file_id,
  name, location and quote (the original passage, not the generated answer). Latest question limit: 4,000
  characters; non-upload request limit: 1 MiB.

Failed uploads are removed. Changed/unindexed supported files block chat; deleted
files are excluded. Reindex after replacing the embedding model behind its tag.

Each document's SHA-256 is saved beside it in `uploads/` as `<file id>.sha256`.

Uploads, SQLite, embeddings, model weights, `.venv`, `.tmp`, logs and secrets are
ignored by Git. See [GIT_GUIDE.md](GIT_GUIDE.md) and [AGENTS.md](AGENTS.md).
