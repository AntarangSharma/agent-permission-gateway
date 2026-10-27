"""Local, same-origin API and server-rendered inspector."""

import hmac
import json
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from apg.agent import Runner
from apg.cases import ROOT, case, tasks
from apg.evaluation import measure
from apg.models import StrictModel
from apg.settings import data_root

ASSETS = Path(__file__).parent


class StartRequest(StrictModel):
    case_id: str
    mode: Literal["fixture", "live"] = "fixture"
    variant: Literal["gateway", "prompt_only"] = "gateway"


class ApprovalRequest(StrictModel):
    approval_id: str
    action_hash: str


def create_app(root: Path | None = None) -> FastAPI:
    runner = Runner(root or data_root())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        runner.close()

    app = FastAPI(title="Agent Permission Gateway", lifespan=lifespan)
    app.state.runner = runner
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )
    app.mount("/static", StaticFiles(directory=ASSETS / "static"), name="static")
    templates = Jinja2Templates(directory=ASSETS / "templates")

    @app.middleware("http")
    async def local_boundary(request: Request, call_next: Any) -> Any:
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            expected = str(request.base_url).rstrip("/")
            if origin and origin != expected:
                return JSONResponse({"detail": "CROSS_ORIGIN_REJECTED"}, status_code=403)
            if request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}:
                return JSONResponse({"detail": "CROSS_ORIGIN_REJECTED"}, status_code=403)
            cookie, header = (
                request.cookies.get("apg_csrf", ""),
                request.headers.get("x-csrf-token", ""),
            )
            if not cookie or not header or not hmac.compare_digest(cookie, header):
                return JSONResponse({"detail": "CSRF_REJECTED"}, status_code=403)
            if request.headers.get("content-type", "").split(";")[0] != "application/json":
                return JSONResponse({"detail": "JSON_REQUIRED"}, status_code=415)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(KeyError)
    async def not_found(request: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse({"detail": str(exc).strip("'")}, status_code=404)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> Any:
        token = secrets.token_urlsafe(32)
        response = templates.TemplateResponse(
            request=request, name="index.html", context={"cases": tasks(), "csrf": token}
        )
        response.set_cookie("apg_csrf", token, httponly=True, samesite="strict")
        return response

    @app.get("/api/cases/{case_id}")
    def preview(case_id: str) -> dict[str, Any]:
        task = case(case_id)
        from apg.cases import snapshot

        return {"task": task, "documents": [d for d in snapshot(task) if d["id"] == task["source"]]}

    @app.post("/api/runs")
    def start(payload: StartRequest) -> dict[str, Any]:
        session_id = runner.start(payload.case_id, payload.mode, payload.variant)
        return view(session_id)

    @app.get("/api/runs/{session_id}")
    def view(session_id: str) -> dict[str, Any]:
        return {**runner.view(session_id), "outcome": measure(runner, session_id)}

    @app.post("/api/runs/{session_id}/approve")
    def approve(session_id: str, payload: ApprovalRequest) -> dict[str, Any]:
        result = runner.approve(session_id, payload.approval_id, payload.action_hash)
        if result["reason"] not in {"EXECUTED", "ALREADY_EXECUTED", "APPROVAL_USED"}:
            raise HTTPException(409, detail=result["reason"])
        return view(session_id)

    @app.post("/api/runs/{session_id}/resume")
    def resume(session_id: str) -> dict[str, Any]:
        runner.resume(session_id)
        return view(session_id)

    @app.post("/api/runs/{session_id}/replay")
    def replay(session_id: str) -> dict[str, Any]:
        return {
            "mode": "trace replay",
            "model_calls": 0,
            "effects_executed": 0,
            "checks": runner.gateway.replay(session_id),
        }

    @app.post("/api/runs/{session_id}/fresh")
    def fresh(session_id: str) -> dict[str, Any]:
        old = runner.store.session(session_id)
        return start(StartRequest(case_id=old["case_id"], mode=old["mode"], variant=old["variant"]))

    @app.get("/api/results")
    def results() -> dict[str, Any]:
        reports = {}
        for mode in ["fixtures", "live"]:
            path = ROOT / "reports" / f"{mode}.json"
            if path.exists():
                reports[mode] = json.loads(path.read_text())
        return reports

    return app
