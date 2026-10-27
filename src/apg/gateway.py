"""The only executor. Trusted permissions are loaded by session inside each transaction."""

import hashlib
import json
import sqlite3
import time
import uuid
from typing import Any, cast

from apg.models import TOOL_MODELS, Message, Permissions, canonical, decide
from apg.store import Store


class Gateway:
    def __init__(self, store: Store, approval_ttl: int = 600):
        self.store = store
        self.approval_ttl = approval_ttl

    @staticmethod
    def _session(db: sqlite3.Connection, session_id: str) -> sqlite3.Row:
        row = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row is None:
            raise KeyError("SESSION_NOT_FOUND")
        return cast(sqlite3.Row, row)

    @staticmethod
    def _outbox(db: sqlite3.Connection, session_id: str, action: Message) -> dict[str, Any]:
        # Content-based identity also covers a new call ID after checkpoint re-execution.
        key = hashlib.sha256(f"{session_id}:{action.action_hash()}".encode()).hexdigest()
        cursor = db.execute(
            "INSERT OR IGNORE INTO outbox VALUES (?,?,?,?,?,?)",
            (key, session_id, action.recipient_id, action.body, action.action_hash(), time.time()),
        )
        return {
            "reason": "EXECUTED" if cursor.rowcount else "ALREADY_EXECUTED",
            "execution_key": key,
        }

    def call(self, session_id: str, tool: str, arguments: Any) -> dict[str, Any]:
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            session = self._session(db, session_id)
            permissions = Permissions.model_validate_json(session["permissions"])
            policy = decide(permissions, tool, arguments)
            protected = session["variant"] == "gateway"
            # The baseline bypasses permission/approval decisions, never structural validation.
            malformed = policy.reason in {"UNKNOWN_TOOL", "INVALID_ARGUMENTS"}
            decision = policy.decision if protected or malformed else "allowed"
            reason = policy.reason if protected or malformed else "PROMPT_ONLY_BYPASS"
            result: dict[str, Any] = {"decision": decision, "reason": reason}
            forbidden = 0
            if decision != "blocked":
                parsed = TOOL_MODELS[tool].model_validate(arguments)
                if tool == "search_documents":
                    query = str(arguments["query"]).lower()
                    result["documents"] = [
                        {"document_id": row["id"], "title": row["title"]}
                        for row in db.execute(
                            "SELECT * FROM documents WHERE session_id=?", (session_id,)
                        )
                        if row["id"] in permissions.documents
                        and (query in row["title"].lower() or query in row["body"].lower())
                    ]
                elif tool == "read_document":
                    row = db.execute(
                        "SELECT * FROM documents WHERE session_id=? AND id=?",
                        (session_id, arguments["document_id"]),
                    ).fetchone()
                    if row:
                        result["document"] = {
                            "id": row["id"],
                            "title": row["title"],
                            "body": row["body"],
                        }
                        forbidden = int(policy.reason == "DOCUMENT_FORBIDDEN")
                    else:
                        result.update(decision="blocked", reason="DOCUMENT_NOT_FOUND")
                elif isinstance(parsed, Message):
                    if decision == "approval_required":
                        existing = db.execute(
                            "SELECT id,used FROM approvals WHERE session_id=? AND action_hash=?",
                            (session_id, parsed.action_hash()),
                        ).fetchone()
                        approval_id = existing["id"] if existing else uuid.uuid4().hex
                        if not existing:
                            db.execute(
                                "INSERT INTO approvals VALUES (?,?,?,?,?,?,0)",
                                (
                                    approval_id,
                                    session_id,
                                    canonical(parsed.model_dump()),
                                    parsed.action_hash(),
                                    permissions.version,
                                    time.time() + self.approval_ttl,
                                ),
                            )
                        if existing and existing["used"]:
                            result.update(
                                decision="allowed", **self._outbox(db, session_id, parsed)
                            )
                        else:
                            result["approval_id"] = approval_id
                    else:
                        result.update(self._outbox(db, session_id, parsed))
                        forbidden = int(
                            policy.reason == "RECIPIENT_FORBIDDEN"
                            and result["reason"] == "EXECUTED"
                        )
            # Rejected raw output is represented safely; it never reaches display unchanged.
            safe_arguments = json.dumps(arguments, sort_keys=True, ensure_ascii=True)
            db.execute(
                "INSERT INTO events(session_id,tool,arguments,decision,reason,result,"
                "forbidden,created) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    session_id,
                    tool.replace(chr(0x2014), "?") if isinstance(tool, str) else "[invalid tool]",
                    safe_arguments,
                    result["decision"],
                    result["reason"],
                    canonical(result),
                    forbidden,
                    time.time(),
                ),
            )
            return result

    def approve(self, session_id: str, approval_id: str, action_hash: str) -> dict[str, Any]:
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            session = self._session(db, session_id)
            row = db.execute(
                "SELECT * FROM approvals WHERE id=? AND session_id=?", (approval_id, session_id)
            ).fetchone()
            if row is None:
                return {"reason": "APPROVAL_NOT_FOUND"}
            permissions = Permissions.model_validate_json(session["permissions"])
            if row["used"]:
                return {"reason": "APPROVAL_USED"}
            if row["expires"] <= time.time():
                return {"reason": "APPROVAL_EXPIRED"}
            if row["policy_version"] != permissions.version:
                return {"reason": "POLICY_CHANGED"}
            try:
                action = Message.model_validate_json(row["action"])
            except ValueError:
                return {"reason": "ACTION_CHANGED"}
            if action.action_hash() != row["action_hash"] or action_hash != row["action_hash"]:
                return {"reason": "ACTION_CHANGED"}
            policy = decide(permissions, "propose_message", action.model_dump())
            if policy.decision == "blocked":
                return {"reason": policy.reason}
            result = self._outbox(db, session_id, action)
            db.execute("UPDATE approvals SET used=1 WHERE id=? AND used=0", (approval_id,))
            return result

    def approval_result(self, session_id: str, approval_id: str) -> dict[str, Any]:
        rows = self.store.rows(
            "SELECT * FROM approvals WHERE session_id=? AND id=?", (session_id, approval_id)
        )
        if not rows or not rows[0]["used"]:
            return {"reason": "APPROVAL_NOT_GRANTED"}
        # Recheck on resume, even if a checkpoint carries an apparently approved value.
        row = rows[0]
        permissions = Permissions.model_validate_json(self.store.session(session_id)["permissions"])
        action = Message.model_validate_json(row["action"])
        if row["policy_version"] != permissions.version:
            return {"reason": "POLICY_CHANGED"}
        if action.action_hash() != row["action_hash"]:
            return {"reason": "ACTION_CHANGED"}
        policy = decide(permissions, "propose_message", action.model_dump())
        if policy.decision == "blocked":
            return {"reason": policy.reason}
        return {"reason": "EXECUTED", "action_hash": row["action_hash"]}

    def replay(self, session_id: str) -> list[dict[str, Any]]:
        permissions = Permissions.model_validate_json(self.store.session(session_id)["permissions"])
        return [
            {
                "event_id": row["id"],
                "tool": row["tool"],
                **decide(permissions, row["tool"], json.loads(row["arguments"])).model_dump(),
            }
            for row in self.store.rows(
                "SELECT * FROM events WHERE session_id=? ORDER BY id", (session_id,)
            )
        ]
