"""Local speech recognition and synthesis for voice mode; no external services."""
import io
import logging
import os
import re
import sys
import wave
from concurrent.futures import ThreadPoolExecutor
from importlib.util import find_spec
from pathlib import Path

MODELS = Path(__file__).resolve().parent.parent / ".models"
WHISPER_PATH = MODELS / "whisper-large-v3-turbo"
KOKORO_PATH = MODELS / "Kokoro-82M-bf16"
VOICE = "af_aoede"
INPUT_RATE = 16000
OUTPUT_RATE = 24000
UNAVAILABLE = "Voice mode needs macOS. Run make voice-install and make voice-models, then restart."
# Whisper invents these from background noise when nobody spoke.
_NOISE_PHRASES = {"thank you", "thanks for watching", "thank you for watching", "you",
                  "subtitles by the amara org community"}
_ABBREVIATIONS = {"dr", "mr", "mrs", "ms", "prof", "st", "vs", "etc", "e.g", "i.e", "no"}
_BOUNDARY = re.compile(r"""[.!?]+["')\]]*\s+|\n+""")

# MLX streams belong to the thread that created them, so one thread owns the models.
_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="speech")
_kokoro = None
_warm = False


class SpeechError(RuntimeError):
    """Speech models are missing or failed; an operational error, not bad input."""


def available():
    return (sys.platform == "darwin" and WHISPER_PATH.is_dir() and KOKORO_PATH.is_dir()
            and all(find_spec(name) for name in ("mlx_whisper", "mlx_audio", "misaki")))


def _run(task, *args):
    if not available():
        raise SpeechError(UNAVAILABLE)
    try:
        return _worker.submit(task, *args).result()
    except Exception as error:
        logging.getLogger(__name__).exception("Speech task failed")
        raise SpeechError("Local speech processing failed.") from error


def _read_wav(data):
    try:
        with wave.open(io.BytesIO(data)) as audio:
            shape = audio.getnchannels(), audio.getsampwidth(), audio.getframerate()
            frames = audio.readframes(audio.getnframes())
    except (wave.Error, EOFError) as error:
        raise ValueError("Audio must be a WAV file.") from error
    if shape != (1, 2, INPUT_RATE):
        raise ValueError("Audio must be 16 kHz, 16-bit mono.")
    if not frames:
        raise ValueError("Audio is empty.")
    return frames


def _recognize(frames):
    import mlx_whisper
    import numpy as np

    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768
    result = mlx_whisper.transcribe(samples, path_or_hf_repo=str(WHISPER_PATH), language="en",
                                    condition_on_previous_text=False)
    return result["text"].strip()


def _load_kokoro():
    global _kokoro
    if _kokoro is None:
        from mlx_audio.tts.utils import load_model

        # Everything is already in .models; never reach for the network.
        os.environ["HF_HUB_OFFLINE"] = "1"
        _kokoro = load_model(KOKORO_PATH)
    return _kokoro


def _render(text):
    import numpy as np

    parts = [np.array(part.audio) for part in _load_kokoro().generate(text, voice=VOICE, lang_code="a")]
    pcm = (np.clip(np.concatenate(parts), -1, 1) * 32767).astype("<i2")
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(OUTPUT_RATE)
        audio.writeframes(pcm.tobytes())
    return output.getvalue()


def _warm_up():
    global _warm
    if not _warm:
        _render("Ready.")
        _recognize(bytes(INPUT_RATE // 5))
        _warm = True


def warm_up():
    _run(_warm_up)


def transcribe(data):
    """Return the spoken text, or an empty string when the audio holds only noise."""
    text = _run(_recognize, _read_wav(data))
    normalized = re.sub(r"[^a-z ]", "", text.lower()).strip()
    return "" if normalized in _NOISE_PHRASES or not normalized else text


def synthesize(text):
    return _run(_render, text)


def _ends_sentence(text, boundary):
    if "\n" in boundary or boundary[0] != ".":
        return True
    words = text.split()
    word = words[-1].rstrip(".").lower() if words else ""
    return not (word in _ABBREVIATIONS or word.isdigit() or (len(word) == 1 and word.isalpha()))


def split_sentences(chunks):
    """Yield complete sentences from streamed text as soon as each one ends."""
    buffer = ""
    for chunk in chunks:
        buffer += chunk
        start = 0
        for match in _BOUNDARY.finditer(buffer):
            if _ends_sentence(buffer[start:match.start()], match.group()):
                sentence = buffer[start:match.end()].strip()
                start = match.end()
                if sentence:
                    yield sentence
        buffer = buffer[start:]
    if buffer.strip():
        yield buffer.strip()


def clean_for_speech(text):
    """Strip markup a voice would read aloud; empty when nothing speakable remains."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "a link", text)
    text = re.sub(r"^\s*(?:[-*+>#]+|\d+[.)])\s+", "", text)
    text = re.sub(r"[`*#~]|(?<!\w)_+|_+(?!\w)", "", text)
    text = " ".join(text.split())
    return text if any(character.isalnum() for character in text) else ""
