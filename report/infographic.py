"""Yapperton infographic: one tall poster with the app's features, pipelines, models and numbers.

Edit the data lists below and rerun: .venv/bin/python report/infographic.py
Writes report/yapperton_infographic.png (300 dpi, transparent), .pdf and .svg.
"""
from pathlib import Path
from textwrap import fill

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

# ---------------------------------------------------------------- content
TITLE = "Yapperton"
SUBTITLE = "A voice-first study buddy that runs entirely on your own laptop"
INTRO = ("Upload your course documents, then just talk. Yapperton answers from your own material with the "
         "source page on screen, writes quizzes, and never sends your documents or voice to the cloud.")

STATS = [  # (value, label)
    ("100%", "local: documents,\nvoice and models"),
    ("4", "AI models on\nyour laptop"),
    ("9.7 GB", "of models\non disk"),
    ("5.8k", "lines of code\n(Python + JS)"),
    ("164", "automated\nunit tests"),
]

PIPELINES = [  # (name, accent, [(step, detail), ...])
    ("1  Reading documents", "green", [
        ("Upload", "PDF, DOCX, TXT, MD\nup to 20 MiB\nby click or by voice"),
        ("Fingerprint", "SHA-256 hash;\nduplicates are\nskipped"),
        ("Extract", "pypdf, python-docx;\npage and paragraph\nkept for citations"),
        ("Chunk", "up to 1,000 chars\n150-char overlap"),
        ("Embed", "nomic-embed-text\nbatches of 16"),
        ("Store + summarize", "SQLite index;\nQwen writes title\n+ 3-5 sentence summary"),
    ]),
    ("2  Answering a question", "cyan", [
        ("Question", "typed in chat\nor spoken"),
        ("Route", "code rules first,\ncosine >= 0.65,\nthen summary router"),
        ("Hybrid search", "cosine + keyword\nranks fused (RRF)\ntop 8 passages"),
        ("Select evidence", "Qwen picks the\npassages that\nanswer it"),
        ("Write answer", "qwen3.5:9b\ntemperature 0\n16,384-token context"),
        ("Check + cite", "unsupported numbers\nreplaced; sources\nresolved by server"),
    ]),
    ("3  Voice conversation", "violet", [
        ("Microphone", "in the browser;\nmute with M"),
        ("Silero VAD", "detects speech;\n1 s pause ends\nyour turn"),
        ("Whisper", "large-v3-turbo\nspeech to text"),
        ("Qwen", "streams sentence\nby sentence\n256-token replies"),
        ("Kokoro", "82M text to speech\nvoice af_bella"),
        ("Speaker + wisp", "animated orb;\nfiller after 1.2 s\nif still thinking"),
    ]),
]

FEATURES = [  # (title, text, accent)
    ("Talk to your slides", "Ask about any uploaded lecture out loud and hear the answer.", "cyan"),
    ("Answers with sources", "Every document answer shows the file and page it came from.", "green"),
    ("Quizzes on demand", "\"Make a 3 question quiz about X\": multiple choice with explanations.", "amber"),
    ("Attach by voice", "\"I need to attach a document\" opens the upload box.", "violet"),
    ("Smart routing", "Course questions use your documents; small talk gets a normal reply.", "blue"),
    ("Fact checks", "\"Is that right?\" searches Wikipedia, then DuckDuckGo (text chat).", "red"),
    ("Follow-ups", "\"What about the second one?\" keeps the context of the last answer.", "cyan"),
    ("Chat + documents", "A text chat and document manager sit side by side.", "green"),
]

MODELS = [  # (model, role, runs on, size)
    ("qwen3.5:9b", "answers, quizzes, summaries, routing", "Ollama", "7.6 GB"),
    ("nomic-embed-text", "passage and question embeddings", "Ollama", "274 MB"),
    ("whisper-large-v3-turbo", "speech to text", "MLX / faster-whisper", "1.5 GB"),
    ("Kokoro-82M", "text to speech (af_bella)", "MLX / kokoro-onnx", "372 MB"),
    ("Silero VAD", "detects when you speak", "ONNX in the browser", "2 MB"),
]

STACK = [  # (layer, tools)
    ("Backend", "Python 3.10+, Flask (localhost:5050)"),
    ("Frontend", "plain HTML, CSS, JavaScript; canvas wisp"),
    ("Storage", "SQLite: passages, vectors, summaries"),
    ("Documents", "pypdf, python-docx, UTF-8 text"),
    ("Web check", "Wikipedia API, ddgs (DuckDuckGo)"),
    ("Platforms", "macOS (Apple silicon, MLX) and Windows"),
]

CODE_LINES = [  # (file, lines)
    ("app.py", 591), ("voice.js", 521), ("answering.py", 519), ("wisp.js", 506),
    ("quiz.py", 268), ("files.js", 267), ("speech.py", 251), ("rag.py", 217),
    ("chat.js", 160), ("web_search.py", 116),
]
TESTS = [  # (area, tests)
    ("voice", 44), ("answering", 34), ("app routes", 18), ("web search", 17), ("retrieval", 13),
    ("files", 12), ("quizzes", 12), ("Ollama start", 8), ("indexing", 6),
]

