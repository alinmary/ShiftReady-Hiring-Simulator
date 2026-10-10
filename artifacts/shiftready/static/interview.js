document.addEventListener("DOMContentLoaded", () => {
  const root = document.querySelector(".candidate-shell");
  if (!root) return;
  const token = root.dataset.token;
  const intro = document.getElementById("candidateIntro");
  const app = document.getElementById("interview");
  const begin = document.getElementById("beginInterview");
  const introError = document.getElementById("introError");
  const callError = document.getElementById("callError");
  const replyForm = document.getElementById("replyForm");
  const replyText = document.getElementById("replyText");
  const sendButton = document.getElementById("sendReply");
  const micButton = document.getElementById("micButton");
  const steps = document.getElementById("scenarioSteps");
  const conversation = document.getElementById("conversation");
  const nextButton = document.getElementById("nextCall");
  const finishButton = document.getElementById("finishInterview");
  let session = null;
  let scenarioIndex = 0;
  let timerId = null;
  let scenarioStartedAt = 0;
  let recorder = null;
  let audioChunks = [];
  let audioStream = null;
  let audioContext = null;
  let analyser = null;
  let signalTimer = null;
  let rmsSamples = [];
  let quietSamples = 0;
  let candidateWords = 0;
  let spokenWords = 0;
  let candidateTurnCount = 0;
  let recognition = null;
  let recordingBlob = null;
  let currentScenarioHasReply = false;
  let scenarioCards = [];
  let liveCall = null;
  let liveConnected = false;
  let micMuted = false;
  let mixedDestination = null;
  let currentAudio = null;
  let customerAudioNodes = [];
  let nextCustomerAudioTime = 0;
  let candidateTranscript = "";
  let lastTypedText = "";
  let pendingTurns = [];
  let savingTurns = false;

  async function postJson(path, data) {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || body.error || "The request could not be completed.");
    return body;
  }

  function setStatus(text) {
    document.getElementById("customerStateText").textContent = text;
  }

  function addBubble(speaker, text) {
    const bubble = document.createElement("article");
    bubble.className = `bubble ${speaker}`;
    const label = document.createElement("span");
    label.className = "bubble-label";
    label.textContent = speaker === "customer" ? "CUSTOMER" : "YOU";
    const content = document.createElement("p");
    content.textContent = text;
    bubble.append(label, content);
    conversation.appendChild(bubble);
    conversation.scrollTop = conversation.scrollHeight;
  }

  async function savePendingTurns() {
    while (savingTurns) await new Promise((resolve) => setTimeout(resolve, 100));
    savingTurns = true;
    try {
      while (pendingTurns.length) {
        await postJson("/sr-api/session/live-turn", pendingTurns[0]);
        pendingTurns.shift();
      }
    } finally { savingTurns = false; }
  }

  function queueTurn(speaker, text, index = scenarioIndex, extra = {}) {
    pendingTurns.push({
      session_id: session.id, scenario_index: index, speaker, text,
      elapsed_seconds: Math.max(0, (Date.now() - interviewStartedAt) / 1000),
      ...extra,
    });
    savePendingTurns().catch(() => {
      callError.textContent = "The transcript could not be saved. It will retry before you move to the next call.";
    });
  }

  function countCandidate(text) {
    candidateWords += text.split(/\s+/).filter(Boolean).length;
    candidateTurnCount += 1;
    candidateTranscript += ` ${text}`;
    currentScenarioHasReply = true;
  }

  function stopCustomerAudio() {
    currentAudio?.pause();
    customerAudioNodes.forEach((node) => { try { node.stop(); } catch (_) {} });
    customerAudioNodes = [];
    nextCustomerAudioTime = audioContext?.currentTime || 0;
  }

  function recordCustomerAudio(base64Audio) {
    if (!audioContext || !mixedDestination) return;
    const raw = atob(base64Audio);
    const samples = new Int16Array(raw.length / 2);
    const bytes = new Uint8Array(samples.buffer);
    for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
    const buffer = audioContext.createBuffer(1, samples.length, 16000);
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < samples.length; i++) channel[i] = samples[i] / 32768;
    const source = audioContext.createBufferSource();
    source.buffer = buffer;
    source.connect(mixedDestination);
    const start = Math.max(audioContext.currentTime, nextCustomerAudioTime);
    source.start(start);
    nextCustomerAudioTime = start + buffer.duration;
    customerAudioNodes.push(source);
    source.onended = () => { customerAudioNodes = customerAudioNodes.filter((item) => item !== source); };
  }

  async function renderScenario() {
    const item = scenarioCards[scenarioIndex];
    document.getElementById("scenarioLabel").textContent = `CALL ${scenarioIndex + 1} OF ${scenarioCards.length}`;
    document.getElementById("scenarioTitle").textContent = item.title;
    document.getElementById("scenarioBrief").textContent = item.brief;
    steps.querySelectorAll(".scenario-step").forEach((step, index) => {
      step.classList.toggle("active", index === scenarioIndex);
      step.classList.toggle("done", index < scenarioIndex);
    });
    conversation.innerHTML = "";
    currentScenarioHasReply = false;
    nextButton.classList.toggle("hidden", scenarioIndex >= scenarioCards.length - 1);
    finishButton.classList.toggle("hidden", scenarioIndex < scenarioCards.length - 1);
    replyText.focus();
    sendButton.disabled = false;
    callError.textContent = "";
    scenarioStartedAt = Date.now();
    startTimer();
    liveConnected = false;
    lastTypedText = "";
    if (audioStream && window.LiveCustomerCall) {
      const index = scenarioIndex;
      try {
        setStatus("Connecting your live customer call");
        liveCall = new window.LiveCustomerCall({
          voiceId: app.dataset.voiceId, scenario: item,
          onMessage: (speaker, text) => {
            if (speaker === "candidate" && text === lastTypedText) { lastTypedText = ""; return; }
            addBubble(speaker, text);
            if (speaker === "candidate") {
              spokenWords += text.split(/\s+/).filter(Boolean).length;
              countCandidate(text);
            }
            queueTurn(speaker, text, index);
          },
          onAudio: recordCustomerAudio,
          onInterrupt: stopCustomerAudio,
          onCorrection: (original, corrected) => {
            const text = corrected || "[Customer was interrupted]";
            const paragraphs = [...conversation.querySelectorAll(".bubble.customer p")];
            const paragraph = paragraphs.reverse().find((item) => item.textContent === original);
            if (paragraph) paragraph.textContent = text;
            queueTurn("customer", text, index, { original_text: original });
          },
          onStatus: (text) => {
            setStatus(text);
            if (text.startsWith("Call disconnected")) liveConnected = false;
          },
          onError: (message) => {
            callError.textContent = `Live voice: ${message}. Typed replies remain available.`;
            liveConnected = false;
          },
        });
        await liveCall.start();
        liveConnected = true;
        micMuted = false;
        micButton.textContent = "Mute microphone";
        document.getElementById("speechSupport").textContent = "Live call connected. Speak naturally; no Send button needed.";
        return;
      } catch (error) {
        await liveCall?.stop().catch(() => {});
        liveCall = null;
        callError.textContent = `${error.message} Continuing in turn-based voice mode.`;
      }
    }
    addBubble("customer", item.opening);
    queueTurn("customer", item.opening);
    await savePendingTurns();
    micButton.textContent = "Speak";
    document.getElementById("speechSupport").textContent = recognition ? "Speak, then send your reply" : "Type your reply";
    speak(item.opening);
  }

  function startTimer() {
    clearInterval(timerId);
    const timer = document.getElementById("timer");
    timerId = setInterval(() => {
      const remaining = Math.max(0, 240 - Math.floor((Date.now() - scenarioStartedAt) / 1000));
      timer.textContent = `${String(Math.floor(remaining / 60)).padStart(2, "0")}:${String(remaining % 60).padStart(2, "0")}`;
      if (remaining === 0) {
        clearInterval(timerId);
        callError.textContent = "Time is up for this call. You can continue to the next one.";
        nextButton.classList.toggle("hidden", scenarioIndex >= scenarioCards.length - 1);
        finishButton.classList.toggle("hidden", scenarioIndex < scenarioCards.length - 1);
      }
    }, 250);
  }

  async function speak(text) {
    try {
      setStatus("Customer is speaking");
      const voiceId = document.getElementById("interview").dataset.voiceId;
      if (!voiceId) { setStatus("Customer reply ready"); return; }
      const response = await fetch("/api/elevenlabs/tts", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, voice_id: voiceId }),
      });
      if (!response.ok) throw new Error("ElevenLabs speech is unavailable.");
      stopCustomerAudio();
      const url = URL.createObjectURL(await response.blob());
      const audio = new Audio(url);
      currentAudio = audio;
      if (audioContext && mixedDestination) {
        const source = audioContext.createMediaElementSource(audio);
        source.connect(mixedDestination);
        source.connect(audioContext.destination);
      }
      audio.onended = () => { setStatus("Your customer is ready"); URL.revokeObjectURL(url); };
      audio.onerror = () => setStatus("Customer reply ready");
      await audio.play();
    } catch (_error) {
      setStatus("Customer reply ready — read the text and continue");
    }
  }

  async function loadVoice() {
    const response = await fetch("/api/elevenlabs/voices");
    if (!response.ok) throw new Error("ElevenLabs connection could not be reached.");
    const body = await response.json();
    const voices = body.voices || [];
    const pick = voices.find((voice) => /indian|south asian/i.test(`${voice.name} ${JSON.stringify(voice.labels || {})}`)) || voices[0];
    if (!pick?.voice_id) throw new Error("No voices are available in the connected ElevenLabs account.");
    app.dataset.voiceId = pick.voice_id;
  }

  async function prepareAudio() {
    audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioContext = new AudioContext();
    await audioContext.resume();
    const source = audioContext.createMediaStreamSource(audioStream);
    mixedDestination = audioContext.createMediaStreamDestination();
    source.connect(mixedDestination);
    const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((type) => MediaRecorder.isTypeSupported(type));
    recorder = new MediaRecorder(mixedDestination.stream, mime ? { mimeType: mime } : undefined);
    recorder.ondataavailable = (event) => { if (event.data.size) audioChunks.push(event.data); };
    recorder.start(1000);
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);
    const buffer = new Uint8Array(analyser.fftSize);
    signalTimer = setInterval(() => {
      if (!analyser) return;
      analyser.getByteTimeDomainData(buffer);
      let sum = 0;
      for (const sample of buffer) {
        const normalized = (sample - 128) / 128;
        sum += normalized * normalized;
      }
      const rms = Math.sqrt(sum / buffer.length);
      rmsSamples.push(rms);
      if (rms < 0.018) quietSamples += 1;
    }, 100);
    document.getElementById("recordState").textContent = "Recording";
  }

  function finishRecording() {
    return new Promise((resolve) => {
      if (!recorder || recorder.state === "inactive") { resolve(recordingBlob); return; }
      recorder.onstop = () => {
        recordingBlob = new Blob(audioChunks, { type: recorder.mimeType || "audio/webm" });
        resolve(recordingBlob);
      };
      recorder.stop();
      clearInterval(signalTimer);
      if (audioStream) audioStream.getTracks().forEach((track) => track.stop());
      if (audioContext) audioContext.close().catch(() => {});
    });
  }

  async function sendReply(event) {
    event.preventDefault();
    const text = replyText.value.trim();
    if (!text || !session) return;
    callError.textContent = "";
    sendButton.disabled = true;
    micButton.disabled = true;
    addBubble("candidate", text);
    if (liveConnected && liveCall) {
      lastTypedText = text;
      liveCall.send(text);
      countCandidate(text);
      queueTurn("candidate", text);
      replyText.value = "";
      sendButton.disabled = false;
      micButton.disabled = false;
      return;
    }
    try {
      setStatus("Customer is responding");
      const elapsed = Math.max(0, Math.floor((Date.now() - new Date(session.startedAt).getTime()) / 1000));
      const result = await postJson("/sr-api/session/turn", {
        session_id: session.id,
        scenario_index: scenarioIndex,
        text,
        elapsed_seconds: elapsed,
      });
      addBubble("customer", result.reply);
      countCandidate(text);
      replyText.value = "";
      await speak(result.reply);
    } catch (error) {
      callError.textContent = error.message;
    } finally {
      sendButton.disabled = false;
      micButton.disabled = false;
      replyText.focus();
    }
  }

  async function advance() {
    if (!currentScenarioHasReply) {
      callError.textContent = "Please respond to the customer before moving on.";
      return;
    }
    clearInterval(timerId);
    nextButton.disabled = true;
    await liveCall?.stop();
    liveCall = null;
    liveConnected = false;
    stopCustomerAudio();
    try { await savePendingTurns(); }
    catch (_) { callError.textContent = "Your transcript could not be saved. Please try Next call again."; nextButton.disabled = false; return; }
    scenarioIndex += 1;
    if (scenarioIndex < scenarioCards.length) await renderScenario();
    nextButton.disabled = false;
  }

  function makeSignals() {
    const candidateTurns = candidateTurnCount || 1;
    return {
      label: "Browser microphone analysis; approximate, not a voice-identity or accent assessment.",
      estimated_words_per_minute: Math.round(candidateWords / Math.max(1, (Date.now() - interviewStartedAt) / 60000)),
      mean_microphone_rms: rmsSamples.length ? Number((rmsSamples.reduce((a, b) => a + b, 0) / rmsSamples.length).toFixed(4)) : null,
      estimated_quiet_seconds: Math.round(quietSamples / 10),
      filler_word_count: candidateTranscript.match(/\b(um|uh|erm)\b/gi)?.length || 0,
      audio_recorded: Boolean(recordingBlob?.size),
      spoken_word_count: spokenWords,
      candidate_turn_count: candidateTurns,
      limitations: "Relative microphone level and silence estimates include room noise and may be affected by microphone placement. Accent and fluency are not scored.",
    };
  }

  let interviewStartedAt = Date.now();

  async function complete() {
    if (!currentScenarioHasReply) {
      callError.textContent = "Please respond to the customer before finishing.";
      return;
    }
    clearInterval(timerId);
    nextButton.disabled = true;
    finishButton.disabled = true;
    sendButton.disabled = true;
    micButton.disabled = true;
    replyText.disabled = true;
    setStatus("Saving your interview");
    try {
      await liveCall?.stop();
      liveCall = null;
      liveConnected = false;
      stopCustomerAudio();
      await savePendingTurns();
      const blob = await finishRecording();
      if (blob?.size) {
        const form = new FormData();
        form.append("session_id", session.id);
        const extension = blob.type.includes("mp4") ? "recording.mp4" : "recording.webm";
        form.append("audio", blob, extension);
        const upload = await fetch("/sr-api/session/audio", { method: "POST", body: form });
        if (!upload.ok) throw new Error("Your recording could not be saved. Please retry.");
      }
      const result = await postJson("/sr-api/session/complete", {
        session_id: session.id,
        voice_signals: makeSignals(),
      });
      app.classList.add("hidden");
      document.getElementById("completeScreen").classList.remove("hidden");
      document.getElementById("completeScreen").dataset.reportUrl = result.report_url;
    } catch (error) {
      callError.textContent = error.message;
      nextButton.disabled = false;
      finishButton.disabled = false;
    }
  }

  begin.addEventListener("click", async () => {
    begin.disabled = true;
    introError.textContent = "";
    try {
      await loadVoice();
      const response = await postJson("/sr-api/session/start", { token });
      session = { id: response.session_id, startedAt: new Date().toISOString() };
      scenarioCards = response.scenarios;
      const available = Boolean(navigator.mediaDevices?.getUserMedia && window.MediaRecorder);
      if (available) {
        try { await prepareAudio(); }
        catch (_error) { document.getElementById("recordState").textContent = "Microphone unavailable — typed responses allowed"; }
      } else {
        document.getElementById("recordState").textContent = "Recording not supported";
      }
      const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (SpeechRecognition) {
        recognition = new SpeechRecognition();
        recognition.lang = "en-IN";
        recognition.interimResults = false;
        recognition.onresult = (event) => {
          const heard = event.results[0][0].transcript.trim();
           spokenWords += heard.split(/\s+/).filter(Boolean).length;
          replyText.value = `${replyText.value} ${heard}`.trim();
        };
        recognition.onerror = () => { document.getElementById("speechSupport").textContent = "Speech recognition unavailable; type your reply."; };
        recognition.onend = () => { if (!liveConnected) document.getElementById("speechSupport").textContent = "Reply captured. Press Send when ready."; };
        document.getElementById("speechSupport").textContent = "Speech recognition ready";
      } else {
        document.getElementById("speechSupport").textContent = "Type your reply";
      }
      intro.classList.add("hidden");
      app.classList.remove("hidden");
      interviewStartedAt = Date.now();
      steps.innerHTML = "";
      scenarioCards.forEach((scenario, index) => {
        const step = document.createElement("div");
        step.className = "scenario-step";
        const number = document.createElement("span");
        number.textContent = String(index + 1).padStart(2, "0");
        const label = document.createElement("div");
        const title = document.createElement("strong");
        title.textContent = scenario.title;
        const subtitle = document.createElement("small");
        subtitle.textContent = "Customer call";
        label.append(title, subtitle);
        step.append(number, label);
        steps.appendChild(step);
      });
      await renderScenario();
    } catch (error) {
      introError.textContent = error.message;
      begin.disabled = false;
    }
  });

  micButton.addEventListener("click", () => {
    if (liveConnected && liveCall) {
      micMuted = !micMuted;
      liveCall.mute(micMuted);
      micButton.textContent = micMuted ? "Unmute microphone" : "Mute microphone";
      return;
    }
    if (!recognition) {
      document.getElementById("speechSupport").textContent = "Speech recognition isn't supported in this browser. Type your reply.";
      return;
    }
    try { recognition.start(); } catch (_error) {}
    document.getElementById("speechSupport").textContent = "Listening…";
  });
  replyForm.addEventListener("submit", sendReply);
  nextButton.addEventListener("click", advance);
  finishButton.addEventListener("click", complete);
});
