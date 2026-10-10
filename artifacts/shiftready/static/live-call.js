class LiveCustomerCall {
  constructor({ voiceId, scenario, onMessage, onAudio, onStatus, onError, onInterrupt, onCorrection }) {
    this.options = { voiceId, scenario, onMessage, onAudio, onStatus, onError, onInterrupt, onCorrection };
    this.connection = null;
    this.closed = false;
  }

  async start() {
    if (!window.ElevenLabsClient?.Conversation) throw new Error("Live speech support has not loaded.");
    const response = await fetch("/api/elevenlabs/live/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ voice_id: this.options.voiceId }),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || "The live call could not be connected.");
    const { scenario, onMessage, onAudio, onStatus, onError, onInterrupt } = this.options;
    this.connection = await window.ElevenLabsClient.Conversation.startSession({
      signedUrl: body.signed_url,
      connectionType: "websocket",
      dynamicVariables: {
        customer_name: scenario.customer,
        scenario_brief: scenario.brief,
        pressure: scenario.pressure,
        opening: scenario.opening,
      },
      onMessage: ({ message, role, source }) => {
        if (!this.closed) onMessage(role === "user" || source === "user" ? "candidate" : "customer", message);
      },
      onAudio,
      onModeChange: ({ mode }) => onStatus(mode === "speaking" ? "Customer is speaking — you can interrupt naturally" : "Listening to you"),
      onInterruption: onInterrupt,
      onAgentResponseCorrection: (event) => {
        if (!this.closed) this.options.onCorrection?.(event.original_agent_response, event.corrected_agent_response);
      },
      onError: (message) => onError(message),
      onDisconnect: () => { if (!this.closed) onStatus("Call disconnected — you can continue with typed replies"); },
    });
    return this;
  }

  send(text) { this.connection?.sendUserMessage(text); }
  mute(muted) { this.connection?.setMicMuted(muted); }
  async stop() {
    this.closed = true;
    if (this.connection) await this.connection.endSession();
    this.connection = null;
  }
}
window.LiveCustomerCall = LiveCustomerCall;
