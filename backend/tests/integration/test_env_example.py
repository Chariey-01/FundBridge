"""`.env.example` documents every setting the application reads, and contains no real secrets."""

from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
READS = re.compile(r'''(?:os\.environ\.get|_setting|_flag|_int|setting|config\.get)\(\s*(?:[a-z_]+,\s*)?["']([A-Z][A-Z0-9_]{2,})["']'''
                   r'''|envvar=["']([A-Z][A-Z0-9_]{2,})["']''')
FLASK_INTERNAL = {"TESTING"}


def _documented() -> set[str]:
    return set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", (BACKEND / ".env.example").read_text(), re.M))


def test_every_setting_read_by_the_app_is_documented():
    read = set()
    for source in (BACKEND / "app").rglob("*.py"):
        for a, b in READS.findall(source.read_text()):
            read.add(a or b)
    missing = sorted(read - _documented() - FLASK_INTERNAL)
    assert len(read) > 40 and missing == [], f"add these to backend/.env.example: {missing}"


def test_env_example_has_no_real_secrets():
    text = (BACKEND / ".env.example").read_text()
    for line in text.splitlines():
        if line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.endswith(("SECRET", "_KEY", "_TOKEN", "PASSWORD")):  # secret-shaped names
            assert value == "" or value.startswith("replace-with-"), f"{key} must be empty or a placeholder"
    assert not re.search(r"sk-[A-Za-z0-9]{20,}|atsk_[A-Za-z0-9]{20,}", text)
