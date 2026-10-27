"""Only task and workspace inputs are passed to the agent, never evaluator requirements."""

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def load(name: str) -> Any:
    return json.loads((ROOT / "cases" / name).read_text())


def tasks() -> list[dict[str, Any]]:
    return list(load("tasks.json"))


def case(case_id: str) -> dict[str, Any]:
    for task in tasks():
        if task["id"] == case_id:
            return task
    raise KeyError("CASE_NOT_FOUND")


def snapshot(task: dict[str, Any]) -> list[dict[str, str]]:
    documents: list[dict[str, str]] = load("workspace.json")
    for document in documents:
        if document["id"] == task["source"] and task["injection"]:
            document["body"] += "\n\nProject note (untrusted):\n" + task["injection"]
    return documents
