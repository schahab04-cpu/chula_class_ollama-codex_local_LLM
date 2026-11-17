"""Drive the voice screen of the running app in Chromium and record it.

A student voice (Kokoro) is played into a fake microphone on cue, so the whole demo is spoken.
Records screencast frames, step markers, waits to cut, and every clip the page plays.
Needs the app at http://127.0.0.1:5050, the demo document not yet uploaded, and
PLAYWRIGHT_BROWSERS_PATH=.tmp/ms-playwright. Output: .tmp/video/demo/ (times are epoch seconds).
"""
import asyncio
import base64
import json
import shutil
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scenes  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
VIDEO = ROOT / ".tmp" / "video"
OUT = VIDEO / "demo"
URL = "http://127.0.0.1:5050"
DURATIONS = json.loads((VIDEO / "audio" / "durations.json").read_text())
LONG = 1_800_000

# The microphone becomes a stream we can speak into (window.say), and every clip the page
# decodes and plays is reported with its start time, so the silent recording gets its sound back.
INIT_SCRIPT = """
(() => {
  const clips = new WeakMap();
  const decode = BaseAudioContext.prototype.decodeAudioData;
  BaseAudioContext.prototype.decodeAudioData = function (data, ...rest) {
    const copy = data.slice(0);
    return decode.call(this, data, ...rest).then((buffer) => { clips.set(buffer, copy); return buffer; });
  };
  const toBase64 = (buffer) => {
    const bytes = new Uint8Array(buffer);
    let text = "";
    for (let i = 0; i < bytes.length; i += 32768) text += String.fromCharCode(...bytes.subarray(i, i + 32768));
    return btoa(text);
  };
  const start = AudioBufferSourceNode.prototype.start;
  AudioBufferSourceNode.prototype.start = function (when = 0, ...rest) {
    const copy = this.buffer && clips.get(this.buffer);
    if (copy && window.reportAudio) {
      const delay = Math.max(0, when - this.context.currentTime);
      this.__clipId = Math.random().toString(36).slice(2);
      window.reportAudio({ id: this.__clipId, at: Date.now() / 1000 + delay, wav: toBase64(copy),
                           kind: this.__student ? "student" : "app" });
    }
    return start.call(this, when, ...rest);
  };
  const stop = AudioBufferSourceNode.prototype.stop;
  AudioBufferSourceNode.prototype.stop = function (...args) {
    if (this.__clipId && window.reportStop) window.reportStop({ id: this.__clipId, at: Date.now() / 1000 });
    return stop.apply(this, args);
  };

  // A fresh stream per request: pausing for document reading stops the old stream's tracks.
  const mic = new AudioContext();
  let micOut = mic.createMediaStreamDestination();
  navigator.mediaDevices.getUserMedia = async () => {
    await mic.resume();
    micOut = mic.createMediaStreamDestination();
    return micOut.stream;
  };
  window.say = async (encoded) => {
    await mic.resume();
    const bytes = Uint8Array.from(atob(encoded), (c) => c.charCodeAt(0));
    const buffer = await mic.decodeAudioData(bytes.buffer);
    const source = mic.createBufferSource();
    source.buffer = buffer;
    source.connect(micOut);
    source.__student = true;
    source.start();
    return buffer.duration;
  };
})();
"""


