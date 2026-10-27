# Implementation plan

1. Verify official APIs and resolve compatible Python 3.12 dependencies, then lock exact versions.
2. Implement strict permission types, validation, a filtered document store, and one transactional executor. Test the real boundary first.
3. Persist canonical approvals and LangGraph SQLite checkpoints; prove restart and duplicate resume safety.
4. Add the official OpenAI SDK adapter, bounded agent loop, 30 original cases, isolated paired evaluation, trace replay, and a local UI.
5. Verify deterministic tests, browser flow, clean checkout, Docker, screenshots, documentation, and public GitHub CI. Run live checks only with a locally configured key and spend cap.

The case split is fixed before any agent prompt tuning. Held-out cases are L07-L10 and A15-A20. Requirements and expected effects stay in the evaluator, outside model inputs.

## API verification

Reviewed official documentation on 2026-10-26:

- https://developers.openai.com/api/docs/guides/function-calling : Responses function calls, strict JSON schemas, function_call_output.
- https://docs.langchain.com/oss/python/langgraph/persistence : thread-scoped durable checkpoints.
- https://docs.langchain.com/oss/python/langgraph/interrupts : interrupt and Command(resume=...), with node re-execution.
- https://fastapi.tiangolo.com/tutorial/ : Pydantic request validation and TestClient.
- https://docs.pydantic.dev/latest/concepts/models/ : extra fields forbidden and strict application validation.
- https://docs.astral.sh/uv/guides/integration/docker/ : locked sync in a Python image.
- https://github.com/ethz-spylab/agentdojo : research reference for separating adversarial success and utility. This project uses original cases and does not implement the official benchmark protocol.

Installed API signatures and integration tests provide the final compatibility check. No provider agent framework is used.
