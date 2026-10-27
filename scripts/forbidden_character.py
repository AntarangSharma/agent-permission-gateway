"""Scan authored text and generated human-facing reports without embedding the character."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {
    ".git",
    ".venv",
    ".runtime",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
}
violations = []
for path in ROOT.rglob("*"):
    if not path.is_file() or any(part in EXCLUDED for part in path.relative_to(ROOT).parts):
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        continue
    for number, line in enumerate(text.splitlines(), 1):
        if chr(0x2014) in line:
            violations.append(f"{path.relative_to(ROOT)}:{number}")
if violations:
    print("Forbidden character U+2014 found:\n" + "\n".join(violations))
    sys.exit(1)
print("Forbidden-character scan passed (first-party text and reports).")
