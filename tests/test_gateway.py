import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from apg.gateway import Gateway
from apg.models import Permissions, decide
from apg.store import Store

ACTION = {"recipient_id": "alex", "body": "Launch June 4."}


@pytest.mark.parametrize(
    ("tool", "args", "reason"),
    [
        ("shell", {}, "UNKNOWN_TOOL"),
        ("read_document", {"document_id": "vault"}, "DOCUMENT_FORBIDDEN"),
        ("read_document", {"document_id": "../vault"}, "INVALID_ARGUMENTS"),
        ("read_document", {"document_id": 1}, "INVALID_ARGUMENTS"),
        ("read_document", {"document_id": "brief", "session_id": "s2"}, "INVALID_ARGUMENTS"),
        ("propose_message", {"recipient_id": "mallory", "body": "hi"}, "RECIPIENT_FORBIDDEN"),
        ("propose_message", {**ACTION, "approved": True}, "INVALID_ARGUMENTS"),
        ("propose_message", {**ACTION, "body": "x" + chr(0x2014)}, "INVALID_ARGUMENTS"),
        ("propose_message", {**ACTION, "body": " "}, "INVALID_ARGUMENTS"),
        ("propose_message", "bad", "INVALID_ARGUMENTS"),
        ("read_document", None, "INVALID_ARGUMENTS"),
        ("search_documents", {"query": "x", "permissions": {}}, "INVALID_ARGUMENTS"),
    ],
)
def test_denied_paths(boundary: tuple[Store, Gateway], tool: str, args: Any, reason: str) -> None:
    store, gateway = boundary
    assert gateway.call("s1", tool, args)["reason"] == reason
    assert store.rows("SELECT * FROM outbox") == []


def test_search_and_reads(boundary: tuple[Store, Gateway]) -> None:
    _, gateway = boundary
    assert gateway.call("s1", "search_documents", {"query": "secret"})["documents"] == []
    assert (
        gateway.call("s1", "read_document", {"document_id": "brief"})["document"]["body"]
        == "Launch June 4."
    )
    assert (
        decide(
            Permissions(documents=[], recipients=[]), "read_document", {"document_id": "brief"}
        ).reason
        == "DOCUMENT_FORBIDDEN"
    )


def pending(boundary: tuple[Store, Gateway]) -> tuple[Store, Gateway, dict[str, Any]]:
    store, gateway = boundary
    result = gateway.call("s1", "propose_message", ACTION)
    assert result["decision"] == "approval_required"
    return store, gateway, store.rows("SELECT * FROM approvals")[0]


def test_approval_and_duplicate_resume(boundary: tuple[Store, Gateway]) -> None:
    store, gateway, row = pending(boundary)
    assert gateway.approve("s1", row["id"], "wrong")["reason"] == "ACTION_CHANGED"
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda _: gateway.approve("s1", row["id"], row["action_hash"]), range(4))
        )
    assert sum(r["reason"] == "EXECUTED" for r in results) == 1
    assert len(store.rows("SELECT * FROM outbox")) == 1
    assert gateway.call("s1", "propose_message", ACTION)["reason"] == "ALREADY_EXECUTED"
    assert gateway.approval_result("s1", row["id"])["reason"] == "EXECUTED"


@pytest.mark.parametrize("change", ["body", "recipient_id", "policy", "expiry", "forbidden"])
def test_approval_binding(boundary: tuple[Store, Gateway], change: str) -> None:
    store, gateway, row = pending(boundary)
    with store.connection() as db:
        if change in {"body", "recipient_id"}:
            action = {**ACTION, change: "mallory"}
            db.execute("UPDATE approvals SET action=?", (json.dumps(action),))
        elif change == "policy":
            db.execute("UPDATE approvals SET policy_version='v0'")
        elif change == "expiry":
            db.execute("UPDATE approvals SET expires=0")
        else:
            db.execute(
                "UPDATE sessions SET permissions=?",
                (Permissions(documents=["brief"], recipients=[]).model_dump_json(),),
            )
    expected = {
        "body": "ACTION_CHANGED",
        "recipient_id": "ACTION_CHANGED",
        "policy": "POLICY_CHANGED",
        "expiry": "APPROVAL_EXPIRED",
        "forbidden": "RECIPIENT_FORBIDDEN",
    }
    assert gateway.approve("s1", row["id"], row["action_hash"])["reason"] == expected[change]
    assert not store.rows("SELECT * FROM outbox")


def test_approval_session_bound(boundary: tuple[Store, Gateway]) -> None:
    store, gateway, row = pending(boundary)
    with store.connection() as db:
        db.execute(
            "INSERT INTO sessions SELECT 's2',case_id,mode,variant,permissions,"
            "status,error,created FROM sessions"
        )
    assert gateway.approve("s2", row["id"], row["action_hash"])["reason"] == "APPROVAL_NOT_FOUND"
    assert gateway.approval_result("s1", row["id"])["reason"] == "APPROVAL_NOT_GRANTED"


def test_replay_has_no_effect(boundary: tuple[Store, Gateway]) -> None:
    store, gateway = boundary
    gateway.call("s1", "propose_message", ACTION)
    before = store.rows("SELECT * FROM approvals")
    assert gateway.replay("s1")[0]["decision"] == "approval_required"
    assert before == store.rows("SELECT * FROM approvals")
    assert not store.rows("SELECT * FROM outbox")


def test_invalid_call_stays_invalid_on_replay(boundary: tuple[Store, Gateway]) -> None:
    store, gateway = boundary
    gateway.call("s1", "propose_message", {**ACTION, "body": "x" + chr(0x2014)})
    assert gateway.replay("s1")[0]["reason"] == "INVALID_ARGUMENTS"
    assert not store.rows("SELECT * FROM outbox")


def test_no_approval_policy_still_enforces_recipient(boundary: tuple[Store, Gateway]) -> None:
    store, gateway = boundary
    with store.connection() as db:
        db.execute(
            "UPDATE sessions SET permissions=?",
            (
                Permissions(
                    documents=["brief"], recipients=["alex"], approval_required=False
                ).model_dump_json(),
            ),
        )
    assert (
        gateway.call("s1", "propose_message", {**ACTION, "recipient_id": "mallory"})["reason"]
        == "RECIPIENT_FORBIDDEN"
    )
    assert gateway.call("s1", "propose_message", ACTION)["reason"] == "EXECUTED"
    assert len(store.rows("SELECT * FROM outbox")) == 1
