import { Router, type IRouter } from "express";
import { ReplitConnectors } from "@replit/connectors-sdk";

const router: IRouter = Router();
const connectors = new ReplitConnectors();

router.get("/elevenlabs/voices", async (_req, res) => {
  try {
    const response = await connectors.proxy(
      "elevenlabs",
      "/v1/voices?show_legacy=true",
    );
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      res.status(response.status).json({ error: body });
      return;
    }

    const voices = Array.isArray((body as { voices?: unknown[] }).voices)
      ? ((body as { voices: Array<Record<string, unknown>> }).voices ?? [])
      : [];
    res.json({
      voices: voices.slice(0, 30).map((voice) => ({
        voice_id: voice["voice_id"],
        name: voice["name"],
        labels: voice["labels"],
      })),
    });
  } catch (error) {
    res.status(502).json({
      error: error instanceof Error ? error.message : "ElevenLabs request failed",
    });
  }
});

router.post("/elevenlabs/tts", async (req, res) => {
  const text = typeof req.body?.text === "string" ? req.body.text.trim() : "";
  const voiceId =
    typeof req.body?.voice_id === "string" ? req.body.voice_id.trim() : "";

  if (!text || text.length > 2500 || !voiceId) {
    res.status(400).json({ error: "A voice and a short text reply are required." });
    return;
  }

  try {
    const response = await connectors.proxy(
      "elevenlabs",
      `/v1/text-to-speech/${encodeURIComponent(voiceId)}?output_format=mp3_44100_128`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text,
          model_id: "eleven_multilingual_v2",
          voice_settings: {
            stability: 0.45,
            similarity_boost: 0.75,
            use_speaker_boost: true,
          },
        }),
      },
    );

    if (!response.ok) {
      const detail = await response.text();
      res.status(response.status).json({ error: detail || "Speech generation failed." });
      return;
    }

    res.setHeader("Content-Type", "audio/mpeg");
    res.setHeader("Cache-Control", "no-store");
    res.send(Buffer.from(await response.arrayBuffer()));
  } catch (error) {
    res.status(502).json({
      error: error instanceof Error ? error.message : "ElevenLabs request failed",
    });
  }
});

export default router;
