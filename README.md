# Local Ollama document chat

Upload your notes, ask questions, and get plain-language answers with file/page
references. Runs locally with Flask, **gemma3:1b** and **nomic-embed-text:latest**.

## Run

From `C:\Users\schah\codex-ollama` in PowerShell, with Ollama running:

```powershell
# Only if the project environment is missing:
python -m venv .venv

# First setup or dependency changes:
New-Item -ItemType Directory -Force .tmp | Out-Null
$env:TEMP = Join-Path (Get-Location) '.tmp'
$env:TMP = $env:TEMP
.\.venv\Scripts\python.exe -m pip install --no-cache-dir -r requirements.txt

# Pull only if absent from `ollama list`:
ollama pull gemma3:1b
ollama pull nomic-embed-text

.\.venv\Scripts\python.exe app.py
```

Always open http://127.0.0.1:5000. The app uses this fixed address only.
Start it with `.\.venv\Scripts\python.exe app.py` from this project folder.
Restart Flask after Python changes and reload the browser after UI changes.
Python 3.10+ required.
No app environment variables are required; TEMP/TMP only control scratch files.

## Use

1. Open **Filemanager**, upload PDF, DOCX, TXT or MD files under 20 MiB, and wait
   for **Ready for questions**.
2. Open **Chat** and ask about the contents. Everyday wording and spelling
   mistakes are allowed; answers have no exact-keyword acceptance gate.
3. Expand **View source text** to inspect cited passages. Click filenames to
   download original files.

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
  up to eight passages, reserving four from each ranking, without a hard cosine cutoff.
- `src/answering.py`: Gemma writes a concise answer and source IDs via a small JSON
  schema. The server validates IDs and resolves the original passages/filenames.
- `src/app.py`: Flask routes and localhost startup; root `app.py` launches it.
- `src/templates/`, `src/static/`: plain HTML/CSS/JavaScript interface.
- `src/diagnose.py`: read-only extraction/index audits and optional live queries.

## Limits

Answers are generated prose. Source IDs and source excerpts are checked, but this
does **not** validate every generated claim. The small model can misunderstand,
omit information or invent facts. Inspect citations. Ranking is not confidence;
retrieval is a Python vector scan intended for small local collections.
Numerical claims absent from the cited text are replaced with a limitation message
and related passages. This also means calculated figures are not supported; this
basic check cannot validate non-numerical claims or prove that a number is relevant.

PDF images/diagrams and DOCX headers, footers and text boxes are not indexed.
Scans need OCR before upload. Encrypted, empty, unreadable and binary files are
rejected. Limits: 500 PDF pages, two million extracted characters, 1,000 passages
per file, 50 MiB expanded DOCX, 20 MiB upload requests including multipart overhead.

All indexed files are shared locally. History is browser memory only and clears on
reload. Each question is retrieved independently: restate the topic in follow-ups.
No authentication, deletion UI, OCR, streaming or persistent chat history.
Keep the server on localhost. Documents are sent only to local Ollama on port 11434.

## Troubleshooting and verification

- Connection/model errors: start Ollama and check both models with `ollama list`.
- Missing information: expand cited text. The answer may be in an image or absent
  from retrieved passages. Ask with an explicit topic.
- Changed/unindexed files: use **Index documents** and check each result.
- Slow requests: each Ollama call can take up to 120 seconds on local hardware.
- Invalid model JSON: retry; this is an operational error, not evidence absence.
- Port occupied: check whether this app is already open at http://127.0.0.1:5000.
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
- `POST /api/files`: multipart `file`; extraction/indexing before HTTP 201.
- `GET /api/files/<id>`: original attachment.
- `POST /api/files/index`: per-file results; HTTP 200 may contain indexing failures.
- `POST /api/chat`: `{messages: [{role: "user", content: "question"}]}`;
  returns `message` and `sources` with file_id, name, location and quote (the
  original passage, not the generated answer). Latest question limit: 4,000
  characters; non-upload request limit: 1 MiB.

Failed uploads are removed. Changed/unindexed supported files block chat; deleted
files are excluded. Reindex after replacing the embedding model behind its tag.

Uploads, SQLite, embeddings, model weights, `.venv`, `.tmp`, logs and secrets are
ignored by Git. See [GIT_GUIDE.md](GIT_GUIDE.md) and [AGENTS.md](AGENTS.md).
