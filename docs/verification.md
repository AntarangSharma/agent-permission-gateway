# Verification evidence

This file records executed checks, not planned results. Commands run on Python 3.12.13. Fixture counts are application-boundary evidence only. Live status is separate in `reports/live.json`.

Initial checks executed:

- `.venv/bin/pytest tests/test_gateway.py -q`: 21 policy and transaction tests passed before the model loop was added.
- `.venv/bin/pytest -m 'not browser' -q`: 36 tests passed after the API, SDK adapter, recovery flow, and evaluator were added.
- `APG_CAPTURE=1 .venv/bin/pytest -m browser -q`: passed the actual Chromium journey after replacing a test assertion that required unsafe-eval. The application's CSP stayed restrictive. Real screenshots are in `docs/screenshots/`.
- `docker build -t agent-permission-gateway:local .`: image built successfully.
- `.venv/bin/python scripts/docker_smoke.py`: built image started, health passed, A01 approval produced one authorized outbox message with zero forbidden effects.
- Formatting, lint, strict mypy, and forbidden-character scan passed.

## Final documented commands

| Executed command | Observed result |
| --- | --- |
| `make setup` | Passed with the committed lockfile |
| `make check` | Formatting, lint, strict mypy, and forbidden-character scan passed |
| `make test` | 42 passed, browser test excluded |
| `make eval-fixtures` | 60/60 paired runs; gateway 0 forbidden effects, 10/10 legitimate and 20/20 attack-bearing tasks completed |
| `make browser-test` | 1 actual Chromium journey passed |
| `make docker-smoke` | Built image, health, denied redirection, exact approval, and duplicate resume checks passed |
| `make smoke-live` | Exited 2 from make with API_KEY_MISSING; zero provider requests |
| `make eval-live` | Exited 2 from make with API_KEY_MISSING; zero provider requests |

Fixture prompt-only runs executed 12 forbidden effects in 12/30 runs. Their legitimate utility was 10/10 and attack-bearing utility 13/20. Both variants attempted 19 violations in 113 tool calls, with 0 incorrect blocks in 94 valid calls. Provider calls and tokens were 0 in fixture mode.

## Clean checkout

Created `/private/tmp/apg-clean-verification` with `git clone --no-local` from the committed repository. It had no development virtual environment or .env. Executed `make setup && make check && make test`, then `make demo` and `.venv/bin/python scripts/smoke.py --url http://127.0.0.1:8000`. Setup, checks, deterministic tests, actual loopback startup, health, redirection denial, approval, and duplicate resume passed. This checkout used Python 3.12.9; development and Docker used Python 3.12.13.

## GitHub delivery

Public personal-account repository: https://github.com/AntarangSharma/agent-permission-gateway

[Initial pushed source verification](https://github.com/AntarangSharma/agent-permission-gateway/actions/runs/40464570256) passed both jobs: deterministic checks with browser smoke, and Docker build/startup smoke. The final source also runs this workflow after push. CI uses no API secret or live evaluation.

## Remaining live gate

No API key was visible in the environment or the designated local .env file when the commands above ran. The real-model smoke test, full 30-case paired comparison, live failure/latency/token totals, and target of at least 8/10 legitimate live tasks remain unverified. The application and fixture suite are delivered, with this completion gap stated explicitly. No fixture count is presented as model-quality evidence.
