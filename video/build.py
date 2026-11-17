"""Edit the final video frame by frame: slides with staged reveals and slow push-ins, the voice demo
with jump cuts, sped-up waits and punch-in zooms, word-by-word captions, music and sound effects.

Inputs come from narrate.py, slides.py and record_demo.py; output is .tmp/video/yapperton_presentation.mp4.
"""
import bisect
import json
import re
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import music  # noqa: E402
import scenes  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
VIDEO = ROOT / ".tmp" / "video"
AUDIO, SLIDES, DEMO, BUILD = VIDEO / "audio", VIDEO / "slides", VIDEO / "demo", VIDEO / "build"
OUTPUT = VIDEO / "yapperton_presentation.mp4"
RATE, FPS, W, H = 24000, 30, 1920, 1080
FAST_FORWARD = 2.0      # seconds each long wait is squeezed into
LEAD, TAIL = 0.3, 0.5   # silence before and after slide narration
FADE = 0.22             # crossfade between segments
FONT_PATH = "/System/Library/Fonts/HelveticaNeue.ttc"
CYAN, WHITE = (92, 232, 214), (255, 255, 255)
# Highlight colour of the spoken word, by speaker.
SPEAKER_COLOURS = {"narrator": CYAN, "app": (255, 200, 90), "student": (190, 160, 255)}
DURATIONS = json.loads((AUDIO / "durations.json").read_text())
WORDS = json.loads((AUDIO / "words.json").read_text())
# The recorder paused for the narration as it was then; later rewrites may be shorter.
RECORDED = VIDEO / "durations_for_recording.json"
RECORDED_DURATIONS = json.loads(RECORDED.read_text()) if RECORDED.exists() else DURATIONS


def font(size, bold=True):
    return ImageFont.truetype(FONT_PATH, size, index=1 if bold else 10)


def read_wav(path):
    with wave.open(str(path)) as audio:
        rate, channels = audio.getframerate(), audio.getnchannels()
        samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2").astype(np.float32) / 32768
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    if rate != RATE:
        samples = np.interp(np.arange(0, len(samples), rate / RATE), np.arange(len(samples)), samples)
    return samples.astype(np.float32)


def load(path):
    return Image.open(path).convert("RGB").resize((W, H), Image.LANCZOS)


def zoomed(image, zoom, cx=W / 2, cy=H / 2):
    """Crop around (cx, cy) and scale back up: a camera push-in."""
    if zoom <= 1.001:
        return image
    width, height = W / zoom, H / zoom
    left = min(max(cx - width / 2, 0), W - width)
    top = min(max(cy - height / 2, 0), H - height)
    return image.resize((W, H), Image.BILINEAR, box=(left, top, left + width, top + height))