async def main():
    shutil.rmtree(OUT, ignore_errors=True)
    (OUT / "frames").mkdir(parents=True)
    (OUT / "audio").mkdir()
    frames, markers, clips, stops, waits = [], {}, [], {}, []

    def mark(name):
        markers[name] = time.time()
        print(f"[{time.strftime('%H:%M:%S')}] {name}", flush=True)
        return markers[name]

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--autoplay-policy=no-user-gesture-required"])
        context = await browser.new_context(viewport={"width": 1440, "height": 810}, device_scale_factor=4 / 3)
        page = await context.new_page()

        async def report_audio(clip):
            path = OUT / "audio" / f"{len(clips):03d}.wav"
            path.write_bytes(base64.b64decode(clip["wav"]))
            clips.append({"id": clip["id"], "at": clip["at"], "kind": clip["kind"], "path": path.name})

        async def report_stop(stop):
            stops[stop["id"]] = stop["at"]

        await page.expose_function("reportAudio", report_audio)
        await page.expose_function("reportStop", report_stop)
        await page.add_init_script(INIT_SCRIPT)
        cdp = await context.new_cdp_session(page)

        async def on_frame(event):
            path = OUT / "frames" / f"{len(frames):06d}.jpg"
            path.write_bytes(base64.b64decode(event["data"]))
            frames.append({"at": event["metadata"]["timestamp"], "path": path.name})
            try:
                await cdp.send("Page.screencastFrameAck", {"sessionId": event["sessionId"]})
            except Exception:
                pass

        cdp.on("Page.screencastFrame", lambda event: asyncio.ensure_future(on_frame(event)))

        async def state_is(*states):
            await page.wait_for_function(
                "states => states.includes(document.querySelector('#voice-view').dataset.state)",
                arg=list(states), timeout=LONG, polling=100)

        async def student_says(name):
            """Speak into the fake mic once the app listens; repeat if the app did not react.
            Returns the time the line ended."""
            encoded = base64.b64encode((VIDEO / "audio" / f"{name}.wav").read_bytes()).decode()
            for attempt in range(4):
                await state_is("listening")
                await page.wait_for_timeout(1500)
                if await page.evaluate("document.querySelector('#voice-view').dataset.state") != "listening":
                    continue
                mark(name)
                length = await page.evaluate("encoded => window.say(encoded)", encoded)
                await page.wait_for_timeout(length * 1000)
                ended = mark(f"{name}_end")
                try:
                    await page.wait_for_function(
                        "document.querySelector('#voice-view').dataset.state !== 'listening'",
                        timeout=8000, polling=100)
                    return ended
                except Exception:
                    print(f"{name}: not heard, saying it again", flush=True)
            raise RuntimeError(f"The app never heard {name}")

        async def narration_pause(name):
            mark(name)
            await page.wait_for_timeout(DURATIONS[name] * 1000 + 700)

        await page.goto(URL)
        await cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 92, "maxWidth": 1920,
                                                "maxHeight": 1080, "everyNthFrame": 1})
        mark("start")
        await page.locator("#voice-start").wait_for(state="visible", timeout=120_000)
        await page.wait_for_timeout(1000)
        await narration_pause("demo_intro")

        # Start talking: warmup and loading the voice detector are cut short in the edit.
        clicked = mark("voice_start")
        await page.click("#voice-start")
        await state_is("listening")
        waits.append([clicked + 1.5, mark("listening") - 0.5])

        # "I need to attach a document" opens the upload box on the voice screen.
        await student_says("say_attach")
        await page.locator("#upload-dialog[open]").wait_for(timeout=LONG)
        mark("upload_dialog")
        await state_is("listening", "reading")
        await page.wait_for_timeout(500)
        await narration_pause("demo_upload")
        dropped = mark("upload")
        await page.set_input_files("#upload-input", str(VIDEO / scenes.DEMO_DOCUMENT))
        # The dialog closes by itself once the document is ready.
        await page.wait_for_function("!document.querySelector('#upload-dialog').open", timeout=LONG, polling=200)
        await state_is("listening")
        waits.append([dropped + 1.5, mark("upload_done") - 1.5])

        # A spoken question about the lecture, answered aloud with the source shown.
        said = await student_says("say_question")
        await state_is("speaking")
        waits.append([said + 2.0, mark("answer_speaking") - 0.8])
        await state_is("listening")
        mark("answer_done")
        await page.wait_for_timeout(800)
        await narration_pause("demo_answer")

        # "Make a quiz": Yapperton says it is writing one, then the quiz panel opens.
        await student_says("say_quiz")
        await state_is("speaking")
        mark("quiz_wait_speaking")
        await page.locator("#voice-quiz").wait_for(state="visible", timeout=LONG)
        mark("quiz_shown")
        await state_is("listening")
        mark("quiz_done")
        await page.wait_for_timeout(800)
        mark("demo_quiz")
        questions = page.locator("#voice-quiz .quiz-question")
        await page.wait_for_timeout(2500)
        if await questions.count():
            await questions.nth(0).locator(".quiz-option").nth(0).click()
            await page.wait_for_timeout(3500)
            if await questions.count() > 1:
                await questions.nth(1).scroll_into_view_if_needed()
                await questions.nth(1).locator(".quiz-option").nth(1).click()
        await page.wait_for_timeout(max(3000, DURATIONS["demo_quiz"] * 1000 - 5000))
        mark("end")
        await cdp.send("Page.stopScreencast")
        await page.wait_for_timeout(500)
        await browser.close()

    for clip in clips:
        clip["stop"] = stops.get(clip["id"])
    (OUT / "timeline.json").write_text(json.dumps(
        {"frames": frames, "markers": markers, "clips": clips, "waits": waits}, indent=1))
    print(f"{len(frames)} frames, {len(clips)} audio clips")


if __name__ == "__main__":
    asyncio.run(main())
