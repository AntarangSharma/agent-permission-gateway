import os
import socket
import subprocess
import time
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import expect, sync_playwright

from apg.cases import ROOT


@pytest.mark.browser
def test_browser_critical_journey(tmp_path: Path) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    command = [
        str(ROOT / ".venv/bin/python"),
        "-m",
        "uvicorn",
        "apg.web:create_app",
        "--factory",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    process = subprocess.Popen(
        command,
        env={**os.environ, "APG_DATA_DIR": str(tmp_path)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if httpx.get(url + "/health").status_code == 200:
                    break
            except httpx.ConnectError:
                pass
            time.sleep(0.1)
        else:
            pytest.fail("Server did not start")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1200}, device_scale_factor=1)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(url)
            assert page.title() == "Agent Permission Gateway"
            page.locator("#case").select_option("A01")
            page.get_by_role("button", name="Run case", exact=True).click()
            page.get_by_text("RECIPIENT_FORBIDDEN", exact=True).wait_for()
            page.get_by_role("button", name="Approve exact message").wait_for()
            assert page.locator("#outbox").inner_text() == "No messages executed."
            if os.getenv("APG_CAPTURE") == "1":
                (ROOT / "docs/screenshots").mkdir(exist_ok=True)
                page.screenshot(
                    path=str(ROOT / "docs/screenshots/attack-blocked.png"), full_page=True
                )
            page.reload()
            page.get_by_role("button", name="Approve exact message").wait_for()
            page.get_by_role("button", name="Approve exact message").click()
            page.get_by_text("Task completed", exact=True).wait_for()
            assert page.locator("#outbox .message").count() == 1
            assert "To: alex" in page.locator("#outbox").inner_text()
            page.get_by_role("button", name="Resume saved run").click()
            expect(page.locator("#run")).to_be_enabled()
            assert page.locator("#outbox .message").count() == 1
            page.get_by_role("button", name="Recheck trace").click()
            page.get_by_text(
                "Trace replay complete. Zero model calls and zero executed effects.", exact=True
            ).wait_for()
            assert '"effects_executed": 0' in page.locator("#replay-output").inner_text()
            if os.getenv("APG_CAPTURE") == "1":
                page.screenshot(path=str(ROOT / "docs/screenshots/completed.png"), full_page=True)
            page.get_by_role("button", name="Fresh rerun").click()
            page.get_by_role("button", name="Approve exact message").wait_for()
            assert page.locator("#outbox .message").count() == 0
            assert errors == []
            browser.close()
    finally:
        process.terminate()
        process.communicate(timeout=10)
