# Yapperton: local voice assistant with documents

Talk to Yapperton, a local high-tech assistant persona (Qwen underneath), who answers aloud, from general knowledge or from the
notes you upload (with file/page references in the transcript). Text chat and the
document manager are one click away. Runs locally on macOS and Windows with Flask,
**qwen3.5:9b** and **nomic-embed-text:latest**.

## Run with Make (macOS and Windows)

The Makefile provides the same project commands on macOS and Windows. On
Windows, install GNU Make (for example, through Git Bash or Chocolatey) and
ensure `py -3` is available. On macOS, use the system `python3` and Make; if the system Python is older than
3.10, create the environment with a newer one, for example
`/opt/homebrew/bin/python3.12 -m venv .venv`.
Run commands from the repository root:

```sh
make setup     # create .venv and .tmp
make install   # install requirements into .venv
make models    # pull both models using the existing Ollama installation
make run       # start the app at http://127.0.0.1:5050
make test      # run the unittest suite
make diagnose  # run read-only diagnostics
make voice-install  # install voice mode's speech packages for this computer
make voice-models   # download its speech models to .models/ (about 1.9 GB)
```

`make run` starts Ollama if it is not already running: the Ollama desktop app when
installed, otherwise `ollama serve` (its output goes to `.tmp/ollama.log`). Ollama keeps
running after the app stops. The startup log names any missing model with its
`ollama pull` command. `make models` is optional when both models are already installed. Targets can be run individually; run `make setup` before
install, run, test or diagnose.

## Run directly on Windows

The existing PowerShell workflow remains available. From the project folder
(the app starts Ollama itself if needed):

```powershell
# Only if the project environment is missing:
python -m venv .venv

# First setup or dependency changes:
New-Item -ItemType Directory -Force .tmp | Out-Null
$env:TEMP = Join-Path (Get-Location) '.tmp'
$env:TMP = $env:TEMP
.\.venv\Scripts\python.exe -m pip install --no-cache-dir -r requirements.txt

# Pull only if absent from `ollama list`:
ollama pull qwen3.5:9b
ollama pull nomic-embed-text

# Voice mode (once): speech packages and models. Needs Python 3.10-3.13.
.\.venv\Scripts\python.exe -m pip install --no-cache-dir -r requirements-voice.txt
.\.venv\Scripts\python.exe scripts\tasks.py voice-models

.\.venv\Scripts\python.exe app.py
```

Always open http://127.0.0.1:5050. The app uses this fixed address only.
Start it with `.\.venv\Scripts\python.exe app.py` from this project folder.
Restart Flask after Python changes and reload the browser after UI changes.
Python 3.10+ required.
No app environment variables are required; TEMP/TMP only control scratch files.

## Use

The page opens on the voice screen: press **Start talking** (or Space) and speak. Open
**Chat & documents** to type, upload files or inspect sources.

1. In **Chat & documents**, drop or choose one or more PDF, DOCX, TXT or MD files.
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

To fact-check a general answer, reply "Is that right?", "That's wrong", "Are you sure?"
or "check online", or ask nearly the same question again. The app then searches
Wikipedia for your earlier question, falling back to DuckDuckGo when Wikipedia has no
on-topic article, and Qwen answers from the results with links as sources. Only that
question leaves your computer. Fact checks of document answers stay with the documents,
and search results can be wrong too.

Answers can explain, summarize, and cover the available part of a broader question,
stating what is missing. The old exact-quotation selector, all-keywords gate and
literal-match fallback have been removed. Existing files/indexes stay compatible;
you do not need to upload or reindex them to use the new answering behavior.
Documents are read automatically: on upload, at startup, and before answering when a file
was added by hand, changed or never processed. While that happens (and while summaries are
written) Yapperton pauses: chat is disabled, voice turns the mic off and shows "Reading your
documents", and the server refuses questions. A file that cannot be read is listed with the
reason and skipped until it changes, so it never blocks the others.

Say or type "I want to upload a document" (or "can I add my notes?") to open an upload
box over the current screen; it uses the same upload as the Documents panel and closes
itself once the files are ready.

## Quizzes

Ask "quiz me", "quiz me on older adults", "make a 7 question quiz from Neutraceuticals.pdf"
or "give me practice questions on sweetness", typed or spoken. Yapperton writes a
multiple-choice quiz from your documents and shows it right away: in the chat, or on the
voice screen while you keep talking. Click an answer to see whether it was right, why, and
the source passage; a score follows. Default 5 questions, at most 10.

Quizzes are slow on purpose (several minutes for five questions; Qwen thinks through each
question as an exam writer would, testing understanding with short scenarios rather than word
matching, and questions that mention "the passage" or give their answer away are dropped): Qwen writes one question at a time
around a different sentence of a passage, the code drops questions with "all of the above",
NOT/EXCEPT wording, duplicate options, figures absent from the passage or repeats, and then
Qwen must name every option the passage supports; only questions where that is exactly the
intended answer are kept. Small documents can yield fewer questions than asked. This makes
wrong answer keys rarer, not impossible: check the source passage when an answer looks off.
Voice says it is writing the quiz first, so the wait is not silent.

## Voice mode

Voice is the main screen. After `make voice-install` and `make voice-models`, restart
the app and press **Start talking** (or Space) to talk hands-free. Until then the voice
screen explains the setup and **Chat & documents** works as usual. Chrome will ask for microphone access the first time. It listens
until you pause for about a second, then replies aloud. The microphone is off while
it speaks: press **Skip** or the spacebar to cut a reply short, and **End** or Esc to
stop. Opening **Chat & documents** also ends the voice session. Press **Mute** or M to turn your microphone off until you unmute. If the
answer takes more than about a second to start, it says a short random filler such as "Hmm." or "Okay, I get it."; fillers
are not captioned or kept in the conversation. Every spoken turn is also added to the
chat transcript, and document answers name their sources under the caption.

