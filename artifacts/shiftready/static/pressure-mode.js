/* Only instantiated for Round 2 Pressure Mode; standard calls are untouched. */
class PressureMode {
  constructor(options) {
    this.options = options;
    this.index = 0;
    this.responses = 0;
    this.lastResponses = 0;
    this.onHold = false;
    this.busy = false;
    this.stopped = false;
    this.delayed = new Set();
    this.clips = new Map();
    this.audio = null;
    this.panel = document.createElement("section");
    this.panel.className = "pressure-live";
    this.panel.setAttribute("aria-live", "polite");
    this.panel.innerHTML = '<p class="eyebrow">PRESSURE MODE · TIMED INTERRUPTIONS</p><p class="pressure-status">Customer complaint → staff priorities → return to the original customer.</p><ol class="pressure-events"></ol>';
    document.getElementById("conversation").before(this.panel);
    this.status = this.panel.querySelector(".pressure-status");
    this.list = this.panel.querySelector("ol");
    for (const event of options.previousEvents) {
      const row = document.createElement("li");
      const label = document.createElement("strong");
      label.textContent = `${Math.floor(event.elapsed_seconds)}s · ${event.label}`;
      const message = document.createElement("p");
      message.textContent = event.text;
      row.append(label, message);
      this.list.append(row);
      this.index += 1;
    }
    if (this.index) this.status.textContent = `Resumed with ${this.index} of 4 interruptions already delivered.`;
    this.preload();
  }

  async preload() {
    const { scenario, staffVoice, customerVoice } = this.options;
    if (!staffVoice) {
      this.options.onError("No second ElevenLabs voice is available. Staff interruptions will be displayed instead.");
    }
    const clips = scenario.events.flatMap((event) => {
      if (event.id === "wrap") return [];
      const voice = event.speaker === "staff" ? staffVoice : customerVoice;
      return [event.text, event.returned_text].filter(Boolean).map((text) => ({ text, voice }));
    });
    for (const { text, voice } of clips) {
      if (!voice || this.stopped) continue;
      try {
        const response = await fetch("/api/elevenlabs/tts", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text, voice_id: voice }),
        });
        if (!response.ok) throw new Error("Speech unavailable");
        const url = URL.createObjectURL(await response.blob());
        if (this.stopped) URL.revokeObjectURL(url);
        else this.clips.set(text, url);
      } catch (_) {
        this.status.textContent = "Some interruption audio is unavailable; all events will still appear as text.";
      }
    }
  }

  candidate(text) {
    this.responses += 1;
    if (/\b(hold|one moment|give me a moment|be right back)\b/i.test(text)) this.onHold = true;
    if (/\b(i am back|i'm back|i’m back|thank you for waiting|thanks for waiting|let(?:'s| us) (?:finish|resolve|return to))\b/i.test(text)) this.onHold = false;
    if (this.responses >= 2 && /\b(please|assign|handle|call|take over|first aid|safety)\b/i.test(text)) {
      this.options.context("The employee has responded to competing needs. Increase customer impatience slightly; respectfully ask for a specific next step on your original issue. Do not invent another emergency.");
    }
  }

  async tick(elapsed) {
    if (this.stopped || this.busy || this.index >= this.options.scenario.events.length) return;
    const event = this.options.scenario.events[this.index];
    // Spacing adapts to whether a response was captured, not accent or speech fluency.
    if (event.id !== "wrap" && this.index > 0 && this.responses === this.lastResponses && elapsed >= event.at) {
      if (!this.delayed.has(event.id)) {
        this.delayed.add(event.id);
        this.status.textContent = "Allowing 15 extra seconds to address the previous interruption.";
        this.options.context("Give the employee a little more thinking time. Do not add new pressure yet.");
      }
    }
    const due = event.at + (this.delayed.has(event.id) ? 15 : 0);
    if (elapsed < due) return;
    this.busy = true;
    try {
      const text = this.onHold ? event.text : event.returned_text || event.text;
      const url = this.clips.get(text);
      const row = document.createElement("li");
      const label = document.createElement("strong");
      label.textContent = `${String(Math.floor(elapsed / 60)).padStart(2, "0")}:${String(Math.floor(elapsed % 60)).padStart(2, "0")} · ${event.label}`;
      const message = document.createElement("p");
      message.textContent = text;
      // Persist the canonical event first; retries are idempotent.
      await this.options.post({
        event_id: event.id, elapsed_seconds: elapsed, on_hold: this.onHold,
        delivery: "display",
      });
      row.append(label, message);
      this.list.append(row);
      this.options.context(`Simulation event (${event.speaker}): ${text}. This is NOT the employee's speech. You remain the original customer. React to the interruption and remember your original complaint.`);
      if (url) {
        let played = false;
        this.options.quiet(true);
        try {
          this.audio = new Audio(url);
          this.options.record(this.audio);
          await new Promise((resolve) => {
            this.audio.onended = resolve;
            this.audio.onerror = resolve;
            this.audio.play().then(() => { played = true; }).catch(resolve);
          });
          if (played) await this.options.markSpeech(event.id);
          else this.options.onError("Interruption audio could not play. Read the staff message and continue.");
        } finally {
          this.options.quiet(false);
          this.audio = null;
        }
      } else if (event.id !== "wrap") {
        this.options.onError("Interruption delivered as text because its speech clip is unavailable.");
      }
      this.lastResponses = this.responses;
      this.index += 1;
      this.status.textContent = event.id === "wrap"
        ? "Return to the original customer, then finish when the four-minute timer ends."
        : `${this.index} of 4 events delivered. Continue the customer conversation.`;
    } catch (error) {
      this.options.onError(`Pressure event could not be saved: ${error.message}. Retrying automatically.`);
    } finally { this.busy = false; }
  }

  get ready() { return this.index === this.options.scenario.events.length && !this.busy; }
  stop() {
    this.stopped = true;
    if (this.audio) {
      this.audio.pause();
      this.audio.onended?.();
    }
    this.clips.forEach((url) => URL.revokeObjectURL(url));
    this.panel.remove();
  }
}
window.PressureMode = PressureMode;
