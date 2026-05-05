#!/usr/bin/env python3
"""Fail CI if bot code calls Telegram bot.send_* outside UsageService."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOT = ROOT / "bot"
ALLOW = BOT / "services" / "usage_service.py"
PATTERN = re.compile(r"\b(?:self\.)?bot\.send_[a-z_]+\s*\(")


def main() -> int:
    violations: list[str] = []
    for path in sorted(BOT.rglob("*.py")):
        if path == ALLOW:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            if not PATTERN.search(line):
                continue
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            violations.append(f"{path.relative_to(ROOT)}:{i}:{stripped}")
    if violations:
        print("bot.send_* used outside bot/services/usage_service.py:\n")
        for item in violations:
            print(item)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
