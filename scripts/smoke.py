"""Health and demo checks shared by native and container verification."""

import argparse
import time

import httpx


def smoke(url: str) -> None:
    with httpx.Client(base_url=url) as client:
        for _ in range(100):
            try:
                if client.get("/health").status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        else:
            raise RuntimeError("Health failed")
        client.get("/").raise_for_status()
        headers = {"X-CSRF-Token": client.cookies["apg_csrf"], "Origin": url}
        data = (
            client.post("/api/runs", json={"case_id": "A01"}, headers=headers)
            .raise_for_status()
            .json()
        )
        assert data["session"]["status"] == "waiting"
        assert data["outbox"] == []
        assert any(e["reason"] == "RECIPIENT_FORBIDDEN" for e in data["events"])
        approval = data["approvals"][0]
        endpoint = f"/api/runs/{data['session']['id']}"
        result = (
            client.post(
                endpoint + "/approve",
                json={"approval_id": approval["id"], "action_hash": approval["action_hash"]},
                headers=headers,
            )
            .raise_for_status()
            .json()
        )
        assert result["outcome"]["completion"]
        assert result["outcome"]["unauthorized_effects"] == 0
        assert len(result["outbox"]) == 1
        again = (
            client.post(endpoint + "/resume", json={}, headers=headers).raise_for_status().json()
        )
        assert len(again["outbox"]) == 1
        print("Health, denied redirection, exact approval, and duplicate resume smoke passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    smoke(parser.parse_args().url)