def ease(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


class Captions:
    """Short word groups, the spoken word highlighted, white text with a dark outline."""

    def __init__(self):
        self.font = font(62)
        self.cache = {}

    @staticmethod
    def groups(words, max_words=3):
        chunks, current = [], []
        for word in words:
            current.append(word)
            if len(current) == max_words or re.search(r"[.,:;!?]$", word[2]):
                chunks.append(current)
                current = []
        if current:
            chunks.append(current)
        return chunks

    def image(self, chunk, active):
        key = (tuple(word[2] for word in chunk), active, chunk[0][3] if len(chunk[0]) > 3 else "narrator")
        if key not in self.cache:
            text_words = [word[2] for word in chunk]
            space = self.font.getlength(" ")
            widths = [self.font.getlength(word) for word in text_words]
            width = int(sum(widths) + space * (len(widths) - 1)) + 40
            layer = Image.new("RGBA", (width, 110), (0, 0, 0, 0))
            draw = ImageDraw.Draw(layer)
            x = 20
            for index, (word, word_width) in enumerate(zip(text_words, widths)):
                colour = SPEAKER_COLOURS[key[2]] if index == active else WHITE
                draw.text((x, 18), word, font=self.font, fill=colour, stroke_width=6, stroke_fill=(5, 8, 16))
                x += word_width + space
            self.cache[key] = layer
        return self.cache[key]


class Segment:
    def __init__(self, name, duration):
        self.name, self.duration = name, duration
        self.sounds = []     # (local time, samples, gain)
        self.words = []      # (local start, local end, word)
        self.pops = []       # local times of reveals
        self.caption_y = 950

    def frame(self, t):
        raise NotImplementedError

    def caption_x(self, t):
        return W / 2


class SlideSegment(Segment):
    def __init__(self, slide):
        name = slide["id"]
        super().__init__(name, DURATIONS[name] + LEAD + TAIL)
        self.sounds.append((LEAD, read_wav(AUDIO / f"{name}.wav"), 1.0))
        self.words = [(LEAD + start, LEAD + end, word) for start, end, word in WORDS[name]]
        stages = sorted((path for path in SLIDES.glob(f"{name}_*.png") if path.stem.rsplit("_", 1)[1].isdigit()),
                        key=lambda path: int(path.stem.rsplit("_", 1)[1]))
        self.images = [load(path) for path in stages]
        self.changes = [0.0]
        position = 0
        for cue in slide.get("cues", []):
            for index in range(position, len(self.words)):
                if self.words[index][2].strip("\"'.,:;!?").lower().startswith(cue.lower()):
                    self.changes.append(max(0.0, self.words[index][0] - 0.12))
                    position = index + 1
                    break
        self.changes = self.changes[:len(self.images)]
        self.pops = self.changes[1:]

    def frame(self, t):
        stage = bisect.bisect_right(self.changes, t) - 1
        image = self.images[stage]
        since = t - self.changes[stage]
        if stage and since < 0.18:
            image = Image.blend(self.images[stage - 1], image, ease(since / 0.18))
        return zoomed(image, 1.0 + 0.035 * t / self.duration)


class HookSegment(Segment):
    """Big kinetic words over a dimmed shot of the speaking wisp."""

    def __init__(self, slide, background):
        super().__init__(slide["id"], DURATIONS[slide["id"]] + LEAD + 0.6)
        self.sounds.append((LEAD, read_wav(AUDIO / f"{self.name}.wav"), 1.0))
        self.spoken = [(LEAD + start, LEAD + end, word) for start, end, word in WORDS[self.name]]
        self.background = ImageEnhance.Brightness(background.filter(ImageFilter.GaussianBlur(9))).enhance(0.5)
        self.font = font(118)
        self.lines = self.wrap([word for _, _, word in self.spoken], 1500)

    def wrap(self, words, width):
        lines, current = [], []
        for index, word in enumerate(words):
            trial = " ".join(w for _, w in current + [(index, word)])
            if current and self.font.getlength(trial) > width:
                lines.append(current)
                current = []
            current.append((index, word))
        lines.append(current)
        return lines

    def frame(self, t):
        image = zoomed(self.background, 1.04 + 0.08 * t / self.duration).copy()
        draw = ImageDraw.Draw(image)
        line_height = 140
        y = H / 2 - line_height * len(self.lines) / 2
        for line in self.lines:
            text = " ".join(word for _, word in line)
            x = (W - self.font.getlength(text)) / 2
            for index, word in line:
                start = self.spoken[index][0]
                if t >= start - 0.05:
                    current = start <= t < self.spoken[index][1] + 0.1
                    lift = int(14 * (1 - ease((t - start + 0.05) / 0.15)))
                    draw.text((x, y + lift), word, font=self.font, fill=CYAN if current else WHITE,
                              stroke_width=4, stroke_fill=(5, 8, 16))
                else:
                    # The whole question is visible from the first frame, lit word by word as spoken.
                    draw.text((x, y), word, font=self.font, fill=(125, 136, 155), stroke_width=4,
                              stroke_fill=(5, 8, 16))
                x += self.font.getlength(word + " ")
            y += line_height
        return image


class DemoSegment(Segment):
    """The recorded voice session: waits squeezed, dead air cut, camera punch-ins on the action."""

    def __init__(self, timeline):
        self.timeline = timeline
        markers = self.markers = timeline["markers"]
        self.begin, self.end = markers["demo_intro"] - 0.4, markers["end"]
        self.clip_words = json.loads((DEMO / "clip_words.json").read_text())
        spans, self.clip_stop = self.speech_trims(), {}
        for start, _, _ in spans:
            for clip in timeline["clips"]:
                if clip["at"] < start <= clip["at"] + 30:
                    self.clip_stop[clip["path"]] = start
        spans += [(start, end, FAST_FORWARD) for start, end in self.waits_to_squeeze()]
        # Narration was paced with the old lengths; cut the leftover silence after each line.
        for line in scenes.DEMO_NARRATION:
            spoken_end = markers[line["step"]] + 0.3 + DURATIONS[line["id"]] + 0.35
            paused_end = markers[line["step"]] + RECORDED_DURATIONS[line["id"]] + 0.7
            if line["step"] != "demo_quiz" and paused_end - spoken_end > 0.3:
                spans.append((spoken_end, paused_end, 0.0))
        # Already-recorded timelines: the upload wait as the recorder now marks it.
        if "upload" in markers and "upload_done" in markers:
            spans = [span for span in spans if not (span[0] >= markers["upload"] and span[1] <= markers["upload_done"])]
            spans.append((markers["upload"] + 1.5, markers["upload_done"] - 1.5, FAST_FORWARD))
            # The dialog closes by itself; skip the idle listening after it.
            spans.append((markers["upload_done"] + 0.2, markers["say_question"] - 1.3, 0.0))
        # The recorder waits for the app to settle before each student line; drop that idle second.
        for marker in scenes.STUDENT_LINES:
            if marker in markers:
                spans.append((markers[marker] - 1.3, markers[marker] - 0.3, 0.0))
        # Spans must not overlap, or the time map stops being monotonic.
        self.spans = []
        for start, end, target in sorted(spans):
            if self.spans and start < self.spans[-1][1]:
                start = self.spans[-1][1]
            if end - start > 0.05:
                self.spans.append((start, end, min(target, end - start)))
        grid = np.arange(self.begin, self.end, 0.005)
        self.grid, self.mapped = grid, np.array([self.to_out(at) for at in grid])
        super().__init__("demo", float(self.mapped[-1]))
        self.caption_y = 36
        self.frame_times = [frame["at"] for frame in timeline["frames"]]
        self.frame_paths = [DEMO / "frames" / frame["path"] for frame in timeline["frames"]]
        self.cache = (None, None)
        self.fast = [(self.to_out(start), self.to_out(end), (end - start) / target)
                     for start, end, target in self.spans if target]
        self.moves = self.camera_moves()

        for line in scenes.DEMO_NARRATION:
            start = self.to_out(markers[line["step"]]) + 0.3
            self.sounds.append((start, read_wav(AUDIO / f"{line['id']}.wav"), 1.0))
            self.words += [(start + a, start + b, word, "narrator") for a, b, word in WORDS[line["id"]]]
        for clip in timeline["clips"]:
            inside = any(a <= clip["at"] < b for a, b, _ in self.spans)
            if clip["at"] < self.begin or clip["at"] >= self.end or inside:
                continue
            samples = read_wav(DEMO / "audio" / clip["path"])
            stop = min(clip.get("stop") or self.end, self.end, self.clip_stop.get(clip["path"], self.end))
            samples = samples[:max(0, int((stop - clip["at"]) * RATE))]
            start = self.to_out(clip["at"])
            self.sounds.append((start, samples, 0.9 if clip["kind"] == "app" else 0.85))
            for a, b, word in self.clip_words.get(clip["path"], []):
                if clip["at"] + b <= stop + 0.05:
                    self.words.append((start + a, start + b, word, clip["kind"]))
        self.words.sort()

    def clip_length(self, clip):
        return len(read_wav(DEMO / "audio" / clip["path"])) / RATE

    def speech_trims(self):
        """Cut parts of Yapperton's replies listed in scenes.TRIM_SPEECH, plus the pause after them."""
        spans = []
        for clip in self.timeline["clips"]:
            text = " ".join(word[2] for word in self.clip_words.get(clip["path"], []))
            for prefix, keep in scenes.TRIM_SPEECH:
                if clip["kind"] == "app" and text.startswith(prefix):
                    words = self.clip_words[clip["path"]]
                    if not keep:
                        start = clip["at"]
                    elif keep < len(words):
                        start = clip["at"] + (words[keep - 1][1] + words[keep][0]) / 2
                    else:
                        start = clip["at"] + words[keep - 1][1] + 0.2
                    following = [c["at"] for c in self.timeline["clips"] if c["at"] > clip["at"]]
                    end = clip["at"] + self.clip_length(clip) + 0.3
                    if following:
                        end = min(end, following[0])
                    spans.append((start, end, 0.0))
        return spans

    def waits_to_squeeze(self):
        markers, waits = self.markers, [tuple(wait) for wait in self.timeline["waits"]]
        quiz_wait = [clip for clip in self.timeline["clips"]
                     if clip["kind"] == "app" and markers["say_quiz_end"] < clip["at"] < markers["quiz_shown"]]
        if quiz_wait:
            last = max(quiz_wait, key=lambda clip: clip["at"])
            spoken_end = self.clip_stop.get(last["path"], last["at"] + self.clip_length(last))
            waits.append((spoken_end + 0.8, markers["quiz_shown"] - 0.6))
        return [(start, end) for start, end in waits if end - start > FAST_FORWARD + 0.5]

    def to_out(self, at):
        shifted = at - self.begin
        for start, end, target in self.spans:
            if at >= end:
                shifted -= (end - start) - target
            elif at > start:
                shifted -= (at - start) * (1 - target / (end - start))
        return shifted

    def camera_moves(self):
        """(out time, zoom, cx, cy) keyframes from scenes.CAMERA; positions are in the 1920x1080 frame."""
        moves = [(0.0, 1.0, W / 2, H / 2)]
        for marker, offset, zoom, cx, cy in scenes.CAMERA:
            if marker in self.markers:
                moves.append((self.to_out(self.markers[marker]) + offset, zoom, cx, cy))
        return sorted(moves)

    def camera(self, t):
        index = max(0, bisect.bisect_right([move[0] for move in self.moves], t) - 1)
        current = self.moves[index]
        if index == 0:
            return current[1:]
        previous = self.moves[index - 1]
        progress = ease((t - current[0]) / 0.7)
        return tuple(a + (b - a) * progress for a, b in zip(previous[1:], current[1:]))

    def caption_x(self, t):
        """Keep captions off the quiz panel when the camera is on it."""
        zoom, cx, _ = self.camera(t)
        return 560 if zoom > 1.3 and cx > 1300 else W / 2

    def source_frame(self, t):
        source = float(np.interp(t, self.mapped, self.grid))
        index = max(0, bisect.bisect_right(self.frame_times, source) - 1)
        path = self.frame_paths[index]
        if self.cache[0] != path:
            self.cache = (path, load(path))
        return self.cache[1]

    def frame(self, t):
        zoom, cx, cy = self.camera(t)
        image = zoomed(self.source_frame(t), zoom, cx, cy).copy()
        draw = ImageDraw.Draw(image)
        fast = next((speed for start, end, speed in self.fast if start <= t < end), None)
        label = f"sped up {fast:.0f}×" if fast else "LIVE DEMO · real app"
        small = font(30)
        width = small.getlength(label)
        left = W - width - 100
        draw.rounded_rectangle((left, 34, W - 34, 92), 29, fill=(36, 91, 206) if fast else (20, 24, 34))
        if fast:
            draw.polygon([(left + 22, 51), (left + 22, 75), (left + 34, 63)], fill=WHITE)
            draw.polygon([(left + 34, 51), (left + 34, 75), (left + 46, 63)], fill=WHITE)
        else:
            draw.ellipse((left + 24, 54, left + 42, 72), fill=(255, 80, 80))
        draw.text((left + 56, 45), label, font=small, fill=WHITE)
        return image


def build_segments(timeline):
    demo = DemoSegment(timeline)
    slides = {slide["id"]: slide for slide in scenes.SLIDES}
    speaking = timeline["markers"].get("answer_speaking", timeline["markers"]["end"]) + 3
    hook_background = demo.source_frame(demo.to_out(speaking))
    segments = []
    for item in scenes.ORDER:
        if item == "DEMO":
            segments.append(demo)
        elif item == "hook":
            segments.append(HookSegment(slides[item], hook_background))
        else:
            segments.append(SlideSegment(slides[item]))
    return segments


def mix(segments, starts, total):
    voice = np.zeros(int((total + 2) * RATE), dtype=np.float32)
    effects = np.zeros_like(voice)

    def place(track, at, samples, gain):
        offset = max(0, int(at * RATE))
        end = min(len(track), offset + len(samples))
        track[offset:end] += samples[:end - offset] * gain

    whoosh, pop = music.whoosh(), music.pop()
    for segment, start in zip(segments, starts):
        for at, samples, gain in segment.sounds:
            place(voice, start + at, samples, gain)
        if start > 0:
            place(effects, start - 0.25, whoosh, 0.22)
        for at in segment.pops:
            place(effects, start + at, pop, 0.16)
    bed = np.zeros_like(voice)
    bed[:int(total * RATE)] = music.bed(total)
    # Duck the music under speech.
    window = int(0.25 * RATE)
    envelope = np.convolve(np.abs(voice), np.ones(window) / window, mode="same")
    gain = np.where(envelope > 0.01, 0.04, 0.09).astype(np.float32)
    gain = np.convolve(gain, np.ones(int(0.3 * RATE)) / int(0.3 * RATE), mode="same")
    track = (voice + effects + bed * gain)[:int(total * RATE)]
    return track * min(1.0, 0.95 / max(1e-6, np.abs(track).max()))


def write_srt(segments, starts):
    def stamp(seconds):
        ms = int(round(seconds * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    entries = []
    for segment, start in zip(segments, starts):
        words = getattr(segment, "spoken", None) or segment.words
        for chunk in Captions.groups(words, 7):
            entries.append((start + chunk[0][0], start + chunk[-1][1], " ".join(word[2] for word in chunk)))
    with open(OUTPUT.with_suffix(".srt"), "w") as srt:
        for number, (a, b, text) in enumerate(entries, 1):
            srt.write(f"{number}\n{stamp(a)} --> {stamp(b)}\n{text}\n\n")


def main(preview=None):
    """preview: optional list of output seconds to save as PNGs instead of encoding the video."""
    BUILD.mkdir(parents=True, exist_ok=True)
    timeline = json.loads((DEMO / "timeline.json").read_text())
    segments = build_segments(timeline)
    starts = [float(x) for x in np.cumsum([0] + [segment.duration for segment in segments[:-1]])]
    total = starts[-1] + segments[-1].duration
    for segment, start in zip(segments, starts):
        print(f"  {start:6.1f}  {segment.name}  ({segment.duration:.1f} s)")
    captions = Captions()

    def render(t, previous_last):
        index = bisect.bisect_right(starts, t) - 1
        segment, local = segments[index], t - starts[index]
        image = segment.frame(local)
        if previous_last is not None and local < FADE:
            image = Image.blend(previous_last, image, ease(local / FADE))
        if not isinstance(segment, HookSegment):
            for chunk in Captions.groups(segment.words):
                if chunk[0][0] - 0.05 <= local < chunk[-1][1] + 0.25:
                    active = max(i for i, word in enumerate(chunk) if word[0] - 0.05 <= local)
                    layer = captions.image(chunk, active)
                    x = int(segment.caption_x(local) - layer.width / 2)
                    image.paste(layer, (max(20, x), segment.caption_y), layer)
                    break
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, H - 8, int(W * t / total), H), fill=CYAN)
        if t > total - 1.0:
            image = ImageEnhance.Brightness(image).enhance(max(0.0, (total - t) / 1.0))
        return image

    if preview:
        (BUILD / "preview").mkdir(exist_ok=True)
        for t in preview:
            render(t, None).save(BUILD / "preview" / f"{t:06.1f}.jpg", quality=85)
        return

    audio = mix(segments, starts, total)
    with wave.open(str(BUILD / "audio.wav"), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes((audio * 32767).astype("<i2").tobytes())
    write_srt(segments, starts)

    encoder = subprocess.Popen([
        "ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
        "-r", str(FPS), "-i", "-", "-i", str(BUILD / "audio.wav"),
        "-af", f"loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=out:st={total - 1.0:.2f}:d=1.0",
        "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(OUTPUT),
    ], stdin=subprocess.PIPE)
    previous_last, current = None, 0
    frame_count = int(total * FPS)
    for number in range(frame_count):
        t = number / FPS
        index = bisect.bisect_right(starts, t) - 1
        if index != current:
            previous_last = segments[current].frame(segments[current].duration - 1 / FPS)
            current = index
        encoder.stdin.write(render(t, previous_last).tobytes())
        if number % 600 == 0:
            print(f"frame {number}/{frame_count}", flush=True)
    encoder.stdin.close()
    encoder.wait()
    print(f"{OUTPUT} ({total:.1f} s)")


if __name__ == "__main__":
    main([float(x) for x in sys.argv[1:]] or None)
