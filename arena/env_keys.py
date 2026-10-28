"""Keys from environment variables, for the program only: values are returned, never printed or logged.

A .env file next to this one (copied from .env.example) is read first; variables already set in the environment win.
"""
from __future__ import annotations

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent / ".env"


def _load() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.strip().partition("=")
        if sep and name and not name.startswith("#"):
            os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


_load()


def obter(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not set (see .env.example)")
    return value