NUMBERS = [  # (value, meaning)
    ("20 MiB", "upload limit"), ("500", "PDF pages max"), ("1,000", "chunks per file max"),
    ("8", "passages per answer"), ("0.65", "cosine to use documents"), ("16,384", "context tokens"),
    ("2,048", "answer tokens"), ("256", "voice reply tokens"), ("1 s", "pause ends a turn"),
    ("5 / 10", "quiz questions default / max"), ("0.3", "quiz temperature"), ("5050", "local port"),
]

WISP = [  # (state, colour)
    ("loading", "#7fa6c9"), ("ready", "#6fb4d8"), ("listening", "#5ce8d6"), ("transcribing", "#8fd8ff"),
    ("thinking", "#a88bff"), ("speaking", "#ffd27a"), ("reading", "#79dca6"), ("muted", "#7d8896"),
    ("error", "#ff7a6a"),
]

PRIVACY = [
    "Documents, embeddings and the index stay in uploads/ on your laptop.",
    "Voice audio is processed in memory and never saved.",
    "Chat history lives only in the browser tab.",
    "Only exception: a fact check sends the question text to Wikipedia / DuckDuckGo.",
]

LIMITS = [
    "A 9B model can still be wrong: sources are shown so you can check.",
    "Scanned PDFs need OCR first; OCR is not built in.",
    "Quizzes are slow by design (each question is self-checked).",
    "Quiz answers are clicked; answering by voice is not built yet.",
    "Single user on localhost; search is sized for a course's worth of files.",
]

# ---------------------------------------------------------------- style
INK, MUTED, CARD, LINE = "#0f1724", "#556074", "#f2f5f9", "#d5dce6"
ACCENT = {"cyan": "#0e8aa3", "violet": "#6a4fd8", "amber": "#c7771b", "green": "#1f8a5b",
          "blue": "#2a5fb0", "red": "#c2453a"}
TINT = {"cyan": "#e3f4f7", "violet": "#eeeafc", "amber": "#fbf0e1", "green": "#e3f3ea",
        "blue": "#e5edf8", "red": "#f9e6e4"}
plt.rcParams["font.family"] = ["Helvetica Neue", "DejaVu Sans"]
plt.rcParams["svg.fonttype"] = "none"

W, H = 100, 232  # layout units; 1 unit = 0.16 inch
fig = plt.figure(figsize=(16, H * 0.16))
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, W)
ax.set_ylim(H, 0)
ax.axis("off")


def card(x, y, w, h, face=CARD, edge=None, radius=1.2, lw=1.5):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={radius}",
                                facecolor=face, edgecolor=edge or face, linewidth=lw))


def text(x, y, s, size=14, color=INK, weight="normal", ha="left", va="top", **kw):
    ax.text(x, y, s, fontsize=size, color=color, fontweight=weight, ha=ha, va=va, **kw)


def heading(y, s, note=None):
    text(4, y, s, 30, weight="bold")
    if note:
        text(96, y + 0.9, note, 15, MUTED, ha="right")
    ax.plot([4, 96], [y + 3.4, y + 3.4], color=LINE, lw=1.5)


# ---------------------------------------------------------------- header
card(0, 0, W, 22.5, face=INK, radius=0.01)
for i, (state, colour) in enumerate(WISP):  # a strip of the wisp's colours along the header edge
    ax.add_patch(plt.Rectangle((i * W / len(WISP), 22.1), W / len(WISP), 0.4, color=colour))
text(4, 3.0, TITLE, 92, "white", "bold")
text(4.3, 12.2, SUBTITLE, 25, "#9fe3ef")
text(4.3, 16.0, fill(INTRO, 118), 15.5, "#c9d2de", linespacing=1.5)
for cx, cy, r, colour, alpha in [(86, 9, 6.5, "#5ce8d6", .18), (86, 9, 4.6, "#a88bff", .28),
                                 (86, 9, 2.8, "#ffd27a", .55), (86, 9, 1.4, "#fff6e0", .9)]:
    ax.add_patch(plt.Circle((cx, cy), r, color=colour, alpha=alpha, lw=0))

# ---------------------------------------------------------------- stats
tile_w = (92 - 4 * 2) / len(STATS)
for i, (value, label) in enumerate(STATS):
    x = 4 + i * (tile_w + 2)
    card(x, 25, tile_w, 10.5)
    text(x + tile_w / 2, 26.4, value, 38, ACCENT[list(ACCENT)[i % 5]], "bold", ha="center")
    text(x + tile_w / 2, 31.6, label, 13.5, MUTED, ha="center", linespacing=1.3)

