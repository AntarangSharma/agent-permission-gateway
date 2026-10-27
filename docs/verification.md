# Verification evidence

This file records executed checks, not planned results. Commands run on Python 3.12.13. Fixture counts are application-boundary evidence only. Live status is separate in `reports/live.json`.

Initial checks executed:

- `.venv/bin/pytest tests/test_gateway.py -q`: 21 policy and transaction tests passed before the model loop was added.
- `.venv/bin/pytest -m 'not browser' -q`: 36 tests passed after the API, SDK adapter, recovery flow, and evaluator were added.
- `APG_CAPTURE=1 .venv/bin/pytest -m browser -q`: passed the actual Chromium journey after replacing a test assertion that required unsafe-eval. The application's CSP stayed restrictive. Real screenshots are in `docs/screenshots/`.
- `docker build -t agent-permission-gateway:local .`: image built successfully.
- `.venv/bin/python scripts/docker_smoke.py`: built image started, health passed, A01 approval produced one authorized outbox message with zero forbidden effects.
- Formatting, lint, strict mypy, and forbidden-character scan passed.

Final make commands, clean-checkout verification, and GitHub Actions outcomes are added after execution below.
