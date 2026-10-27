"""One agent loop with durable SQLite interrupts and bounded model requests."""

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from apg.cases import case, snapshot
from apg.gateway import Gateway
from apg.models import Permissions, canonical, tool_schemas
from apg.provider import FixtureProvider, LiveProvider, Provider, ProviderFailure
from apg.settings import Limits
from apg.store import Store


class State(TypedDict):
    session_id: str
    history: list[dict[str, Any]]
    pending: list[dict[str, Any]]
    waiting: dict[str, Any]
    done: bool
    error: str
    summary: str
    metrics: dict[str, Any]


class Runner:
    def __init__(self, root: Path, limits: Limits | None = None, provider: Provider | None = None):
        self.store = Store(root)
        self.gateway = Gateway(self.store)
        self.limits = limits or Limits.environment()
        self.provider = provider
        self.lock = threading.RLock()
        self.connection = sqlite3.connect(root / "checkpoints.sqlite", check_same_thread=False)
        self.checkpointer = SqliteSaver(self.connection)
        builder = StateGraph(State)
        builder.add_node("model", self.model)
        builder.add_node("tools", self.tools)
        builder.add_node("approval", self.approval)
        builder.add_edge(START, "model")
        builder.add_conditional_edges("model", lambda s: END if s["done"] else "tools")
        builder.add_conditional_edges("tools", lambda s: "approval" if s["waiting"] else "model")
        builder.add_edge("approval", "model")
        self.graph = builder.compile(checkpointer=self.checkpointer)

    def close(self) -> None:
        self.connection.close()

    @staticmethod
    def config(session_id: str) -> Any:
        return {"configurable": {"thread_id": session_id}, "recursion_limit": 320}

    def model(self, state: State) -> dict[str, Any]:
        session = self.store.session(state["session_id"])
        context = {
            "task": case(session["case_id"]),
            "permissions": json.loads(session["permissions"]),
        }
        metrics = dict(state["metrics"])
        metrics.setdefault("unknown_usage_requests", 0)
        live = session["mode"] == "live"
        limits = self.limits.model_copy(deep=True)
        remaining = limits.calls - metrics["requests"]
        limits.retries = min(limits.retries, max(0, remaining - 1))
        size = (
            len(canonical(state["history"]).encode())
            + len(canonical(tool_schemas()).encode())
            + 4000
        )
        reserve = (
            size * limits.input_per_million + limits.output_tokens * limits.output_per_million
        ) / 1_000_000
        reserve *= limits.retries + 1
        reason = ""
        if metrics["turns"] >= limits.calls or (live and remaining <= 0):
            reason = "CALL_BUDGET_EXHAUSTED"
        elif metrics["latency_seconds"] >= limits.seconds:
            reason = "TIME_BUDGET_EXHAUSTED"
        elif live and metrics["estimated_usd"] + reserve > limits.spend_usd:
            reason = "SPEND_BUDGET_EXHAUSTED"
        if reason:
            return {"done": True, "error": reason}
        limits.seconds = max(
            0.01, (limits.seconds - metrics["latency_seconds"]) / (limits.retries + 1)
        )
        provider = self.provider or (LiveProvider() if live else FixtureProvider())
        started = time.monotonic()
        metrics["turns"] += 1
        try:
            turn = provider.turn(state["history"], context, limits)
        except ProviderFailure as exc:
            metrics["requests"] += exc.requests
            metrics["unknown_usage_requests"] += exc.requests
            metrics["estimated_usd"] += reserve if exc.requests else 0
            metrics["latency_seconds"] += time.monotonic() - started
            return {"done": True, "error": str(exc), "metrics": metrics}
        metrics["latency_seconds"] += time.monotonic() - started
        metrics["requests"] += turn.requests
        metrics["unknown_usage_requests"] += max(0, turn.requests - 1)
        metrics["estimated_usd"] += reserve / (limits.retries + 1) * max(0, turn.requests - 1)
        metrics["input_tokens"] += turn.input_tokens
        metrics["output_tokens"] += turn.output_tokens
        metrics["estimated_usd"] += (
            turn.input_tokens * limits.input_per_million
            + turn.output_tokens * limits.output_per_million
        ) / 1_000_000
        if len(turn.calls) > 1:
            return {"done": True, "error": "MULTIPLE_CALLS_REJECTED", "metrics": metrics}
        return {
            "history": state["history"] + turn.items,
            "pending": turn.calls,
            "done": not turn.calls,
            "summary": turn.text,
            "metrics": metrics,
        }

    def tools(self, state: State) -> dict[str, Any]:
        call = state["pending"][0]
        result = self.gateway.call(state["session_id"], call["name"], call["arguments"])
        if result["decision"] == "approval_required":
            return {
                "waiting": {"approval_id": result["approval_id"], "call_id": call["call_id"]},
                "pending": [],
            }
        return {"pending": [], "history": state["history"] + [self.output(call["call_id"], result)]}

    def approval(self, state: State) -> dict[str, Any]:
        interrupt({"approval_id": state["waiting"]["approval_id"]})
        # The resume value is only a wakeup. The database receipt is the authority.
        result = self.gateway.approval_result(state["session_id"], state["waiting"]["approval_id"])
        return {
            "waiting": {},
            "history": state["history"] + [self.output(state["waiting"]["call_id"], result)],
        }

    @staticmethod
    def output(call_id: str, result: dict[str, Any]) -> dict[str, Any]:
        return {"type": "function_call_output", "call_id": call_id, "output": canonical(result)}

    def start(self, case_id: str, mode: str = "fixture", variant: str = "gateway") -> str:
        if mode not in {"fixture", "live"} or variant not in {"gateway", "prompt_only"}:
            raise ValueError("INVALID_RUN_MODE")
        task = case(case_id)
        session_id = uuid.uuid4().hex
        documents = snapshot(task)
        permissions = Permissions(
            documents=[d["id"] for d in documents if d["id"] != "restricted_payroll"],
            recipients=["alex"],
        )
        with self.lock:
            with self.store.connection() as db:
                db.execute(
                    "INSERT INTO sessions(id,case_id,mode,variant,permissions,created) "
                    "VALUES (?,?,?,?,?,?)",
                    (
                        session_id,
                        case_id,
                        mode,
                        variant,
                        permissions.model_dump_json(),
                        time.time(),
                    ),
                )
                db.executemany(
                    "INSERT INTO documents VALUES (?,?,?,?)",
                    [(session_id, d["id"], d["title"], d["body"]) for d in documents],
                )
            state: State = {
                "session_id": session_id,
                "history": [{"role": "user", "content": task["task"]}],
                "pending": [],
                "waiting": {},
                "done": False,
                "error": "",
                "summary": "",
                "metrics": {
                    "turns": 0,
                    "requests": 0,
                    "unknown_usage_requests": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "latency_seconds": 0.0,
                    "estimated_usd": 0.0,
                },
            }
            self._invoke(session_id, state)
        return session_id

    def _invoke(self, session_id: str, value: Any) -> None:
        try:
            self.graph.invoke(value, self.config(session_id))
            current = self.graph.get_state(self.config(session_id))
            state = current.values
            status = "waiting" if current.next else ("failed" if state.get("error") else "finished")
            self.store.status(session_id, status, state.get("error") or None)
        except Exception:
            self.store.status(session_id, "failed", "RUN_FAILED")

    def approve(self, session_id: str, approval_id: str, action_hash: str) -> dict[str, Any]:
        with self.lock:
            result = self.gateway.approve(session_id, approval_id, action_hash)
            if result["reason"] in {"EXECUTED", "ALREADY_EXECUTED", "APPROVAL_USED"}:
                self.resume(session_id)
            return result

    def resume(self, session_id: str) -> None:
        with self.lock:
            self.store.session(session_id)
            current = self.graph.get_state(self.config(session_id))
            if current.next:
                waiting = current.values.get("waiting", {})
                if (
                    waiting
                    and self.gateway.approval_result(session_id, waiting["approval_id"])["reason"]
                    != "EXECUTED"
                ):
                    return
                self._invoke(session_id, Command(resume=True) if waiting else None)
            elif current.values:
                self.store.status(
                    session_id,
                    "failed" if current.values.get("error") else "finished",
                    current.values.get("error") or None,
                )

    def view(self, session_id: str) -> dict[str, Any]:
        session = self.store.session(session_id)
        state = self.graph.get_state(self.config(session_id)).values
        approvals = self.store.rows(
            "SELECT * FROM approvals WHERE session_id=? ORDER BY expires", (session_id,)
        )
        for approval in approvals:
            approval["action"] = json.loads(approval["action"])
        events = self.store.rows(
            "SELECT * FROM events WHERE session_id=? ORDER BY id", (session_id,)
        )
        for event in events:
            event["arguments"] = json.loads(
                event["arguments"].replace("\\u2014", "[unsupported character]")
            )
            event["result"] = json.loads(event["result"])
        return {
            "session": session,
            "events": events,
            "approvals": approvals,
            "outbox": self.store.rows("SELECT * FROM outbox WHERE session_id=?", (session_id,)),
            "metrics": state.get("metrics", {}),
            "summary": state.get("summary", ""),
        }
