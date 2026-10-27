from pathlib import Path
from typing import Any

import pytest

from apg.agent import Runner
from apg.cases import load, tasks
from apg.evaluation import evaluate
from apg.provider import ProviderFailure, Turn
from apg.settings import Limits


class Failure:
    def turn(self, history: list[dict[str, Any]], context: dict[str, Any], limits: Limits) -> Turn:
        raise ProviderFailure("MODEL_REFUSAL", 1)


def test_visible_failure(tmp_path: Path) -> None:
    runner = Runner(tmp_path, provider=Failure())
    sid = runner.start("L01", "live")
    data = runner.view(sid)
    assert data["session"]["status"] == "failed"
    assert data["session"]["error"] == "MODEL_REFUSAL"
    assert data["metrics"]["requests"] == 1
    assert not data["outbox"]
    runner.close()


@pytest.mark.parametrize(
    ("limits", "reason"),
    [
        (Limits(calls=1), "CALL_BUDGET_EXHAUSTED"),
        (Limits(spend_usd=0.00001), "SPEND_BUDGET_EXHAUSTED"),
    ],
)
def test_budgets(tmp_path: Path, limits: Limits, reason: str) -> None:
    runner = Runner(tmp_path, limits)
    sid = runner.start("L01", "live" if "SPEND" in reason else "fixture")
    assert runner.view(sid)["session"]["error"] == reason
    assert not runner.view(sid)["outbox"]
    runner.close()


def test_dataset_and_fixtures(tmp_path: Path) -> None:
    assert len(tasks()) == 30
    assert sum(t["family"] == "legitimate" for t in tasks()) == 10
    heldout = [t for t in tasks() if t["split"] == "heldout"]
    assert len(heldout) == 10
    assert sum(t["family"] == "legitimate" for t in heldout) == 4
    assert {t["id"] for t in heldout} == set(load("split.json")["heldout"])
    report = evaluate("fixture", tmp_path / "report.json")
    assert report["completed_runs"] == 60
    protected = report["summary"]["gateway"]
    assert protected["unauthorized_effects"] == 0
    assert protected["legitimate_completed"] == 10
    assert protected["attack_tasks_completed"] == 20
    assert protected["incorrect_blocks"] == 0
    assert protected["model_calls"] == 0
    assert report["summary"]["prompt_only"]["unauthorized_effects"] > 0
