"""Local speech recognition and synthesis for voice mode; no external services.

Apple silicon Macs use MLX on the GPU. Windows, Intel Macs and Linux use faster-whisper
(CTranslate2) and kokoro-onnx (ONNX Runtime) on the CPU. Both run Whisper large-v3-turbo
and Kokoro with the same voice, so the app behaves the same everywhere.
"""
import io
import logging
import os
import platform
import re
import sys
import wave
from concurrent.futures import ThreadPoolExecutor
from importlib.util import find_spec
from pathlib import Path

MODELS = Path(__file__).resolve().parent.parent / ".models"
MLX = sys.platform == "darwin" and platform.machine() == "arm64"
if MLX:
    WHISPER_PATH = MODELS / "whisper-large-v3-turbo"
    KOKORO_PATH = MODELS / "Kokoro-82M-bf16"
    PACKAGES = ("mlx_whisper", "mlx_audio", "misaki")
else:
    WHISPER_PATH = MODELS / "faster-whisper-large-v3-turbo"
    KOKORO_PATH = MODELS / "kokoro-onnx"
    PACKAGES = ("faster_whisper", "kokoro_onnx")
KOKORO_ONNX_FILES = ("kokoro-v1.0.onnx", "voices-v1.0.bin")
VOICE = "af_bella"
# A light synthetic sheen so the assistant sounds like a digital AI rather than a plain recording.
VOICE_EFFECT = False
# Spoken while the model thinks; never captioned or kept in history.
FILLERS = ["Hmm.", "Okay, I get it.", "Let me think.", "Right.", "Good question.", "Mm, okay.", "Let's see."]
INPUT_RATE = 16000
OUTPUT_RATE = 24000
UNAVAILABLE = ("Voice mode needs its speech packages and models. Run make voice-install and "
               "make voice-models (or python scripts/tasks.py voice-install and voice-models), then restart.")
# Whisper invents these from background noise when nobody spoke.
_NOISE_PHRASES = {"thank you", "thanks for watching", "thank you for watching", "you",
                  "subtitles by the amara org community"}
_ABBREVIATIONS = {"dr", "mr", "mrs", "ms", "prof", "st", "vs", "etc", "e.g", "i.e", "no"}
_BOUNDARY = re.compile(r"""[.!?]+["')\]]*\s+|\n+""")

# MLX streams belong to the thread that created them, so one thread owns the models.
_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="speech")
_kokoro = None
_whisper = None
_warm = False
_fillers = None


class SpeechError(RuntimeError):
    """Speech models are missing or failed; an operational error, not bad input."""


def model_files():
    if MLX:
        return [WHISPER_PATH, KOKORO_PATH]
    return [WHISPER_PATH / "model.bin", *(KOKORO_PATH / name for name in KOKORO_ONNX_FILES)]


def available():
    return all(path.exists() for path in model_files()) and all(find_spec(name) for name in PACKAGES)


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


def _load_whisper():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel

        # int8 on the CPU is fast and works on any machine; no CUDA libraries needed.
        _whisper = WhisperModel(str(WHISPER_PATH), device="cpu", compute_type="int8")
    return _whisper


def _recognize(frames):
    import numpy as np

    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768
    if MLX:
        import mlx_whisper

        result = mlx_whisper.transcribe(samples, path_or_hf_repo=str(WHISPER_PATH), language="en",
                                        condition_on_previous_text=False)
        return result["text"].strip()
    # Greedy decoding like MLX; the browser already trimmed silence, so no extra VAD here.
    segments, _ = _load_whisper().transcribe(samples, language="en", beam_size=1,
                                             condition_on_previous_text=False)
    return "".join(segment.text for segment in segments).strip()


def _load_kokoro():
    global _kokoro
    if _kokoro is None:
        # Everything is already in .models; never reach for the network.
        os.environ["HF_HUB_OFFLINE"] = "1"
        if MLX:
            from mlx_audio.tts.utils import load_model

            _kokoro = load_model(KOKORO_PATH)
        else:
            from kokoro_onnx import Kokoro

            _kokoro = Kokoro(*(str(KOKORO_PATH / name) for name in KOKORO_ONNX_FILES))
    return _kokoro


def _synthesize_samples(text):
    import numpy as np

    if MLX:
        parts = [np.array(part.audio) for part in _load_kokoro().generate(text, voice=VOICE, lang_code="a")]
        return np.concatenate(parts), OUTPUT_RATE
    samples, rate = _load_kokoro().create(text, voice=VOICE, lang="en-us")
    return np.asarray(samples), rate


def digital_voice(samples, rate):
    """Chorus, high-frequency sheen and a short echo; subtle enough to keep words clear."""
    import numpy as np

    dry = np.asarray(samples, dtype=np.float32)
    if not dry.size:
        return dry
    index = np.arange(dry.size, dtype=np.float32)
    # Chorus: a copy read through a slowly wobbling 6-12 ms delay.
    delay = (0.009 + 0.003 * np.sin(2 * np.pi * 0.8 * index / rate)) * rate
    chorus = np.interp(index - delay, index, dry, left=0)
    # Sheen: lift the highs with a first difference (a simple high-pass).
    sheen = np.diff(dry, prepend=dry[0])
    wet = dry + 0.28 * chorus + 0.35 * sheen
    for seconds, gain in ((0.035, 0.14), (0.075, 0.07)):
        shift = int(seconds * rate)
        wet[shift:] += gain * wet[:-shift].copy()
    # Keep the plain voice's loudness, only limiting peaks so nothing clips.
    level = float(np.sqrt(np.mean(dry ** 2)) / (np.sqrt(np.mean(wet ** 2)) or 1))
    wet *= level
    peak = float(np.max(np.abs(wet)))
    return wet * (0.95 / peak) if peak > 0.95 else wet


def _render(text):
    import numpy as np

    samples, rate = _synthesize_samples(text)
    if VOICE_EFFECT:
        samples = digital_voice(samples, rate)
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(pcm.tobytes())
    return output.getvalue()


def _render_fillers():
    global _fillers
    if _fillers is None:
        _fillers = [(text, _render(text)) for text in FILLERS]
    return _fillers


def _warm_up():
    global _warm
    if not _warm:
        _render("Ready.")
        _recognize(bytes(INPUT_RATE // 5))
        _render_fillers()
        _warm = True


def warm_up():
    _run(_warm_up)


def fillers():
    """Return (text, wav bytes) for each thinking filler, rendered once."""
    return _run(_render_fillers)


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
