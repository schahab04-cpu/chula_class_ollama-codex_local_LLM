"""Render narration and the student's lines with local Kokoro, then time every caption word with Whisper.

Writes .tmp/video/audio/<id>.wav, durations.json and words.json ({id: [[start, end, word], ...]}).
Run it only while no recording is running: the recorder reads durations.json and the student lines.
"""
import json
import os
import re
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scenes  # noqa: E402

OUT = ROOT / ".tmp" / "video" / "audio"
RATE = 24000


def save(path, samples, rate=RATE):
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(pcm.tobytes())


def normalize(word):
    return re.sub(r"[^a-z0-9]", "", word.lower())


def align(words, heard, duration):
    """Time each caption word from Whisper's words: matched words take Whisper's times, the rest are
    spread evenly between their matched neighbours."""
    from difflib import SequenceMatcher

    if not heard:
        step = duration / max(1, len(words))
        return [[i * step, (i + 1) * step, word] for i, word in enumerate(words)]
    times = [None] * len(words)
    matcher = SequenceMatcher(None, [normalize(w) for w in words], [normalize(h[2]) for h in heard], autojunk=False)
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            times[block.a + k] = heard[block.b + k][:2]
    if times[0] is None:
        times[0] = (heard[0][0], heard[0][0] + 0.2)
    if times[-1] is None:
        times[-1] = (heard[-1][1] - 0.2, heard[-1][1])
    index = 0
    while index < len(words):
        if times[index] is not None:
            index += 1
            continue
        gap_end = index
        while times[gap_end] is None:
            gap_end += 1
        begin, finish = times[index - 1][1], times[gap_end][0]
        step = max(0.0, finish - begin) / (gap_end - index)
        for k in range(index, gap_end):
            times[k] = (begin + (k - index) * step, begin + (k - index + 1) * step)
        index = gap_end
    return [[start, end, word] for (start, end), word in zip(times, words)]


def main(only=None):
    os.environ["HF_HUB_OFFLINE"] = "1"
    import mlx_whisper
    from mlx_audio.tts.utils import load_model

    model = load_model(ROOT / ".models" / "Kokoro-82M-bf16")
    OUT.mkdir(parents=True, exist_ok=True)
    durations_path, words_path = OUT / "durations.json", OUT / "words.json"
    durations = json.loads(durations_path.read_text()) if durations_path.exists() else {}
    words = json.loads(words_path.read_text()) if words_path.exists() else {}

    def speak(text, voice, speed=1.0):
        parts = [np.array(part.audio) for part in model.generate(text, voice=voice, lang_code="a", speed=speed)]
        return np.concatenate(parts).astype(np.float32)

    lines = [(slide["id"], slide["text"], slide.get("say", slide["text"])) for slide in scenes.SLIDES]
    lines += [(line["id"], line["text"], line.get("say", line["text"])) for line in scenes.DEMO_NARRATION]
    for name, text, spoken in lines:
        if only and name not in only:
            continue
        samples = speak(spoken, scenes.NARRATOR_VOICE, scenes.NARRATION_SPEED)
        # Trim Kokoro's trailing silence so pacing stays tight.
        loud = np.flatnonzero(np.abs(samples) > 0.01)
        if len(loud):
            samples = samples[:loud[-1] + int(0.08 * RATE)]
        save(OUT / f"{name}.wav", samples)
        durations[name] = len(samples) / RATE
        resampled = np.interp(np.arange(0, len(samples), RATE / 16000), np.arange(len(samples)), samples)
        result = mlx_whisper.transcribe(resampled.astype(np.float32),
                                        path_or_hf_repo=str(ROOT / ".models" / "whisper-large-v3-turbo"),
                                        language="en", word_timestamps=True)
        heard = [(w["start"], w["end"], w["word"]) for segment in result["segments"] for w in segment.get("words", [])]
        caption_words = re.findall(r"\S+", text)
        words[name] = align(caption_words, heard, durations[name])
        match = f"{len(heard)} heard / {len(caption_words)} caption words"
        print(f"{name}: {durations[name]:.1f} s, word timing {match}")

    # The student's lines are played into the app's microphone during the recording.
    for name, text in scenes.STUDENT_LINES.items():
        if only and name not in only:
            continue
        samples = speak(text, scenes.STUDENT_VOICE)
        save(OUT / f"{name}.wav", samples)
        durations[name] = len(samples) / RATE
    durations_path.write_text(json.dumps(durations, indent=2))
    words_path.write_text(json.dumps(words, indent=1))


if __name__ == "__main__":
    main(set(sys.argv[1:]) or None)
