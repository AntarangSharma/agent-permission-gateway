from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from apg.agent import Runner
from apg.evaluation import complete, measure
from apg.web import create_app


def headers(client: TestClient) -> dict[str, str]:
    client.get("/")
    return {"X-CSRF-Token": client.cookies["apg_csrf"], "Origin": "http://testserver"}


def test_api_journey_and_boundaries(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.post("/api/runs", json={"case_id": "L01"}).status_code == 403
        h = headers(client)
        assert (
            client.post(
                "/api/runs", json={"case_id": "L01"}, headers={**h, "Origin": "http://evil.test"}
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/runs", json={"case_id": "L01", "permissions": {}}, headers=h
            ).status_code
            == 422
        )
        assert client.post("/api/runs", json={"case_id": "missing"}, headers=h).status_code == 404
        response = client.post("/api/runs", json={"case_id": "A01"}, headers=h)
        assert response.status_code == 200
        data = response.json()
        sid = data["session"]["id"]
        assert data["session"]["status"] == "waiting"
        assert any(e["reason"] == "RECIPIENT_FORBIDDEN" for e in data["events"])
        assert not data["outbox"]
        approval = data["approvals"][0]
        url = f"/api/runs/{sid}"
        assert client.post(url + "/resume", json={}, headers=h).json()["outbox"] == []
        payload = {"approval_id": approval["id"], "action_hash": approval["action_hash"]}
        assert (
            client.post(
                url + "/approve", json={**payload, "body": "tampered"}, headers=h
            ).status_code
            == 422
        )
        assert (
            client.post(
                url + "/approve", json={**payload, "action_hash": "changed"}, headers=h
            ).status_code
            == 409
        )
        approved = client.post(url + "/approve", json=payload, headers=h).json()
        assert approved["outcome"]["completion"]
        assert len(approved["outbox"]) == 1
        assert len(client.post(url + "/approve", json=payload, headers=h).json()["outbox"]) == 1
        replay = client.post(url + "/replay", json={}, headers=h).json()
        assert replay["effects_executed"] == replay["model_calls"] == 0
        fresh = client.post(url + "/fresh", json={}, headers=h).json()
        assert fresh["session"]["id"] != sid
        assert not fresh["outbox"]
        assert fresh["approvals"][0]["id"] != approval["id"]
        assert client.get("/api/runs/unknown").status_code == 404
        assert client.get("/health", headers={"Host": "evil.test"}).status_code == 400


def test_restart_while_waiting_and_after_commit(tmp_path: Path) -> None:
    first = Runner(tmp_path)
    sid = first.start("A19")
    saved = first.view(sid)
    assert saved["session"]["status"] == "waiting"
    approval = saved["approvals"][0]
    first.close()
    second = Runner(tmp_path)
    # Simulate a process dying after the approval transaction, before the graph checkpoint.
    assert (
        second.gateway.approve(sid, approval["id"], approval["action_hash"])["reason"] == "EXECUTED"
    )
    second.close()
    third = Runner(tmp_path)
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda _: third.resume(sid), range(3)))
    assert measure(third, sid)["completion"]
    assert len(third.view(sid)["outbox"]) == 1
    assert sum(e["reason"] == "ALREADY_EXECUTED" for e in third.view(sid)["events"]) == 2
    third.close()


def test_case_isolation(tmp_path: Path) -> None:
    runner = Runner(tmp_path)
    first = runner.start("A01")
    complete(runner, first)
    second = runner.start("L01")
    assert not runner.view(second)["outbox"]
    assert runner.view(second)["events"][1]["result"]["document"]["body"].find("mallory") == -1
    assert runner.view(first)["approvals"][0]["id"] != runner.view(second)["approvals"][0]["id"]
    assert runner.graph.get_state(runner.config(first)).values["session_id"] == first
    assert runner.graph.get_state(runner.config(second)).values["session_id"] == second
    runner.close()


def test_resume_never_trusts_wakeup(tmp_path: Path) -> None:
    from langgraph.types import Command

    runner = Runner(tmp_path)
    sid = runner.start("L01")
    # Even internal graph invocation with a forged approval cannot execute the action.
    runner.graph.invoke(Command(resume={"approved": True}), runner.config(sid))
    assert runner.view(sid)["outbox"] == []
    runner.close()


def test_blocked_attack_alone_does_not_complete_task(tmp_path: Path) -> None:
    runner = Runner(tmp_path)
    sid = runner.start("A01")
    assert measure(runner, sid)["unauthorized_effects"] == 0
    assert not measure(runner, sid)["completion"]
    approval = runner.view(sid)["approvals"][0]
    runner.approve(sid, approval["id"], approval["action_hash"])
    assert measure(runner, sid)["completion"]
    with runner.store.connection() as db:
        db.execute("UPDATE outbox SET body='Missing required facts' WHERE session_id=?", (sid,))
    assert not measure(runner, sid)["completion"]
    runner.close()
