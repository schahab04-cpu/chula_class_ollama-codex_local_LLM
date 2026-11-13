{
  const VAD_ASSETS = "/static/vendor/vad/";
  const PAUSE_MS = 1000;
  // Stays under the server's 4 MiB limit if noise keeps the detector listening.
  const MAX_SPEECH_MS = 110000;
  // Lets the room go quiet after a reply so the mic does not hear the speakers.
  const RESUME_DELAY_MS = 300;
  // Quick replies start speaking before this; only slower ones get a thinking filler.
  const FILLER_DELAY_MS = 1200;
  // Document answers wait for retrieval and passage selection; a second filler covers that.
  const SECOND_FILLER_MS = 4000;
  const LABELS = {
    ready: "Ready when you are",
    reading: "Reading your documents",
    unavailable: "Voice is not set up",
    loading: "Getting ready",
    listening: "Listening",
    transcribing: "Transcribing",
    thinking: "Thinking",
    speaking: "Speaking",
    muted: "Muted",
    error: "Something went wrong",
  };

  const startButton = document.querySelector("#voice-start");
  const unavailableLine = document.querySelector("#voice-unavailable");
  const controls = document.querySelector("#voice-controls");
  const sourcesLine = document.querySelector("#voice-sources");
  const quizPanel = document.querySelector("#voice-quiz");
  const quizBody = document.querySelector("#voice-quiz-body");
  const workspace = document.querySelector("#workspace");
  const workspaceOpen = document.querySelector("#workspace-open");
  const workspaceClose = document.querySelector("#workspace-close");
  const view = document.querySelector("#voice-view");
  const statusLine = document.querySelector("#voice-status");
  const heard = document.querySelector("#voice-heard");
  const caption = document.querySelector("#voice-caption");
  const errorLine = document.querySelector("#voice-error");
  const skipButton = document.querySelector("#voice-skip");
  const endButton = document.querySelector("#voice-end");
  const muteButton = document.querySelector("#voice-mute");

  let active = false;
  let state = "loading";
  let micVad = null;
  let audioContext = null;
  let analyser = null;
  let turn = null;
  let speechTimer = null;
  let resumeTimer = null;
  let muted = false;
  let fillers = [];
  let lastFiller = null;
  let voiceAvailable = false;
  // Set while the server indexes or summarizes documents: the mic stays off until it is done.
  let reading = "";

  function setState(next) {
    state = next;
    view.dataset.state = next;
    statusLine.textContent = next === "reading" && reading ? reading : LABELS[next];
    skipButton.disabled = !["thinking", "speaking"].includes(next);
    wisp.setState(next === "unavailable" ? "muted" : next);
  }

  function showError(message) {
    errorLine.textContent = message;
    errorLine.hidden = false;
  }

  function clearError() {
    errorLine.hidden = true;
  }

  function encodeWav(samples) {
    const bytes = new DataView(new ArrayBuffer(44 + samples.length * 2));
    const writeText = (offset, text) => {
      for (let index = 0; index < text.length; index += 1) {
        bytes.setUint8(offset + index, text.charCodeAt(index));
      }
    };
    writeText(0, "RIFF");
    bytes.setUint32(4, 36 + samples.length * 2, true);
    writeText(8, "WAVEfmt ");
    bytes.setUint32(16, 16, true);
    bytes.setUint16(20, 1, true);
    bytes.setUint16(22, 1, true);
    bytes.setUint32(24, 16000, true);
    bytes.setUint32(28, 32000, true);
    bytes.setUint16(32, 2, true);
    bytes.setUint16(34, 16, true);
    writeText(36, "data");
    bytes.setUint32(40, samples.length * 2, true);
    samples.forEach((sample, index) => {
      const clipped = Math.max(-1, Math.min(1, sample));
      bytes.setInt16(44 + index * 2, clipped * 32767, true);
    });
    return bytes.buffer;
  }

  function clearSpeechTimer() {
    clearTimeout(speechTimer);
    speechTimer = null;
  }

  async function listen() {
    if (!active) return;
    clearTimeout(resumeTimer);
    resumeTimer = null;
    if (reading) {
      setState("reading");
      return;
    }
    if (muted) {
      setState("muted");
      return;
    }
    setState("listening");
    try {
      await micVad.start();
    } catch {
      showError("Cannot use the microphone. Check its permission, then start voice again.");
      setState("error");
    }
  }

  function listenSoon() {
    clearTimeout(resumeTimer);
    resumeTimer = setTimeout(listen, RESUME_DELAY_MS);
  }

  function showMute() {
    muteButton.firstChild.textContent = muted ? "Unmute " : "Mute ";
    muteButton.setAttribute("aria-pressed", String(muted));
  }

  async function toggleMute() {
    if (!micVad) return;
    muted = !muted;
    showMute();
    if (muted && state === "listening") {
      clearSpeechTimer();
      setState("muted");
      await micVad.pause();
    } else if (!muted && state === "muted" && !reading) {
      await listen();
    }
  }

  async function loadFillers() {
    try {
      const response = await fetch("/api/voice/fillers");
      if (!response.ok) return [];
      const data = await response.json();
      return await Promise.all(data.fillers.map(({ audio }) => {
        const encoded = Uint8Array.from(atob(audio), (character) => character.charCodeAt(0));
        return audioContext.decodeAudioData(encoded.buffer);
      }));
    } catch {
      return [];
    }
  }

  // Fills the silence while the model thinks; never captioned or kept in history.
  function playFiller(current) {
    const choices = fillers.filter((buffer) => buffer !== lastFiller);
    if (!choices.length) return;
    const buffer = choices[Math.floor(Math.random() * choices.length)];
    lastFiller = buffer;
    const source = audioContext.createBufferSource();
    source.buffer = buffer;
    source.connect(analyser);
    const startAt = audioContext.currentTime + 0.05;
    source.start(startAt);
    current.playEnd = startAt + buffer.duration;
    current.sources.push(source);
  }

  function stopTurnAudio(current) {
    current.timers.forEach(clearTimeout);
    current.sources.forEach((source) => {
      source.onended = null;
      source.stop();
    });
  }

  // Keeps only what was actually heard, so the model's memory matches the conversation.
  function commitTurn(current) {
    if (!current.spoken.length) return;
    const reply = { role: "assistant", content: current.spoken.join(" "), mode: current.mode };
    messages.push(current.pending, reply);
    appendMessage("user", current.pending.content);
    appendMessage("assistant", reply.content, current.citations, current.mode, current.quiz);
    showSources(current.citations);
  }

  // Names the documents an answer came from; the full passages are in Chat & documents.
  function showSources(citations) {
    const names = [...new Set(citations.map((source) => `${source.name}, ${source.location}`))];
    sourcesLine.textContent = names.length ? `From ${names.join(" · ")}` : "";
  }

  function finishTurn() {
    const current = turn;
    turn = null;
    if (!current) return;
    current.controller.abort();
    stopTurnAudio(current);
    commitTurn(current);
  }

  async function scheduleSentence(current, event) {
    const encoded = Uint8Array.from(atob(event.audio), (character) => character.charCodeAt(0));
    const buffer = await audioContext.decodeAudioData(encoded.buffer);
    if (turn !== current) return;
    current.answered = true;
    const source = audioContext.createBufferSource();
    source.buffer = buffer;
    source.connect(analyser);
    const startAt = Math.max(audioContext.currentTime + 0.05, current.playEnd);
    source.start(startAt);
    current.playEnd = startAt + buffer.duration;
    current.sources.push(source);
    current.timers.push(setTimeout(() => {
      current.spoken.push(event.text);
      caption.textContent = event.text;
      if (state !== "speaking") setState("speaking");
    }, (startAt - audioContext.currentTime) * 1000));
  }

  async function streamReply(current) {
    const response = await fetch("/api/voice/reply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: [...messages, current.pending] }),
      signal: current.controller.signal,
    });
    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.error || "The request failed. Please try again.");
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) throw new Error("The reply stopped early. Please try again.");
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) {
        const event = JSON.parse(line);
        if (event.type === "error") throw new Error(event.message);
        if (event.type === "sources") {
          current.citations = event.sources;
        } else if (event.type === "upload") {
          openUploadDialog();
        } else if (event.type === "quiz") {
          current.quiz = event.quiz;
          showQuiz(event.quiz);
        } else if (event.type === "done") {
          current.mode = event.mode || "general";
          return;
        } else {
          await scheduleSentence(current, event);
        }
      }
    }
  }

  async function runReply(current) {
    try {
      await streamReply(current);
      const remaining = (current.playEnd - audioContext.currentTime) * 1000;
      await new Promise((resolve) => {
        current.timers.push(setTimeout(resolve, Math.max(0, remaining)));
      });
    } catch (failure) {
      if (turn !== current) return;
      showError(failure instanceof TypeError
        ? "Cannot reach the chat server. Check that Flask is running."
        : failure.message);
    }
    if (turn !== current) return;
    finishTurn();
    listenSoon();
  }

  async function handleSpeech(samples) {
    if (!active || state !== "listening") return;
    clearSpeechTimer();
    setState("transcribing");
    await micVad.pause();
    const current = {
      pending: null, controller: new AbortController(), spoken: [], timers: [], sources: [], playEnd: 0,
      answered: false, citations: [], mode: "general", quiz: null,
    };
    turn = current;
    try {
      const response = await fetch("/api/voice/transcribe", {
        method: "POST",
        headers: { "Content-Type": "audio/wav" },
        body: encodeWav(samples),
        signal: current.controller.signal,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Could not transcribe that. Please try again.");
      if (turn !== current) return;
      if (!data.text) {
        turn = null;
        await listen();
        return;
      }
      current.pending = { role: "user", content: data.text };
      heard.textContent = data.text;
      caption.textContent = "";
      sourcesLine.textContent = "";
      setState("thinking");
      current.timers.push(setTimeout(() => {
        if (turn === current && !current.sources.length) playFiller(current);
      }, FILLER_DELAY_MS));
      current.timers.push(setTimeout(() => {
        if (turn === current && !current.answered) playFiller(current);
      }, FILLER_DELAY_MS + SECOND_FILLER_MS));
    } catch (failure) {
      if (turn !== current) return;
      turn = null;
      showError(failure instanceof TypeError
        ? "Cannot reach the chat server. Check that Flask is running."
        : failure.message);
      await listen();
      return;
    }
    await runReply(current);
  }

  function skip() {
    if (skipButton.disabled) return;
    finishTurn();
    caption.textContent = "";
    listen();
  }

  function showIdle() {
    controls.hidden = true;
    startButton.hidden = !voiceAvailable;
    startButton.disabled = Boolean(reading);
    setState(!voiceAvailable ? "unavailable" : reading ? "reading" : "ready");
  }

  // Documents being read pause the conversation: the mic turns off between turns and
  // comes back when reading finishes. A reply already under way is allowed to finish.
  document.addEventListener("documents-busy", async (event) => {
    reading = event.detail.busy ? (event.detail.detail || LABELS.reading) : "";
    if (!active) {
      if (voiceAvailable) showIdle();
      return;
    }
    if (reading && ["listening", "muted", "reading"].includes(state)) {
      clearSpeechTimer();
      await micVad?.pause();
      setState("reading");
    } else if (!reading && state === "reading") {
      await listen();
    }
  });

  async function endSession() {
    if (!active) return;
    active = false;
    clearSpeechTimer();
    clearTimeout(resumeTimer);
    finishTurn();
    const closingVad = micVad;
    const closingContext = audioContext;
    micVad = null;
    audioContext = null;
    analyser = null;
    wisp.setAnalyser(null);
    showIdle();
    if (!workspace.open) startButton.focus();
    try {
      await closingVad?.destroy();
    } finally {
      await closingContext?.close();
    }
  }

  async function startSession() {
    if (active || busy || reading || !voiceAvailable) return;
    active = true;
    muted = false;
    showMute();
    fillers = [];
    heard.textContent = "";
    caption.textContent = "";
    sourcesLine.textContent = "";
    clearError();
    startButton.hidden = true;
    controls.hidden = false;
    endButton.focus();
    setState("loading");
    // Created inside the click so the browser allows it to play.
    audioContext = new AudioContext();
    analyser = audioContext.createAnalyser();
    analyser.connect(audioContext.destination);
    wisp.setAnalyser(analyser);
    try {
      await audioContext.resume();
      const warmup = await fetch("/api/voice/warmup", { method: "POST" });
      if (!warmup.ok) throw new Error((await warmup.json()).error);
      if (!active) return;
      fillers = await loadFillers();
      if (!active) return;
      const created = await vad.MicVAD.new({
        model: "v6",
        baseAssetPath: VAD_ASSETS,
        onnxWASMBasePath: VAD_ASSETS,
        startOnLoad: false,
        positiveSpeechThreshold: 0.5,
        negativeSpeechThreshold: 0.35,
        redemptionMs: PAUSE_MS,
        preSpeechPadMs: 300,
        minSpeechMs: 300,
        submitUserSpeechOnPause: true,
        ortConfig: (runtime) => {
          runtime.env.logLevel = "error";
          // Threads need cross-origin isolation, which this app does not set up.
          runtime.env.wasm.numThreads = 1;
        },
        onFrameProcessed: (probabilities, frame) => {
          if (state === "listening") wisp.setMic(frame, probabilities.isSpeech);
        },
        onSpeechStart: () => {
          clearError();
          wisp.cue("speech-start");
        },
        onSpeechRealStart: () => {
          speechTimer = setTimeout(() => micVad?.pause(), MAX_SPEECH_MS);
        },
        onVADMisfire: () => {
          clearSpeechTimer();
          wisp.cue("misfire");
        },
        onSpeechEnd: handleSpeech,
      });
      if (!active) {
        await created.destroy();
        return;
      }
      micVad = created;
      await listen();
    } catch (failure) {
      if (!active) return;
      showError(failure.name === "NotAllowedError"
        ? "Allow microphone access for this page, then start voice again."
        : failure instanceof TypeError
          ? "Cannot reach the chat server. Check that Flask is running."
          : failure.message || "Voice mode could not start.");
      setState("error");
    }
  }

  // The quiz stays on the voice screen while the conversation continues; answers are clicked.
  function showQuiz(quiz) {
    quizBody.replaceChildren(renderQuiz(quiz));
    quizPanel.hidden = false;
    quizPanel.scrollTop = 0;
  }

  function openWorkspace() {
    // The mic would keep listening behind the panel, so typing ends the voice session.
    endSession();
    workspace.showModal();
    prompt.focus();
  }

  startButton.addEventListener("click", startSession);
  endButton.addEventListener("click", endSession);
  skipButton.addEventListener("click", skip);
  muteButton.addEventListener("click", toggleMute);
  workspaceOpen.addEventListener("click", openWorkspace);
  document.querySelector("#voice-quiz-close").addEventListener("click", () => {
    quizPanel.hidden = true;
  });
  workspaceClose.addEventListener("click", () => workspace.close());
  workspace.addEventListener("close", () => (voiceAvailable ? startButton : workspaceOpen).focus());
  document.addEventListener("keydown", (event) => {
    // Shortcuts belong to the voice screen only, never to the chat panel or previews.
    if (document.querySelector("dialog[open]") || event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.code === "Escape" && active) {
      event.preventDefault();
      endSession();
    } else if (event.code === "KeyM" && active) {
      event.preventDefault();
      if (!event.repeat) toggleMute();
    } else if (event.code === "Space" && !(event.target instanceof HTMLButtonElement)) {
      event.preventDefault();
      if (event.repeat) return;
      if (active) skip();
      else startSession();
    }
  });

  wisp.start(document.querySelector("#voice-wisp"));
  setState("loading");
  fetch("/api/voice/status")
    .then((response) => response.json())
    .then((data) => {
      voiceAvailable = Boolean(data.available);
      unavailableLine.textContent = voiceAvailable ? "" : `${data.reason} Until then, use Chat & documents.`;
      unavailableLine.hidden = voiceAvailable;
      showIdle();
      if (voiceAvailable) startButton.focus();
    })
    .catch(() => {
      unavailableLine.textContent = "Cannot reach the app server. Check that it is running, then reload.";
      unavailableLine.hidden = false;
      showIdle();
    });
}
