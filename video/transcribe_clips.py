"""Time every word Yapperton and the student say in the recording, for on-screen captions.

Writes .tmp/video/demo/clip_words.json: {clip file: [[start, end, word], ...]} relative to the clip.
"""
import json
import os
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / ".tmp" / "video" / "demo"


def samples_16k(path):
    with wave.open(str(path)) as audio:
        rate = audio.getframerate()
        samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2").astype(np.float32) / 32768
    return np.interp(np.arange(0, len(samples), rate / 16000), np.arange(len(samples)), samples).astype(np.float32)


def main():
    os.environ["HF_HUB_OFFLINE"] = "1"
    import mlx_whisper

    timeline = json.loads((DEMO / "timeline.json").read_text())
    words = {}
    for clip in timeline["clips"]:
        result = mlx_whisper.transcribe(samples_16k(DEMO / "audio" / clip["path"]),
                                        path_or_hf_repo=str(ROOT / ".models" / "whisper-large-v3-turbo"),
                                        language="en", word_timestamps=True)
        timed = []
        for segment in result["segments"]:
            for w in segment.get("words", []):
                text = w["word"].strip()
                if text.startswith("-") and timed:
                    timed[-1][1], timed[-1][2] = w["end"], timed[-1][2] + text
                else:
                    timed.append([w["start"], w["end"], text])
        words[clip["path"]] = timed
        print(clip["kind"], clip["path"], " ".join(w[2] for w in words[clip["path"]]))
    (DEMO / "clip_words.json").write_text(json.dumps(words, indent=1))


if __name__ == "__main__":
    sys.exit(main())
