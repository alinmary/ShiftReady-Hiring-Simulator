---
name: ElevenLabs Python connector availability
description: Why a secure Node connector bridge was needed for a Python-first app.
---

The ElevenLabs connection instructions advertised `replit-connectors` for Python, but the package registry returned no matching distribution in this environment.

**Why:** Connector setup instructions alone do not establish that an advertised language SDK can be installed. The installed Node connector SDK did authenticate successfully.

**How to apply:** Verify actual package availability before replacing the bridge with Python calls. Prefer the existing connected integration over asking the user for another API key.
