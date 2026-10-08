"""Configuration, read from the environment at call time."""

import os
from pathlib import Path


def unpaywall_email() -> str | None:
    return os.environ.get("UNPAYWALL_EMAIL") or None


def s2_api_key() -> str | None:
    return os.environ.get("S2_API_KEY") or None


def openalex_api_key() -> str | None:
    return os.environ.get("OPENALEX_API_KEY") or None


def logseq_api_url() -> str:
    return (os.environ.get("LOGSEQ_API_URL") or "http://localhost:12315").rstrip("/")


def logseq_api_token() -> str | None:
    return os.environ.get("LOGSEQ_API_TOKEN") or None


def second_brain_path() -> Path | None:
    value = os.environ.get("SECOND_BRAIN_PATH")
    return Path(value).expanduser() if value else None


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "sci-paper-mcp"
