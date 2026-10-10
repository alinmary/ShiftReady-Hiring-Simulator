#!/usr/bin/env bash
# Run the Python and JavaScript test suites for ShiftReady.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run pytest -q artifacts/shiftready/tests
node artifacts/shiftready/tests/pressure-mode.test.cjs
