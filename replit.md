# ShiftReady

Python-first retail voice simulations with evidence-based interview reports for human hiring reviewers.

## Run & Operate

- `python artifacts/shiftready/app.py` — Python web app; registered root preview workflow supplies PORT
- `pnpm --filter @workspace/api-server run dev` — secure ElevenLabs connector bridge at `/api` (port 8080)
- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from the OpenAPI spec
- Python dependencies are in `pyproject.toml` and `uv.lock`; installed with the Replit package manager.

## Stack

- Application: Python 3.13, FastAPI, Jinja2, SQLite.
- Browser: minimal JavaScript for microphone capture, live calls, recording and playback.
- AI: managed Anthropic Sonnet for the typed fallback; Opus for reports and round-two scenarios.
- Live speech: ElevenLabs conversational agent using Sonnet, interruptions, streaming speech and dynamic scenario variables.
- Existing Express service is only the connector/SDK bridge, not the primary application.

## Where things live

- `artifacts/shiftready/`: Python routes, SQLite store, templates and browser assets.
- `artifacts/shiftready-web/`: registered preview service; serves the Python app, not the unused React scaffold.
- `artifacts/api-server/src/routes/`: ElevenLabs connector bridge and browser speech SDK delivery.
- FastAPI publishes its Python API contract at `/openapi.json`; bridge contract is `lib/api-spec/openapi.yaml`.
- Local SQLite database and recordings live under `artifacts/shiftready/data`, excluded from Git and publishing.

## Architecture decisions

- User explicitly requested Python. Keep application logic, persistence and scoring in Python; browser microphone APIs require JavaScript.
- The demo is local-first with a single owner and no authentication, as requested in the supplied plan. Do not treat it as a production hiring system.
- The Python connector package was unavailable; use the connected SDK rather than asking for an ElevenLabs key.
- AI scores are advisory. Compute thresholds in code; insufficient recording/transcript evidence must yield a retest recommendation.

## Product

- Three retail customer calls, invite links, microphone/full-call recording, typed fallback, ranked role groups, seven-score reports, timestamped audio evidence, owner decisions and focused second-round comparisons.
- Five seeded candidate reports are explicitly demo examples, with no fabricated candidate audio.

## User preferences

- Primary coding language: Python.

## Gotchas

- Root preview serves Python. `/api` is reserved for the connector bridge; Python mutations use `/sr-api`.
- Live calls require microphone permission and ElevenLabs agent credits. Failures are surfaced before using the turn-based fallback.
- Browser microphone statistics are approximate, not validated measures of personality, accent or fluency. Human reviewers must listen to the evidence.
- Local files do not provide durable multi-instance production storage. Add owner access controls, private durable storage and an agreed retention/consent policy before real hiring use.

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