# ---------------------------------------------------------------- pipelines
heading(39, "How it works", "every step runs on your laptop")
row_y = 45
for name, accent, steps in PIPELINES:
    text(4, row_y, name, 19, ACCENT[accent], "bold")
    box_w, gap = 13.4, 2.3
    for i, (step, detail) in enumerate(steps):
        x, y = 4 + i * (box_w + gap), row_y + 3.2
        card(x, y, box_w, 10.2, face=TINT[accent], edge=ACCENT[accent], radius=0.9, lw=1.2)
        text(x + box_w / 2, y + 1.0, step, 15, ACCENT[accent], "bold", ha="center")
        text(x + box_w / 2, y + 3.7, detail, 11.5, INK, ha="center", linespacing=1.35)
        if i:
            ax.add_patch(FancyArrowPatch((x - gap + 0.25, y + 5.1), (x - 0.25, y + 5.1),
                                         arrowstyle="-|>", mutation_scale=18, color=ACCENT[accent], lw=2))
    row_y += 15.5
text(4, row_y - 1.6, "Requests are recognized in code before search: identity questions, \"what is uploaded?\", quizzes, "
     "uploads and fact checks each take their own path.", 12.5, MUTED, style="italic")

# ---------------------------------------------------------------- features
heading(94, "What you can do")
feat_w, feat_h = (92 - 3 * 2) / 4, 9.6
for i, (title, body, accent) in enumerate(FEATURES):
    x, y = 4 + (i % 4) * (feat_w + 2), 100 + (i // 4) * (feat_h + 1.6)
    card(x, y, feat_w, feat_h, face=TINT[accent])
    ax.add_patch(plt.Rectangle((x, y + 1.2), 0.45, feat_h - 2.4, color=ACCENT[accent]))
    text(x + 1.6, y + 1.3, title, 16, ACCENT[accent], "bold")
    text(x + 1.6, y + 4.0, fill(body, 30), 12.5, INK, linespacing=1.4)

# ---------------------------------------------------------------- models and stack
heading(123, "Built on", "open models, free tools, no subscriptions")
card(4, 129, 55, 21, face=CARD)
text(5.5, 130.2, "Models", 17, weight="bold")
for i, (model, role, runtime, size) in enumerate(MODELS):
    y = 133.6 + i * 3.1
    text(5.5, y, model, 13.5, ACCENT["violet"], "bold")
    text(22.5, y, role, 12.5)
    text(44.5, y, runtime, 11.5, MUTED)
    text(57.6, y, size, 12.5, weight="bold", ha="right")
card(61, 129, 35, 21, face=CARD)
text(62.5, 130.2, "Software", 17, weight="bold")
for i, (layer, tools) in enumerate(STACK):
    y = 133.6 + i * 2.75
    text(62.5, y, layer, 12.5, ACCENT["cyan"], "bold")
    text(70.5, y, fill(tools, 44), 11.5)


# ---------------------------------------------------------------- code and tests charts
heading(154, "Code and tests", "lines per source file / unit tests per area")
for col, (rows, accent, unit) in enumerate([(CODE_LINES, "blue", ""), (TESTS, "green", "")]):
    x0, top = 4 + col * 48, 160
    peak = max(v for _, v in rows)
    for i, (label, value) in enumerate(rows):
        y = top + i * 2.35
        text(x0 + 13, y + 0.95, label, 12.5, INK, ha="right", va="center")
        ax.add_patch(plt.Rectangle((x0 + 14, y + 0.2), 26 * value / peak, 1.5, color=ACCENT[accent]))
        text(x0 + 14.6 + 26 * value / peak, y + 0.95, f"{value:,}", 12, MUTED, va="center")

# ---------------------------------------------------------------- numbers
heading(185, "By the numbers")
num_w = (92 - 5 * 1.6) / 6
for i, (value, meaning) in enumerate(NUMBERS):
    x, y = 4 + (i % 6) * (num_w + 1.6), 191 + (i // 6) * 7.2
    card(x, y, num_w, 6.2)
    text(x + num_w / 2, y + 0.9, value, 21, ACCENT["cyan"], "bold", ha="center")
    text(x + num_w / 2, y + 4.0, meaning, 11.5, MUTED, ha="center")

# ---------------------------------------------------------------- wisp, privacy, limits
text(4, 206.5, "The wisp shows what Yapperton is doing", 15, weight="bold")
for i, (state, colour) in enumerate(WISP):
    x = 4 + i * 10.3
    ax.add_patch(plt.Circle((x + 1.2, 210.6), 1.1, color=colour, lw=0))
    text(x + 2.9, 210.6, state, 12.5, INK, va="center")

for col, (title, items, accent) in enumerate([("Privacy", PRIVACY, "green"), ("Honest limits", LIMITS, "amber")]):
    x = 4 + col * 47
    card(x, 213.5, 45, 14, face=TINT[accent])
    text(x + 1.5, 214.5, title, 17, ACCENT[accent], "bold")
    for i, item in enumerate(items):
        text(x + 1.5, 217.6 + i * 1.75, "•  " + item, 11.5, INK)

text(50, 230.6, "Yapperton  ·  local RAG + voice assistant  ·  Flask · Ollama · Whisper · Kokoro",
     12, MUTED, ha="center", va="bottom")

fig_path = Path(__file__).resolve().parent / "yapperton_infographic"
for ext in ("png", "pdf", "svg"):
    fig.savefig(fig_path.with_suffix("." + ext), dpi=300, transparent=True)
print(fig_path.with_suffix(".png"))
