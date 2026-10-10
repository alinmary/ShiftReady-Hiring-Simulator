---
name: ElevenLabs English live-agent compatibility
description: A live-agent model restriction that was absent from the general TTS setup guide.
---

The live API rejected an English agent configured with `eleven_flash_v2_5`, saying English agents must use Turbo or Flash v2. The ordinary TTS model list is not a live-agent compatibility list.

**Why:** A schema-valid TTS configuration can still be rejected by the conversational-agent service.

**How to apply:** Keep English live agents on a provider-accepted conversational model and verify the create-agent endpoint before changing model versions.