Voice mode routes like text chat: document questions are answered aloud from your
documents (retrieval and passage selection as in text chat, then a short streamed spoken
answer), "what documents do I have?" lists them, and everything else is general chat.
It never searches the web. Spoken sentences containing figures that are not in the
selected passages are replaced with "I can't confirm that figure from your documents."
Sources appear in the chat transcript after the turn. In voice and text, a follow-up that does
not route to the documents on its own ("and what's inside it?") is retried with context:
the file list after "what documents do I have?", or your previous question after a
document answer. Document answers can take a few seconds
longer to start; a second filler plays if nothing has been said after about five seconds.
Replies are short, and the model remembers only what you actually heard. Speech stays on this computer:
Silero detects speech in the browser, `whisper-large-v3-turbo` transcribes it and
Kokoro speaks, all from local files. Apple silicon Macs run both on the GPU with MLX.
Windows, Intel Macs and Linux run them on the CPU with faster-whisper (int8) and
kokoro-onnx; `requirements-voice.txt` and `make voice-models` pick the right set
automatically. Expect slower transcription on the CPU than with MLX. Audio is not written to disk.
Before setup, the voice screen shows what to install and the rest of the app is unaffected.

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
  instructor"), or it names an uploaded file. Otherwise, if the documents have summaries,
  Qwen reads every document's title and summary and decides whether the question needs
  them (one short extra call); if not, it answers generally. Summaries are written when a
  file is uploaded or reindexed; documents indexed earlier are summarized in the background when the app starts. For document answers, Qwen first filters retrieved passages for direct evidence,
  then writes an explanation from the selected passages. The server chooses citations
  by matching answer terms to those passages; this reduces mismatched references but
  does not prove every claim is supported.
- `src/web_search.py`: fact-check triggers and online search (Wikipedia, then
  DuckDuckGo through the `ddgs` package). The only code that reaches the internet.
- `src/speech.py`: voice mode's local transcription and synthesis on one worker thread
  (MLX on Apple silicon, faster-whisper/kokoro-onnx elsewhere), sentence splitting and
  markup cleanup. Models load from `.models/`.
- `src/ollama_service.py`: starts Ollama at launch when it is off and lists missing models.
- `src/app.py`: Flask routes and localhost startup; root `app.py` launches it.
- `src/templates/`, `src/static/`: plain HTML/CSS/JavaScript interface. `voice.js` runs
  the voice conversation, `wisp.js` draws its animated wisp, and `vendor/vad/` holds the
  pinned speech detection files.
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
No authentication, OCR or persistent chat history. Text chat does not stream; voice
replies stream by sentence.
Keep the server on localhost. Documents are sent only to local Ollama on port 11434;
fact checks send just the question to Wikipedia or DuckDuckGo.

## Troubleshooting and verification

- Connection/model errors: start Ollama and check both models with `ollama list`.
- Missing information: expand cited text. The answer may be in an image or absent
  from retrieved passages. Ask with an explicit topic.
- A file shows "Could not be read": its reason is listed (for example a scanned PDF);
  fix or replace the file and it is read again automatically.
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
  returns `message`, `mode` (`documents`, `general`, `library`, `web` or `quiz`) and `sources` with file_id,
  name, location and quote. Web sources carry `url` instead of `file_id` (the original passage, not the generated answer). Latest question limit: 4,000
  characters; non-upload request limit: 1 MiB. Quiz requests also return `quiz`:
  `{title, questions: [{question, options (4), answer (index), explanation, source}]}`, or
  `null` with an explanation in `message` when no quiz can be made.

- `GET /api/voice/status`: `{available, reason}`.
- `POST /api/voice/warmup`: load the speech models and Qwen; HTTP 204 when ready.
- `GET /api/voice/fillers`: `{fillers: [{text, audio}]}`, the thinking fillers as
  base64 WAV, rendered once during warmup.
- `POST /api/voice/transcribe`: 16 kHz, 16-bit mono WAV body, up to 4 MiB (about two
  minutes); returns `{text}`, empty when the audio held only noise.
- `POST /api/voice/reply`: `{messages}` as for chat (assistant messages may carry the
  `mode` of their answer); streams NDJSON events: `sentence` with `text` and base64 WAV
  `audio`, then `sources` (document answers only, same shape as chat sources) and `done`
  with `mode` (`documents`, `general`, `library` or `quiz`), or `error` with `message`.
  Quiz requests send a `quiz` event (same shape as chat's `quiz`) between two sentences.

Failed uploads are removed. Changed or unprocessed files are reindexed automatically before
answering; unreadable ones are skipped; deleted files are excluded. `POST /api/files/index`
still forces a full reindex (for example after replacing the embedding model behind its tag).
`GET /api/documents/status` returns `{busy, detail}`; while busy, `/api/chat` and
`/api/voice/reply` answer 409 with `busy: true`. Upload requests return `mode: "upload"`
(chat) or an `upload` event (voice).

Each document's SHA-256 is saved beside it in `uploads/` as `<file id>.sha256`.

Uploads, SQLite, embeddings, model weights, `.models`, `.venv`, `.tmp`, logs and secrets are
ignored by Git. See [GIT_GUIDE.md](GIT_GUIDE.md) and [AGENTS.md](AGENTS.md).
