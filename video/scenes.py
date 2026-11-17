"""Storyboard for the presentation video. Edit the text here and rerun video/build.py.

Structure follows short-form practice: a hook in the first seconds, the product shown working
before it is explained, something new on screen every few seconds, captions throughout and a
call to action at the end.

`text` is what the captions show; `say` (optional) is respelled so Kokoro pronounces names well.
`cues` reveal slide parts one by one, each on the first later caption word starting with the cue.
"""

NARRATOR_VOICE = "am_michael"
STUDENT_VOICE = "am_adam"
NARRATION_SPEED = 1.1

DEMO_DOCUMENT = "GAI_Literacy_Lecture_1.pdf"

# What the student says into the microphone during the voice demo, in order.
STUDENT_LINES = {
    "say_attach": "I need to attach a document.",
    "say_question": "According to the lecture, what does AI literacy mean?",
    "say_quiz": "Make a three question quiz about predictive and generative AI.",
}

SLIDES = [
    {
        "id": "hook",
        "text": "What if your lecture slides could talk back?",
    },
    {
        "id": "title",
        "kicker": "BAScii Generative AI · Final project · Group Aliens",
        "title": "Yapperton",
        "subtitle": "A study buddy you talk to.\nRunning entirely on your laptop.",
        "text": "Meet Yapperton: a study buddy you talk to, running entirely on your own laptop.",
    },
    {
        "id": "problem",
        "title": "Studying alone is hard",
        "bullets": [
            "Long slides, short focus",
            "Explaining out loud helps,\nbut nobody is free at 11 pm",
            "Cloud AI = your notes on\nsomeone else's server",
        ],
        "text": "Studying alone from long slides is hard. Explaining out loud helps, but nobody is free at "
                "eleven p.m. before an exam. And cloud AI means uploading your notes to someone else's server.",
        "say": "Studying alone from long slides is hard. Explaining out loud helps, but nobody is free at "
               "eleven P M before an exam. And cloud AI means uploading your notes to someone else's server.",
        "cues": ["Studying", "Explaining", "cloud"],
    },
    {
        "id": "architecture",
        "title": "Under the hood",
        "diagram": True,
        "text": "Under the hood: documents become searchable passages. A hybrid search finds the best "
                "ones, and Qwen 3.5 writes the answer, all in Ollama. Whisper listens, Kokoro speaks. "
                "Nothing leaves your laptop.",
        "say": "Under the hood: documents become searchable passages. A hybrid search finds the best "
               "ones, and Kwen three point five writes the answer, all in oh-llama. Whisper listens, Kokoro "
               "speaks. Nothing leaves your laptop.",
        "cues": ["documents", "hybrid", "Whisper", "Nothing"],
    },
    {
        "id": "limits",
        "title": "Honest limits",
        "bullets": [
            "A small model can be wrong:\nsources are always on screen",
            "Quizzes take a few minutes\non a laptop",
        ],
        "text": "It's not perfect. A small model can be wrong, so sources are always on screen, "
                "and quizzes take a few minutes on a laptop.",
        "cues": ["small", "quizzes"],
    },
    {
        "id": "closing",
        "kicker": "Wilhelm Durelius · Shayan Gardan Gardawan · Schahab Bashar-Mal",
        "title": "Yapperton",
        "subtitle": "Your course, out loud. Fully private.\ngithub.com/schahab04-cpu/chula_class_ollama-codex_local_LLM",
        "text": "Yapperton. Your course, out loud, fully private. Find it on GitHub.",
    },
]

# Narration spoken over the demo recording, keyed by the recording marker it starts at.
DEMO_NARRATION = [
    {"id": "demo_intro", "step": "demo_intro",
     "text": "Here's Yapperton. Press start, and just talk."},
    {"id": "demo_upload", "step": "demo_upload",
     "text": "Need a document? Just say so. The upload box opens, we drop in our first lecture, "
             "and Yapperton reads it."},
    {"id": "demo_answer", "step": "demo_answer",
     "text": "The answer comes from your slides, with the source page right on screen."},
    {"id": "demo_quiz", "step": "demo_quiz",
     "text": "Exam tomorrow? Ask for a quiz. Click an answer to see if you got it, and why."},
]

# Order of the final video: slide ids and the demo block.
ORDER = ["hook", "title", "problem", "DEMO", "architecture", "limits", "closing"]

# Camera punch-ins during the demo: (recording marker, seconds after it, zoom, centre x, centre y).
# Each move eases in over 0.7 s and holds until the next one.
CAMERA = [
    ("say_attach", 0.0, 1.12, 960, 620),
    ("upload_dialog", 0.2, 1.35, 960, 540),
    ("upload_done", -1.0, 1.0, 960, 540),
    ("say_question", 0.0, 1.15, 960, 620),
    ("answer_speaking", 0.5, 1.3, 960, 760),
    ("demo_answer", 0.0, 1.8, 960, 900),
    ("say_quiz", -0.5, 1.15, 960, 640),
    ("quiz_shown", 0.0, 1.0, 960, 540),
    ("demo_quiz", 0.0, 1.6, 1560, 500),
]

# Parts of Yapperton's replies to cut for pace: (reply starts with, words to keep).
TRIM_SPEECH = [
    ("Okay, writing your quiz now.", 5),
]
