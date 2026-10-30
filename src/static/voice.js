{
  const VAD_ASSETS = "/static/vendor/vad/";
  const PAUSE_MS = 1000;
  // Stays under the server's 4 MiB limit if noise keeps the detector listening.
  const MAX_SPEECH_MS = 110000;
  // Lets the room go quiet after a reply so the mic does not hear the speakers.
  const RESUME_DELAY_MS = 300;
  const LABELS = {
    loading: "Getting ready",
    listening: "Listening",
    transcribing: "Transcribing",
    thinking: "Thinking",
    speaking: "Speaking",
    error: "Something went wrong",
  };

  const openButton = document.querySelector("#voice-open");
  const view = document.querySelector("#voice-view");
  const statusLine = document.querySelector("#voice-status");
  const heard = document.querySelector("#voice-heard");
  const caption = document.querySelector("#voice-caption");
  const errorLine = document.querySelector("#voice-error");
  const skipButton = document.querySelector("#voice-skip");
  const endButton = document.querySelector("#voice-end");

  let active = false;
  let state = "loading";
  let micVad = null;
  let audioContext = null;
  let analyser = null;
  let turn = null;
  let speechTimer = null;
  let resumeTimer = null;

  function setState(next) {
    state = next;
    view.dataset.state = next;
    statusLine.textContent = LABELS[next];
    skipButton.disabled = !["thinking", "speaking"].includes(next);
    wisp.setState(next);
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
    const reply = { role: "assistant", content: current.spoken.join(" ") };
    messages.push(current.pending, reply);
    appendMessage("user", current.pending.content);
    appendMessage("assistant", reply.content, [], "general");
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
        if (event.type === "done") return;
        await scheduleSentence(current, event);
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
    const current = { pending: null, controller: new AbortController(), spoken: [], timers: [], sources: [], playEnd: 0 };
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
      setState("thinking");
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

  async function closeVoice() {
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
    wisp.stop();
    if (view.open) view.close();
    prompt.focus();
    try {
      await closingVad?.destroy();
    } finally {
      await closingContext?.close();
    }
  }

  async function openVoice() {
    if (active || busy) return;
    active = true;
    heard.textContent = "";
    caption.textContent = "";
    clearError();
    view.showModal();
    wisp.start(document.querySelector("#voice-wisp"));
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

  openButton.addEventListener("click", openVoice);
  endButton.addEventListener("click", closeVoice);
  skipButton.addEventListener("click", skip);
  view.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeVoice();
  });
  view.addEventListener("keydown", (event) => {
    if (event.code !== "Space") return;
    event.preventDefault();
    if (!event.repeat) skip();
  });

  fetch("/api/voice/status")
    .then((response) => response.json())
    .then((data) => {
      openButton.hidden = !data.available;
    })
    .catch(() => {});
}
