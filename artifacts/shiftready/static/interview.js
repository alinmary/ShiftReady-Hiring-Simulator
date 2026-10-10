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
  let candidateTurnCount = 0;
  let recognition = null;
  let recordingBlob = null;
  let currentScenarioHasReply = false;
  let scenarioCards = [];

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

  function renderScenario() {
    const item = scenarioCards[scenarioIndex];
    document.getElementById("scenarioLabel").textContent = `CALL ${scenarioIndex + 1} OF ${scenarioCards.length}`;
    document.getElementById("scenarioTitle").textContent = item.title;
    document.getElementById("scenarioBrief").textContent = item.brief;
    steps.querySelectorAll(".scenario-step").forEach((step, index) => {
      step.classList.toggle("active", index === scenarioIndex);
      step.classList.toggle("done", index < scenarioIndex);
    });
    conversation.innerHTML = "";
    addBubble("customer", item.opening);
    currentScenarioHasReply = false;
    nextButton.classList.toggle("hidden", scenarioIndex >= scenarioCards.length - 1);
    finishButton.classList.toggle("hidden", scenarioIndex < scenarioCards.length - 1);
    replyText.focus();
    speak(item.opening);
    scenarioStartedAt = Date.now();
    startTimer();
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
        nextButton.classList.remove("hidden");
        finishButton.classList.toggle("hidden", scenarioIndex < scenarioCards.length - 1);
        sendButton.disabled = true;
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
      const audio = new Audio(URL.createObjectURL(await response.blob()));
      audio.onended = () => setStatus("Your customer is ready");
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
    const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((type) => MediaRecorder.isTypeSupported(type));
    recorder = new MediaRecorder(audioStream, mime ? { mimeType: mime } : undefined);
    recorder.ondataavailable = (event) => { if (event.data.size) audioChunks.push(event.data); };
    recorder.start(1000);
    audioContext = new AudioContext();
    const source = audioContext.createMediaStreamSource(audioStream);
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
    candidateWords += text.split(/\s+/).filter(Boolean).length;
    candidateTurnCount += 1;
    try {
      setStatus("Customer is responding");
      const elapsed = Math.max(0, Math.floor((Date.now() - new Date(session.startedAt).getTime()) / 1000));
      const result = await postJson("/api/session/turn", {
        session_id: session.id,
        scenario_index: scenarioIndex,
        text,
        elapsed_seconds: elapsed,
      });
      addBubble("customer", result.reply);
      currentScenarioHasReply = true;
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
    scenarioIndex += 1;
    if (scenarioIndex < scenarioCards.length) renderScenario();
  }

  function makeSignals() {
    const candidateTurns = candidateTurnCount || 1;
    return {
      label: "Browser microphone analysis; approximate, not a voice-identity or accent assessment.",
      estimated_words_per_minute: Math.round(candidateWords / Math.max(1, (Date.now() - interviewStartedAt) / 60000)),
      mean_microphone_rms: rmsSamples.length ? Number((rmsSamples.reduce((a, b) => a + b, 0) / rmsSamples.length).toFixed(4)) : null,
      estimated_quiet_seconds: Math.round(quietSamples / 10),
      filler_word_count: (window.candidateTranscript || "").match(/\b(um|uh|erm|like)\b/gi)?.length || 0,
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
    setStatus("Saving your interview");
    try {
      const blob = await finishRecording();
      if (blob?.size) {
        const form = new FormData();
        form.append("session_id", session.id);
        const extension = blob.type.includes("mp4") ? "recording.mp4" : "recording.webm";
        form.append("audio", blob, extension);
        await fetch("/api/session/audio", { method: "POST", body: form });
      }
      const result = await postJson("/api/session/complete", {
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
      const response = await postJson("/api/session/start", { token });
      session = { id: response.session_id, startedAt: new Date().toISOString() };
      scenarioCards = response.scenarios;
      const available = Boolean(navigator.mediaDevices?.getUserMedia && window.MediaRecorder);
      if (available) {
        await prepareAudio();
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
          replyText.value = `${replyText.value} ${heard}`.trim();
          window.candidateTranscript = `${window.candidateTranscript || ""} ${heard}`;
        };
        recognition.onerror = () => { document.getElementById("speechSupport").textContent = "Speech recognition unavailable; type your reply."; };
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
        step.innerHTML = `<span>${String(index + 1).padStart(2, "0")}</span><div><strong>${scenario.title}</strong><small>Customer call</small></div>`;
        steps.appendChild(step);
      });
      renderScenario();
    } catch (error) {
      introError.textContent = error.message;
      begin.disabled = false;
    }
  });

  micButton.addEventListener("click", () => {
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
