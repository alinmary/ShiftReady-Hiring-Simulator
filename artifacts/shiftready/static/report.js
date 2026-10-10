document.addEventListener("DOMContentLoaded", () => {
  const decision = document.getElementById("ownerDecision");
  if (decision) {
    decision.addEventListener("change", async () => {
      const status = document.getElementById("decisionSave");
      status.textContent = "Saving…";
      try {
        const response = await fetch(`/api/candidates/${decision.dataset.candidateId}/decision`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ decision: decision.value }),
        });
        if (!response.ok) throw new Error("Could not save decision.");
        status.textContent = "Decision saved";
      } catch (error) {
        status.textContent = error.message;
      }
    });
  }
  const audio = document.getElementById("reportAudio");
  document.querySelectorAll("[data-play-at]").forEach((button) => {
    button.addEventListener("click", () => {
      if (!audio) return;
      audio.currentTime = Number(button.dataset.playAt) || 0;
      audio.play().catch(() => {});
    });
  });
});
