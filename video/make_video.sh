#!/bin/sh
# Build the presentation video. The app must already run at http://127.0.0.1:5050 and the demo
# document must not be uploaded yet (the recording uploads it through voice mode).
# Output: .tmp/video/yapperton_presentation.mp4 and .srt. To re-edit without re-recording, edit
# video/scenes.py and run only: narrate.py <changed ids>, slides.py, build.py.
set -e
cd "$(dirname "$0")/.."
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.tmp/ms-playwright"
.venv/bin/python video/narrate.py
.venv/bin/python video/slides.py
# The recorder paces itself by the narration lengths; keep the lengths it used.
cp .tmp/video/audio/durations.json .tmp/video/durations_for_recording.json
.venv/bin/python video/record_demo.py
.venv/bin/python video/transcribe_clips.py
.venv/bin/python video/build.py
